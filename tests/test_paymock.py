import hashlib
import hmac
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fastapi.testclient import TestClient  # noqa: E402

from paymock.main import create_app  # noqa: E402


def client():
    return TestClient(create_app())


def test_paystack_initialize_and_verify_roundtrip():
    c = client()
    resp = c.post("/paystack/transaction/initialize",
                  json={"email": "me@x.dev", "amount": 50000})
    assert resp.status_code == 200
    ref = resp.json()["data"]["reference"]
    verify = c.get(f"/paystack/transaction/verify/{ref}")
    assert verify.status_code == 200
    assert verify.json()["data"]["status"] == "pending"
    assert verify.json()["data"]["amount"] == 50000


def test_paystack_missing_fields_rejected():
    c = client()
    resp = c.post("/paystack/transaction/initialize", json={"amount": 100})
    assert resp.status_code == 400


def test_paystack_idempotency_key_replays_same_txn():
    c = client()
    headers = {"Idempotency-Key": "same-key"}
    a = c.post("/paystack/transaction/initialize", json={"email": "a@x.dev", "amount": 100}, headers=headers)
    b = c.post("/paystack/transaction/initialize", json={"email": "a@x.dev", "amount": 100}, headers=headers)
    assert a.json()["data"]["reference"] == b.json()["data"]["reference"]


def test_paystack_settle_emits_signed_webhook():
    c = client()
    ref = c.post("/paystack/transaction/initialize",
                 json={"email": "me@x.dev", "amount": 250000}).json()["data"]["reference"]
    settle = c.post(f"/paystack/_settle/{ref}", json={"status": "success"})
    assert settle.status_code == 200
    body = settle.json()["webhook_body"]
    headers = settle.json()["webhook_headers"]
    expected = hmac.new(b"sk_test_paymock", body.encode(), hashlib.sha512).hexdigest()
    assert hmac.compare_digest(headers["X-Paystack-Signature"], expected)
    payload = json.loads(body)
    assert payload["event"] == "charge.success"
    assert payload["data"]["reference"] == ref


def test_flutterwave_payment_and_verify():
    c = client()
    resp = c.post("/flutterwave/v3/payments",
                  json={"tx_ref": "tx-001", "amount": 2500, "customer": {"email": "me@x.dev"}})
    assert resp.status_code == 200
    verify = c.get("/flutterwave/v3/transactions/tx-001/verify")
    assert verify.status_code == 200
    assert verify.json()["data"]["amount"] == 2500  # major units preserved


def test_flutterwave_settle_emits_signed_webhook():
    c = client()
    c.post("/flutterwave/v3/payments", json={"tx_ref": "tx-002", "amount": 1000})
    settle = c.post("/flutterwave/_settle/tx-002", json={"status": "successful"})
    assert settle.status_code == 200
    headers = settle.json()["webhook_headers"]
    body = settle.json()["webhook_body"]
    expected = hmac.new(b"FLWTEST-DEFAULT-KEY", body.encode(), hashlib.sha256).hexdigest()
    assert hmac.compare_digest(headers["verif-hash"], expected)
    assert json.loads(body)["data"]["tx_ref"] == "tx-002"


def test_cross_gateway_reference_isolation():
    c = client()
    c.post("/paystack/transaction/initialize", json={"email": "a@x.dev", "amount": 100, "reference": "shared-ref"})
    flutterwave_verify = c.get("/flutterwave/v3/transactions/shared-ref/verify")
    assert flutterwave_verify.status_code == 404
