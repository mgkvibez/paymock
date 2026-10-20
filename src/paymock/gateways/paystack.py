"""Drop-in replacement for https://api.paystack.co — the routes your app calls."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from ..store import store
from ..webhooks import build

router = APIRouter()


@router.post("/transaction/initialize")
def initialize(body: dict, request: Request, authorization: str = Header(default="")):
    if not body.get("email") or "amount" not in body:
        raise HTTPException(400, detail="email and amount are required")
    txn = store.create(
        gateway="paymock-paystack",
        amount=int(body["amount"]),
        email=body["email"],
        currency=body.get("currency", "NGN"),
        reference=body.get("reference"),
        idempotency_key=request.headers.get("idempotency-key"),
    )
    return {
        "status": True,
        "message": "Authorization URL created",
        "data": {
            "authorization_url": f"http://localhost:{request.app.state.port}/checkout/paystack/{txn.reference}",
            "access_code": txn.reference,
            "reference": txn.reference,
        },
    }


@router.get("/transaction/verify/{reference}")
def verify(reference: str):
    txn = store.get(reference)
    if not txn or txn.gateway != "paymock-paystack":
        raise HTTPException(404, detail="Transaction not found")
    return {
        "status": True,
        "message": "Verification successful",
        "data": {
            "status": txn.status,
            "reference": txn.reference,
            "amount": txn.amount,
            "currency": txn.currency,
            "customer": {"email": txn.email},
        },
    }


@router.post("/_settle/{reference}")
def settle(reference: str, body: dict):
    """paymock extension: force a transaction to success/failed to test each path."""
    status = body.get("status", "success")
    txn = store.settle(reference, status)
    if not txn:
        raise HTTPException(404, detail="Transaction not found")
    raw, headers = build("paystack", txn, status)
    return {"event": "charge.success" if status == "success" else "charge.failed", "webhook_body": raw.decode(), "webhook_headers": headers}
