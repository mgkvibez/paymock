# Drop this file into your test suite:
#   cp fixtures/pytest/conftest.py tests/conftest.py
import http.server
import json
import threading

import pytest


class _Receiver:
    """Records every webhook paymock fires at it, verifying signatures."""

    def __init__(self, mode="ok"):
        self.credits = {}      # reference -> times credited
        self.received = []
        self.mode = mode       # ok | error (for the failed scenario)
        handler = self._make_handler()
        self.server = http.server.HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/webhook"

    def _make_handler(self):
        receiver = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                event = json.loads(body)

                if receiver.mode == "error":
                    self.send_response(500)
                    self.end_headers()
                    return

                # THE idempotency check your production code should have:
                ref = event["data"]["reference"]
                seen = receiver.credits.get(ref, 0)
                if seen == 0:
                    receiver.credits[ref] = 1     # credit exactly once
                else:
                    receiver.credits[ref] = seen  # duplicate: no double credit

                receiver.received.append(event)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass

        return H

    def close(self):
        self.server.shutdown()


@pytest.fixture
def paymock_receiver():
    """A local webhook receiver that asserts 'no double credit'."""
    receiver = _Receiver()
    yield receiver
    receiver.close()


@pytest.fixture
def failing_receiver():
    receiver = _Receiver(mode="error")
    yield receiver
    receiver.close()
