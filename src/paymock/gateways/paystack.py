"""Drop-in replacement for https://api.paystack.co — the routes your app calls."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from ..delivery import SCENARIOS, engine, scenario_plan
from ..registry import registry
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
    """paymock extension: force a transaction to a status and (optionally)
    auto-deliver its webhook with a failure scenario attached.

    body: {"status": "success", "scenario": "duplicate"|"delayed"|
    "out_of_order"|"none", "delay_seconds": 30}
    """
    status = body.get("status", "success")
    scenario = body.get("scenario", "none")
    if scenario not in SCENARIOS:
        raise HTTPException(400, detail=f"unknown scenario: {scenario} (known: {', '.join(SCENARIOS)})")
    txn = store.settle(reference, status)
    if not txn:
        raise HTTPException(404, detail="Transaction not found")
    raw, headers = build("paystack", txn, status)
    event = "charge.success" if status == "success" else "charge.failed"

    reg = registry.get("paystack")
    queued = 0
    if reg:
        for delivery, delay in scenario_plan(
            gateway="paystack", txn=txn, status=status, scenario=scenario,
            body=raw, headers=headers, url=reg.url, schedule=reg.schedule,
            delay_seconds=body.get("delay_seconds", 30.0),
            build_event=lambda s: build("paystack", txn, s),
        ):
            engine.enqueue(delivery, delay)
            queued += 1
    return {
        "event": event,
        "webhook_body": raw.decode(),
        "webhook_headers": headers,
        "scenario": scenario,
        "auto_deliveries_queued": queued,
    }


@router.post("/_webhooks/register")
def register_webhook(body: dict):
    """Register the local URL that auto-delivered webhooks are POSTed to.

    body: {"url": "http://localhost:3000/webhooks/paystack",
           "schedule": "paystack_live"|"paystack_test"}   (schedule optional)
    """
    url = body.get("url")
    if not url:
        raise HTTPException(400, detail="url is required")
    try:
        reg = registry.register("paystack", url, body.get("schedule"))
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {"registered": url, "schedule": reg.schedule_key,
            "time_scale": engine.time_scale}


@router.get("/_webhooks/deliveries")
def deliveries():
    """Every delivery attempt, newest last — assert retry counts and spacing."""
    return {"deliveries": engine.log("paystack")}
