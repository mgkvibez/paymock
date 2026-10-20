"""Auto-delivery of signed webhooks to your local URL, with real retry schedules.

paymock's whole point: the official sandboxes never show you live retry
behavior. This engine replays it deterministically on localhost.

Schedules (sources):
- paystack live: retry every 3 minutes for the first 4 tries, then hourly
  for 72 hours (Paystack docs, /docs/payments/webhooks)
- paystack test: hourly for 10 hours (same page)
- flutterwave: retries up to 3 times on non-2xx (Flutterwave engineering
  blog); intervals are NOT officially documented — the defaults below are
  paymock's choice and configurable at registration.

Virtual time: delays are in *gateway* seconds. `time_scale` divides them so
tests can compress hours into milliseconds (scale 1000 -> 1.8ms for a 3-min
retry). Default scale 1.0 = production-faithful waits.
"""
from __future__ import annotations

import heapq
import json
import threading
import time
import urllib.request
from dataclasses import dataclass, field

SCHEDULES: dict[str, list[int]] = {
    # seconds between attempts, in order
    "paystack_live": [180] * 4 + [3600] * 72,
    "paystack_test": [3600] * 10,
    "flutterwave": [60, 300, 900],  # 3 retries; intervals configurable, not official
}

DEFAULT_SCHEDULE = {"paystack": "paystack_live", "flutterwave": "flutterwave"}

SCENARIOS = ("none", "duplicate", "delayed", "out_of_order")


@dataclass
class Delivery:
    gateway: str
    reference: str
    event: str
    body: bytes
    headers: dict[str, str]
    url: str
    schedule: list[int]
    schedule_i: int = 0
    initial_delay: float = 0.0
    attempt: int = 0
    attempts: list[dict] = field(default_factory=list)

    def record(self, status_code: int | None, error: str | None, virtual_at: float) -> dict:
        rec = {
            "reference": self.reference,
            "gateway": self.gateway,
            "event": self.event,
            "attempt": self.attempt,
            "status_code": status_code,
            "ok": status_code is not None and 200 <= status_code < 300,
            "error": error,
            "virtual_at": virtual_at,
        }
        self.attempts.append(rec)
        return rec


class DeliveryEngine:
    """Background thread that POSTs webhooks and retries failures per schedule."""

    def __init__(self):
        self._queue: list[tuple[float, int, Delivery]] = []
        self._seq = 0
        self._lock = threading.Lock()
        self._log: list[dict] = []
        self.time_scale = 1.0
        self._virtual_now = 0.0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- lifecycle -----------------------------------------------------

    def start(self):
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._worker, daemon=True, name="paymock-delivery")
            self._thread.start()

    def stop(self):
        self._stop.set()

    # -- api ------------------------------------------------------------

    def enqueue(self, delivery: Delivery, delay_seconds: float = 0.0):
        self.start()
        with self._lock:
            delivery.initial_delay = float(delay_seconds)
            self._schedule_locked(delivery, delay_seconds)

    def log(self, gateway: str | None = None) -> list[dict]:
        with self._lock:
            return [r for r in self._log if gateway is None or r["gateway"] == gateway]

    # -- internals -----------------------------------------------------

    def _schedule_locked(self, d: Delivery, delay_seconds: float):
        real_delay = float(delay_seconds) / self.time_scale
        due = time.monotonic() + real_delay
        heapq.heappush(self._queue, (due, self._seq, d))
        self._seq += 1

    def _worker(self):
        while not self._stop.is_set():
            now = time.monotonic()
            due_items: list[Delivery] = []
            with self._lock:
                while self._queue and self._queue[0][0] <= now:
                    due_items.append(heapq.heappop(self._queue)[2])
            for d in due_items:
                self._deliver(d)
            time.sleep(0.02)

    def _deliver(self, d: Delivery):
        d.attempt += 1
        # virtual timestamp: first attempt is at schedule position 0's origin;
        # later attempts advance by the schedule gaps
        if d.attempts:
            gap = d.schedule[d.schedule_i - 1] if d.schedule_i else d.schedule[0]
            virtual_at = d.attempts[-1]["virtual_at"] + gap
        else:
            virtual_at = d.initial_delay
        code, err = _post(d.url, d.body, d.headers)
        rec = d.record(code, err, virtual_at)
        with self._lock:
            self._log.append(rec)
        if rec["ok"]:
            return
        if d.schedule_i < len(d.schedule):
            gap = d.schedule[d.schedule_i]
            d.schedule_i += 1
            with self._lock:
                self._schedule_locked(d, gap)


def _post(url: str, body: bytes, headers: dict[str, str]) -> tuple[int | None, str | None]:
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, None
    except urllib.error.HTTPError as e:
        return e.code, str(e)
    except Exception as e:  # connection refused, timeout, etc.
        return None, str(e)


engine = DeliveryEngine()


def scenario_plan(gateway: str, txn, status: str, scenario: str, body: bytes,
                   headers: dict[str, str], url: str, schedule: list[int],
                   delay_seconds: float, build_event) -> list[tuple[Delivery, float]]:
    """Turn a settle call into the deliveries the scenario requires.

    Returns [(delivery, initial_delay_seconds), ...].
    """
    def make(event_status: str, ev_body: bytes | None = None, ev_headers: dict | None = None):
        b, h = build_event(event_status) if ev_body is None else (ev_body, ev_headers)
        return Delivery(gateway=gateway, reference=txn.reference, event=_event_name(event_status),
                        body=b, headers=h, url=url, schedule=schedule)

    if scenario == "duplicate":
        # two identical deliveries: same body bytes, same signature
        return [(make(status), 0.0), (make(status), 0.0)]
    if scenario == "delayed":
        return [(make(status), delay_seconds or 30.0)]
    if scenario == "out_of_order":
        # a failed-charge webhook arrives first, the real success after it
        return [(make("failed"), 0.0), (make(status), delay_seconds or 5.0)]
    return [(make(status), 0.0)]


def _event_name(status: str) -> str:
    return "charge.success" if status == "success" else "charge.failed"
