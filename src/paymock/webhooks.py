"""HMAC-signed webhook event payloads — reproduce gateway signatures exactly."""
from __future__ import annotations

import hashlib
import hmac
import json

from .store import Transaction

PAYSTACK_EVENTS = ["charge.success", "charge.failed"]

def paystack_signature(payload: bytes, secret: str = "sk_test_paymock") -> str:
    """Paystack signs the raw body with HMAC-SHA512."""
    return hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()


def flutterwave_signature(payload: bytes, secret: str = "FLWTEST-DEFAULT-KEY") -> str:
    """Flutterwave 'verify hash' is HMAC-SHA256 of the raw body."""
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def paystack_event(txn: Transaction, status: str) -> dict:
    return {
        "event": "charge.success" if status == "success" else "charge.failed",
        "data": {
            "id": abs(hash(txn.reference)) % 10_000_000,
            "domain": "test",
            "status": status,
            "reference": txn.reference,
            "amount": txn.amount,  # kobo
            "currency": txn.currency,
            "channel": txn.channel,
            "customer": {"email": txn.email},
            "paid_at": txn.created_at,
        },
    }


def flutterwave_event(txn: Transaction, status: str) -> dict:
    return {
        "event": "charge.completed",
        "data": {
            "id": abs(hash(txn.reference)) % 10_000_000,
            "tx_ref": txn.reference,
            "amount": txn.amount / 100,  # flutterwave uses major units
            "currency": txn.currency,
            "status": status,
            "customer": {"email": txn.email},
        },
        "event.type": "CARD_TRANSACTION",
    }


def build(gateway: str, txn: Transaction, status: str) -> tuple[bytes, dict[str, str]]:
    """Return (raw_body, headers) for a webhook, signed with the default test keys."""
    body = json.dumps(
        paystack_event(txn, status) if gateway == "paystack" else flutterwave_event(txn, status)
    ).encode()
    headers = {
        "Content-Type": "application/json",
    }
    if gateway == "paystack":
        headers["X-Paystack-Signature"] = paystack_signature(body)
    else:
        headers["verif-hash"] = flutterwave_signature(body)
    return body, headers
