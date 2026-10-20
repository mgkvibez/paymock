"""pytest plugin: fixtures that spin paymock and a webhook receiver.

Install paymock and these fixtures are auto-registered (entry point pytest11):

    def test_no_double_credit(paymock, webhook_receiver):
        paymock.register_webhook("paystack", webhook_receiver.url)
        ref = paymock.initialize("paystack", amount=50000)
        paymock.settle("paystack", ref, "success", scenario="duplicate")

        # your app-under-test receives 2 identical charge.success events;
        # credit must happen once:
        events = webhook_receiver.events("charge.success")
        assert len(events) == 2
        assert all(e["data"]["reference"] == ref for e in events)
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http(method: str, url: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise AssertionError(f"{method} {url} -> {e.code}: {detail}") from e


class PaymockHandle:
    """Thin client over a running paymock server."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _url(self, gateway: str, path: str) -> str:
        return f"{self.base_url}/{gateway}{path}"

    def initialize(self, gateway: str = "paystack", amount: int = 50000,
                   email: str = "test@paymock.dev", **extra) -> str:
        if gateway == "paystack":
            body = {"email": email, "amount": amount, **extra}
            path = "/transaction/initialize"
            out = _http("POST", self._url(gateway, path), body)
            return out["data"]["reference"]
        tx_ref = extra.pop("tx_ref", None) or f"tx-{int(time.time() * 1000)}"
        body = {"tx_ref": tx_ref, "amount": amount / 100, **extra}
        _http("POST", self._url(gateway, "/v3/payments"), body)
        return tx_ref

    def settle(self, gateway: str, reference: str, status: str = "success",
               scenario: str = "none", delay_seconds: float = 30.0) -> dict:
        path = f"/_settle/{reference}"
        return _http("POST", self._url(gateway, path),
                     {"status": status, "scenario": scenario,
                      "delay_seconds": delay_seconds})

    def register_webhook(self, gateway: str, url: str, schedule: str | None = None) -> dict:
        return _http("POST", self._url(gateway, "/_webhooks/register"),
                     {"url": url, **({"schedule": schedule} if schedule else {})})

    def deliveries(self, gateway: str | None = None) -> list[dict]:
        if gateway is None:
            return _http("GET", f"{self.base_url}/paymock/deliveries")["deliveries"]
        return _http("GET", self._url(gateway, "/_webhooks/deliveries"))["deliveries"]


class _ReceiverHandler(BaseHTTPRequestHandler):
    receiver: "WebhookReceiver" = None  # type: ignore[assignment]

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        # self.headers is case-insensitive; read the signature here
        sig = self.headers.get("X-Paystack-Signature") or self.headers.get("verif-hash")
        self.receiver.record(body, dict(self.headers), self.path, signature=sig)
        if self.receiver.fail_times > 0:
            self.receiver.fail_times -= 1
            self.send_response(500)
        else:
            self.send_response(200)
        self.end_headers()

    def log_message(self, *args):  # silence
        pass


class WebhookReceiver:
    """Local HTTP sink for auto-delivered webhooks."""

    def __init__(self, fail_times: int = 0):
        self.requests: list[dict] = []
        self.fail_times = fail_times
        self._lock = threading.Lock()
        handler = type("H", (_ReceiverHandler,), {"receiver": self})
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/webhook"
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()

    def record(self, body: bytes, headers: dict, path: str, signature: str | None = None):
        with self._lock:
            self.requests.append({
                "body": body.decode(errors="replace"),
                "signature": signature,
                "path": path,
                "json": json.loads(body) if body else {},
            })

    def events(self, event: str | None = None) -> list[dict]:
        with self._lock:
            return [r for r in self.requests
                    if event is None or r["json"].get("event") == event]

    def count(self) -> int:
        with self._lock:
            return len(self.requests)

    def wait(self, n: int = 1, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.count() >= n:
                return
            time.sleep(0.01)
        raise AssertionError(f"timed out waiting for {n} webhook(s); got {self.count()}")

    def stop(self):
        self._server.shutdown()


@pytest.fixture
def paymock():
    """A running paymock server with compressed time (scale 10000)."""
    from paymock.delivery import engine
    from paymock.main import create_app
    from paymock.registry import registry
    from paymock.store import store

    # reset shared in-process state between tests
    store.txns.clear()
    registry.per_gateway.clear()
    with engine._lock:
        engine._queue.clear()
        engine._log.clear()
    engine.time_scale = float(os.getenv("PAYMOCK_TEST_TIME_SCALE", "10000"))

    port = _free_port()
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(
        create_app(port=port, time_scale=float(os.getenv("PAYMOCK_TEST_TIME_SCALE", "10000"))),
        host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            _http("GET", f"{base}/health")
            break
        except Exception:
            time.sleep(0.05)
    else:
        raise RuntimeError("paymock server did not start")

    yield PaymockHandle(base)
    server.should_exit = True


@pytest.fixture
def webhook_receiver():
    """A local webhook sink; set receiver.fail_times=N to force retries."""
    receiver = WebhookReceiver()
    yield receiver
    receiver.stop()
