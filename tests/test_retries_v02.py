"""v0.2: retry schedules, auto-delivery and scenarios — fully offline."""
import http.server
import json
import threading
import unittest

from paymock.retry import (
    LIVE_SCHEDULE, TEST_SCHEDULE, deliver, deliver_duplicate, deliver_out_of_order,
)
from paymock.scenarios import run, SCENARIOS
from paymock.store import Transaction
from paymock.webhooks import paystack_signature


class Receiver:
    def __init__(self, mode="ok"):
        self.credits, self.received, self.mode = {}, [], mode
        recv = self
        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                if recv.mode == "error":
                    self.send_response(500); self.end_headers(); return
                # verify the signature like real Paystack code should
                sig = self.headers.get("X-Paystack-Signature")
                if sig and sig != paystack_signature(body):
                    self.send_response(401); self.end_headers(); return
                event = json.loads(body)
                ref = event["data"]["reference"]
                recv.credits[ref] = 1 if ref not in recv.credits else recv.credits[ref]
                recv.received.append(event)
                self.send_response(200); self.end_headers()
            def log_message(self, *a): pass
        self.server = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/webhook"

    def close(self):
        self.server.shutdown()


def txn(ref="T-V02", gateway="paystack"):
    return Transaction(reference=ref, amount=50000, currency="NGN",
                       email="me@x.dev", gateway=gateway)


class TestSchedules(unittest.TestCase):
    def test_test_mode_hourly_for_10_hours(self):
        self.assertEqual(TEST_SCHEDULE, [3600] * 10)

    def test_live_mode_3min_then_hourly(self):
        self.assertEqual(LIVE_SCHEDULE, [180] * 4 + [3600] * 72)
        self.assertEqual(len(LIVE_SCHEDULE), 76)


class TestDelivery(unittest.TestCase):
    def setUp(self):
        self.rx = Receiver()

    def tearDown(self):
        self.rx.close()

    def test_deliver_once_on_200(self):
        report = deliver(self.rx.url, "paystack", txn(), "success", max_attempts=2)
        self.assertTrue(report.delivered)
        self.assertEqual(len(report.attempts), 1)
        self.assertEqual(report.attempts[0][0], 200)
        self.assertEqual(self.rx.credits["T-V02"], 1)

    def test_retry_then_success(self):
        # fail twice, then accept: 3 attempts, delays applied per schedule
        calls = {"n": 0}
        orig = self.rx.server.RequestHandlerClass.do_POST
        def flaky(self_h):
            calls["n"] += 1
            if calls["n"] <= 2:
                self_h.send_response(500); self_h.end_headers(); return
            orig(self_h)
        self.rx.server.RequestHandlerClass.do_POST = flaky
        report = deliver(self.rx.url, "paystack", txn("T-RETRY"), "success",
                         schedule="live", time_scale=0.001, max_attempts=4)
        self.assertTrue(report.delivered)
        self.assertEqual(len(report.attempts), 3)
        # delays: 180ms*0.001 twice before success
        self.assertAlmostEqual(report.attempts[1][1], 0.18, places=2)
        self.assertAlmostEqual(report.attempts[2][1], 0.36, places=2)


class TestScenarios(unittest.TestCase):
    def setUp(self):
        self.rx = Receiver()

    def tearDown(self):
        self.rx.close()

    def test_duplicate_no_double_credit(self):
        result = run("duplicate", self.rx.url, "paystack", txn("T-DUP"))
        self.assertEqual(result["duplicates"], 2)
        self.assertEqual(len(self.rx.received), 3)
        self.assertEqual(sum(self.rx.credits.values()), 1)

    def test_out_of_order_final_state_is_success(self):
        run("out_of_order", self.rx.url, "paystack", txn("T-OOO"))
        events = [e["data"]["status"] for e in self.rx.received]
        self.assertEqual(events, ["success", "pending"])

    def test_failed_scenario_reports_undelivered(self):
        rx = Receiver(mode="error")
        try:
            result = run("failed", rx.url, "paystack", txn("T-FAIL"),
                         time_scale=0.001, max_attempts=3)
            self.assertFalse(result["delivered"])
            self.assertEqual(result["attempts"], 3)
        finally:
            rx.close()

    def test_unknown_scenario_raises(self):
        with self.assertRaises(ValueError):
            run("nope", self.rx.url, "paystack", txn())


if __name__ == "__main__":
    unittest.main()
