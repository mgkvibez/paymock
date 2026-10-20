"""In-memory stateful store: transactions survive between requests."""
from __future__ import annotations

import random
import string
import threading
import time
import uuid
from dataclasses import dataclass, field

from pydantic import BaseModel


class Transaction(BaseModel):
    reference: str
    amount: int  # kobo for paystack, cents-equivalent for flutterwave
    currency: str
    email: str
    gateway: str  # paystack | flutterwave
    status: str = "pending"  # pending | success | failed | abandoned
    channel: str = "card"
    created_at: int = field(default_factory=lambda: int(time.time()))
    idempotency_key: str | None = None


@dataclass
class Store:
    txns: dict[str, Transaction] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    secret_keys: dict[str, str] = field(
        default_factory=lambda: {
            "paystack": "sk_test_paymock",
            "flutterwave": "FLWTEST-DEFAULT-KEY",
        }
    )

    def create(self, gateway: str, amount: int, email: str, currency: str, reference: str | None = None, idempotency_key: str | None = None) -> Transaction:
        with self.lock:
            if idempotency_key:
                existing = next((t for t in self.txns.values() if t.idempotency_key == idempotency_key and t.gateway == gateway), None)
                if existing:
                    return existing
            ref = reference or "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
            txn = Transaction(
                reference=ref, amount=amount, currency=currency,
                email=email, gateway=gateway, idempotency_key=idempotency_key,
            )
            self.txns[ref] = txn
            return txn

    def get(self, reference: str) -> Transaction | None:
        return self.txns.get(reference)

    def settle(self, reference: str, status: str) -> Transaction | None:
        with self.lock:
            txn = self.txns.get(reference)
            if txn:
                txn.status = status
            return txn


store = Store()
