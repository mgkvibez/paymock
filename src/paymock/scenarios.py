"""Built-in failure scenarios — the ones sandboxes never show you.

duplicate       same event N times (the double-credit killer)
delayed         event held back, then delivered (late webhooks)
out_of_order    success arrives before the stale pending event
failed          target errors; watch the real retry schedule work
"""
from __future__ import annotations

import time

from .retry import deliver, deliver_duplicate, deliver_out_of_order, SCHEDULES
from .store import Transaction
from .webhooks import build, paystack_signature, flutterwave_signature

SCENARIOS = ["duplicate", "delayed", "out_of_order", "failed"]


def run(name: str, url: str, gateway: str, txn: Transaction,
        schedule: str = "live", time_scale: float = 1.0,
        delay_s: float = 2.0, copies: int = 3,
        max_attempts: int = 6) -> dict:
    """Run one scenario against the local URL; returns a summary dict."""
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario {name!r}; expected one of {SCENARIOS}")

    if name == "duplicate":
        r = deliver_duplicate(url, gateway, txn, "success", copies=copies)
        return {"scenario": name, "delivered": r.delivered, "duplicates": r.duplicates,
                "attempts": len(r.attempts), "event": r.event, "reference": r.reference}

    if name == "delayed":
        time.sleep(delay_s)
        r = deliver(url, gateway, txn, "success", schedule="test", time_scale=time_scale, max_attempts=1)
        return {"scenario": name, "delivered": r.delivered, "duplicates": 0,
                "attempts": len(r.attempts), "event": r.event, "reference": r.reference,
                "held_for_s": delay_s}

    if name == "out_of_order":
        r = deliver_out_of_order(url, gateway, txn)
        return {"scenario": name, "delivered": r.delivered, "duplicates": 0,
                "attempts": len(r.attempts), "event": r.event, "reference": r.reference}

    # failed: the endpoint keeps erroring; the schedule should retry
    r = deliver(url, gateway, txn, "success", schedule=schedule,
                time_scale=time_scale, max_attempts=max_attempts)
    return {"scenario": name, "delivered": r.delivered, "duplicates": 0,
            "attempts": len(r.attempts), "event": r.event, "reference": r.reference,
            "schedule": f"{schedule} ({len(SCHEDULES[schedule])} retries)"}
