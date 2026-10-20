"""Drop-in replacement for https://api.flutterwave.com — the routes your app calls."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from ..delivery import SCENARIOS, engine, scenario_plan
from ..registry import registry
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
    """paymock extension: force a status; auto-deliver with a failure scenario.

    body: {"status": "successful", "scenario": "duplicate"|"delayed"|
    "out_of_order"|"none", "delay_seconds": 30}
    """
    status = body.get("status", "successful")
    scenario = body.get("scenario", "none")
    if scenario not in SCENARIOS:
        raise HTTPException(400, detail=f"unknown scenario: {scenario} (known: {', '.join(SCENARIOS)})")
    txn = store.settle(tx_ref, status)
    if not txn:
        raise HTTPException(404, detail="Transaction not found")
    raw, headers = build("flutterwave", txn, status)

    reg = registry.get("flutterwave")
    queued = 0
    if reg:
        for delivery, delay in scenario_plan(
            gateway="flutterwave", txn=txn, status=status, scenario=scenario,
            body=raw, headers=headers, url=reg.url, schedule=reg.schedule,
            delay_seconds=body.get("delay_seconds", 30.0),
            build_event=lambda s: build("flutterwave", txn, s),
        ):
            engine.enqueue(delivery, delay)
            queued += 1
    return {"webhook_body": raw.decode(), "webhook_headers": headers,
            "scenario": scenario, "auto_deliveries_queued": queued}


@router.post("/_webhooks/register")
def register_webhook(body: dict):
    """Register the local URL auto-delivered webhooks are POSTed to.

    body: {"url": "http://localhost:3000/webhooks/flutterwave"}
    (Flutterwave retry intervals are configurable via PAYMOCK_FLW_SCHEDULE.)
    """
    url = body.get("url")
    if not url:
        raise HTTPException(400, detail="url is required")
    try:
        reg = registry.register("flutterwave", url, body.get("schedule"))
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {"registered": url, "schedule": reg.schedule_key,
            "time_scale": engine.time_scale}


@router.get("/_webhooks/deliveries")
def deliveries():
    return {"deliveries": engine.log("flutterwave")}
