"""Webhook auto-delivery with real gateway retry schedules.

Paystack's documented behavior (paystack.com/docs/payments/webhooks):
- TEST mode:  retries hourly for 10 hours.
- LIVE mode:  retries every 3 minutes for the first 4 tries, then
              hourly for 72 hours.

Developers never see the live schedule in the sandbox, so duplicate and
late webhooks only surface in production. paymock reproduces both,
compressed by --time-scale (3600s becomes 1s at scale 1/3600).
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .webhooks import build
from .store import Transaction

# seconds between retries, after the initial attempt
TEST_SCHEDULE = [3600] * 10
LIVE_SCHEDULE = [180] * 4 + [3600] * 72

SCHEDULES = {"test": TEST_SCHEDULE, "live": LIVE_SCHEDULE}


@dataclass
class DeliveryReport:
    url: str
    event: str
    reference: str
    attempts: list = field(default_factory=list)  # (status_code, elapsed_s)
    delivered: bool = False
    duplicates: int = 0  # extra copies sent after first 2xx (scenario: duplicate)

    @property
    def last_status(self):
        return self.attempts[-1][0] if self.attempts else None


def _post(url: str, payload: bytes, headers: dict) -> int:
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0  # connection refused / unreachable


def deliver(url: str, gateway: str, txn: Transaction, status: str,
            schedule: str = "live", time_scale: float = 1.0,
            secret: str | None = None, max_attempts: int | None = None) -> DeliveryReport:
    """Deliver a signed webhook, retrying on non-2xx per the schedule.

    time_scale multiplies every delay (use 1/3600 to turn hours into
    seconds in tests). max_attempts truncates the schedule locally.
    """
    delays = list(SCHEDULES[schedule])
    if max_attempts is not None:
        delays = delays[: max_attempts - 1]
    payload, headers = build(gateway, txn, status)

    import json as _json
    event = _json.loads(payload).get("event", headers.get("event", ""))
    report = DeliveryReport(url=url, event=event, reference=txn.reference)

    waited = 0.0
    for delay in [0.0] + delays:
        time.sleep(delay * time_scale)
        waited += delay * time_scale
        status_code = _post(url, payload, headers)
        report.attempts.append((status_code, round(waited, 4)))
        if 200 <= status_code < 300:
            report.delivered = True
            break
    return report


def deliver_duplicate(url: str, gateway: str, txn: Transaction, status: str,
                      copies: int = 3, secret: str | None = None) -> DeliveryReport:
    """The production classic: the same event delivered 2+ times.

    Your handler must credit the customer exactly once. Assert that on
    the receiving side.
    """
    payload, headers = build(gateway, txn, status)
    import json as _json
    event = _json.loads(payload).get("event", headers.get("event", ""))
    report = DeliveryReport(url=url, event=event, reference=txn.reference)
    got = 0
    for _ in range(copies):
        code = _post(url, payload, headers)
        report.attempts.append((code, 0.0))
        if 200 <= code < 300:
            got += 1
            if report.delivered is False and got == 1:
                report.delivered = True
    report.duplicates = max(0, got - 1)
    return report


def deliver_out_of_order(url: str, gateway: str, txn: Transaction,
                         secret: str | None = None) -> DeliveryReport:
    """charge.success arrives before the earlier pending event.

    Replays what happens when queues cross: your final state must be
    the success, not the stale pending.
    """
    payload_s, headers_s = build(gateway, txn, "success")
    payload_p, headers_p = build(gateway, txn, "pending")
    import json as _json
    event = _json.loads(payload_s).get("event", headers_s.get("event", ""))
    report = DeliveryReport(url=url, event=event, reference=txn.reference)
    for payload, headers in ((payload_s, headers_s), (payload_p, headers_p)):
        code = _post(url, payload, headers)
        report.attempts.append((code, 0.0))
        if 200 <= code < 300:
            report.delivered = True
    return report
