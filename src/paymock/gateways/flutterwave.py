"""Drop-in replacement for https://api.flutterwave.com — the routes your app calls."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from ..store import store
from ..webhooks import build

router = APIRouter()


@router.post("/v3/payments")
def payments(body: dict, request: Request, authorization: str = Header(default="")):
    if not body.get("tx_ref") or "amount" not in body:
        raise HTTPException(400, detail="tx_ref and amount are required")
    txn = store.create(
        gateway="paymock-flutterwave",
        amount=int(body["amount"]) * 100,  # flutterwave uses major units; store kobo
        email=(body.get("customer") or {}).get("email", "test@paymock.dev"),
        currency=body.get("currency", "NGN"),
        reference=body["tx_ref"],
    )
    return {
        "status": "success",
        "message": "Hosted Link",
        "data": {"link": f"http://localhost:{request.app.state.port}/checkout/flutterwave/{txn.reference}"},
    }


@router.get("/v3/transactions/{tx_ref}/verify")
def verify(tx_ref: str):
    txn = store.get(tx_ref)
    if not txn or txn.gateway != "paymock-flutterwave":
        raise HTTPException(404, detail="Transaction not found")
    return {
        "status": "success",
        "data": {
            "id": abs(hash(txn.reference)) % 10_000_000,
            "tx_ref": txn.reference,
            "status": txn.status,
            "amount": txn.amount / 100,
            "currency": txn.currency,
            "customer": {"email": txn.email},
        },
    }


@router.post("/_settle/{tx_ref}")
def settle(tx_ref: str, body: dict):
    status = body.get("status", "successful")
    txn = store.settle(tx_ref, status)
    if not txn:
        raise HTTPException(404, detail="Transaction not found")
    raw, headers = build("flutterwave", txn, status)
    return {"webhook_body": raw.decode(), "webhook_headers": headers}
