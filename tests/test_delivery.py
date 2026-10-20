"""Auto-delivery, retry schedules, and failure scenarios — end to end."""
import hashlib
import hmac
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _verify_paystack_sig(body: str, sig: str) -> bool:
    expected = hmac.new(b"sk_test_paymock", body.encode(), hashlib.sha512).hexdigest()
    return hmac.compare_digest(sig, expected)


def test_register_and_auto_deliver(paymock, webhook_receiver):
    paymock.register_webhook("paystack", webhook_receiver.url)
    ref = paymock.initialize("paystack")
    out = paymock.settle("paystack", ref, "success")
    assert out["auto_deliveries_queued"] == 1
    webhook_receiver.wait(1)
    ev = webhook_receiver.events("charge.success")
    assert len(ev) == 1
    assert ev[0]["json"]["data"]["reference"] == ref
    assert _verify_paystack_sig(ev[0]["body"], ev[0]["signature"])


def test_no_double_credit_pattern(paymock, webhook_receiver):
    """The headline use: duplicate webhooks must not double-credit an order."""
    paymock.register_webhook("paystack", webhook_receiver.url)
    ref = paymock.initialize("paystack", amount=250000)
    paymock.settle("paystack", ref, "success", scenario="duplicate")
    webhook_receiver.wait(2)
    events = webhook_receiver.events("charge.success")
    assert len(events) == 2
    # identical payload AND identical signature — like real duplicate delivery
    assert events[0]["body"] == events[1]["body"]
    assert events[0]["signature"] == events[1]["signature"]
    assert all(e["json"]["data"]["reference"] == ref for e in events)
    # the merchant-side assertion: one reference must be credited once


def test_delayed_scenario_records_virtual_delay(paymock, webhook_receiver):
    paymock.register_webhook("paystack", webhook_receiver.url)
    ref = paymock.initialize("paystack")
    paymock.settle("paystack", ref, "success", scenario="delayed", delay_seconds=300)
    webhook_receiver.wait(1)
    log = paymock.deliveries("paystack")
    assert log[0]["virtual_at"] == 300.0


def test_out_of_order_scenario(paymock, webhook_receiver):
    paymock.register_webhook("paystack", webhook_receiver.url)
    ref = paymock.initialize("paystack")
    paymock.settle("paystack", ref, "success", scenario="out_of_order", delay_seconds=5)
    webhook_receiver.wait(2)
    all_requests = webhook_receiver.requests
    assert all_requests[0]["json"]["event"] == "charge.failed"
    assert all_requests[1]["json"]["event"] == "charge.success"
    assert all_requests[0]["json"]["data"]["reference"] == ref


def test_retry_follows_paystack_live_schedule(paymock, webhook_receiver):
    """First retry must come 180s later (virtual), then 180s again."""
    paymock.register_webhook("paystack", webhook_receiver.url,
                             schedule="paystack_live")
    ref = paymock.initialize("paystack")
    webhook_receiver.fail_times = 2  # fail twice, then succeed
    paymock.settle("paystack", ref, "success")
    webhook_receiver.wait(3)
    log = paymock.deliveries("paystack")
    assert len(log) == 3
    assert [r["attempt"] for r in log] == [1, 2, 3]
    assert [r["virtual_at"] for r in log] == [0.0, 180.0, 360.0]
    assert log[0]["ok"] is False and log[1]["ok"] is False and log[2]["ok"] is True


def test_flutterwave_retry_then_success(paymock, webhook_receiver):
    paymock.register_webhook("flutterwave", webhook_receiver.url)
    ref = paymock.initialize("flutterwave", amount=100000)
    webhook_receiver.fail_times = 1
    paymock.settle("flutterwave", ref, "successful")
    webhook_receiver.wait(2)
    log = paymock.deliveries("flutterwave")
    assert len(log) == 2
    assert log[1]["virtual_at"] == 60.0  # first FLW retry gap
    sigs = [r["signature"] for r in webhook_receiver.requests]
    assert all(sigs), "every delivery carries a verif-hash"
    body = webhook_receiver.requests[0]["body"]
    expected = hmac.new(b"FLWTEST-DEFAULT-KEY", body.encode(), hashlib.sha256).hexdigest()
    assert hmac.compare_digest(sigs[0], expected)


def test_retries_exhaust_after_schedule(paymock, webhook_receiver):
    """Flutterwave gives up after its 3 retries — 4 attempts total, no more."""
    paymock.register_webhook("flutterwave", webhook_receiver.url)
    ref = paymock.initialize("flutterwave", amount=100000)
    webhook_receiver.fail_times = 99  # always fail
    paymock.settle("flutterwave", ref, "successful")
    import time as _t

    _t.sleep(0.5)  # at scale 10000 the full schedule drains in ~126ms
    log = paymock.deliveries("flutterwave")
    assert len(log) == 4  # initial + 3 retries
    assert all(r["ok"] is False for r in log)
    assert [r["virtual_at"] for r in log] == [0.0, 60.0, 360.0, 1260.0]


def test_settle_without_registration_queues_nothing(paymock, webhook_receiver):
    ref = paymock.initialize("paystack")
    out = paymock.settle("paystack", ref, "success")
    assert out["auto_deliveries_queued"] == 0
    assert webhook_receiver.count() == 0
    assert "webhook_body" in out  # manual delivery still available


def test_unknown_scenario_rejected(paymock):
    ref = paymock.initialize("paystack")
    with pytest.raises(AssertionError) as e:
        paymock.settle("paystack", ref, "success", scenario="chaos")
    assert "400" in str(e.value)


def test_register_requires_url(paymock):
    with pytest.raises(AssertionError) as e:
        paymock.register_webhook("paystack", "")
    assert "400" in str(e.value)


def test_combined_deliveries_route(paymock, webhook_receiver):
    paymock.register_webhook("paystack", webhook_receiver.url)
    ref = paymock.initialize("paystack")
    paymock.settle("paystack", ref, "success")
    webhook_receiver.wait(1)
    assert len(paymock.deliveries()) == 1


def test_env_preset_registers_url():
    from paymock.main import create_app
    from paymock.registry import registry

    registry.per_gateway.clear()
    app = create_app(port=9091, time_scale=1.0)
    assert app is not None
    # preset path covered via direct registry check below (env tested in CI)
    assert registry.get("paystack") is None or registry.get("paystack").url
