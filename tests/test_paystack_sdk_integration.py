"""Real-client integration: official paystackapi SDK + real Flask merchant app.

paymock's equivalent of voxserve's real-model verification: prove the
contract against the real client library and a real merchant-style webhook
consumer, not only our own fixtures.
"""
import hashlib
import hmac
import threading
import time

import pytest

flask = pytest.importorskip("flask")
paystackapi = pytest.importorskip("paystackapi")

from paymock.pytest_plugin import paymock as _paymock_fixture  # noqa: F401

SECRET = "sk_test_paymock"


def _sdk(base_url):
    import paystackapi
    paystackapi.API_URL = f"{base_url}/paystack/"
    paystackapi.SECRET_KEY = SECRET
    from paystackapi.base import Borg
    Borg._shared_state = {}  # reset the singleton between tests/servers
    from paystackapi.transaction import Transaction
    return Transaction(secret_key=SECRET)


@pytest.fixture
def merchant_app():
    """A real merchant endpoint: verifies the signature, credits idempotently."""
    app = flask.Flask("merchant")
    balance = {}
    log = []

    @app.post("/webhook")
    def webhook():
        raw = flask.request.get_data()
        sig = flask.request.headers.get("x-paystack-signature", "")
        expected = hmac.new(SECRET.encode(), raw, hashlib.sha512).hexdigest()
        if not hmac.compare_digest(sig, expected):
            log.append("BAD_SIGNATURE")
            return {"error": "invalid signature"}, 401
        event = flask.request.get_json()
        log.append(event)
        ref = event["data"]["reference"]
        if event["event"] == "charge.success" and ref not in balance:
            balance[ref] = event["data"]["amount"]  # credit ONCE
        return {"received": True}, 200

    server = _run_flask(app)
    yield f"http://127.0.0.1:{server['port']}/webhook", balance, log
    server["shutdown"]()


def _run_flask(app):
    from werkzeug.serving import make_server
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = make_server("127.0.0.1", port, app)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return {"port": port, "shutdown": srv.shutdown}


def test_official_sdk_initialize_and_verify(paymock):
    txn = _sdk(paymock.base_url)
    init = txn.initialize(email="dev@example.com", amount=250000,
                          reference="sdk-int-001")
    body = init if isinstance(init, dict) else init[1]
    data = (body or {}).get("data", {})
    assert data.get("reference") == "sdk-int-001", init
    assert data.get("authorization_url", "").startswith("http"), init
    assert body.get("status") is True, init

    paymock.settle("paystack", "sdk-int-001", "success")

    ver = txn.verify(reference="sdk-int-001")
    vbody = ver if isinstance(ver, dict) else ver[1]
    vdata = (vbody or {}).get("data", {})
    assert vdata.get("status") == "success", ver
    assert vdata.get("amount") == 250000, ver


def test_flask_merchant_credits_exactly_once_under_duplicate(paymock, merchant_app):
    url, balance, log = merchant_app
    paymock.register_webhook("paystack", url)

    txn = _sdk(paymock.base_url)
    init = txn.initialize(email="dev@example.com", amount=10000,
                          reference="dup-001")
    body = init if isinstance(init, dict) else init[1]
    assert (body or {}).get("status") is True, init

    paymock.settle("paystack", "dup-001", "success", scenario="duplicate")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and len(log) < 2:
        time.sleep(0.05)

    assert len(log) == 2, log            # duplicate delivered twice
    assert "BAD_SIGNATURE" not in log    # both signatures verified
    assert balance == {"dup-001": 10000} # credited exactly ONCE
