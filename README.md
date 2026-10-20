# paymock

**stripe-mock for African payments.** A stateful, offline mock server for Paystack and Flutterwave — signed webhooks included, no API keys, no tunnel, no live internet.

If you build with Paystack or Flutterwave, you know the pain: brittle sandboxes, webhooks that need a public tunnel, and no way to test the *failure* paths (bank downtime, declined cards, duplicate deliveries) without hoping they happen.

```bash
pip install paymock && paymock
```

```python
# your app, unchanged — only base_url changes
import requests

base = "http://localhost:9090/paystack"     # was https://api.paystack.co
init = requests.post(f"{base}/transaction/initialize",
                     json={"email": "me@x.dev", "amount": 50000},
                     headers={"Authorization": "Bearer sk_test_paymock"}).json()

# force the outcome you want to test, get the exact signed webhook
settle = requests.post(f"{base}/_settle/{init['data']['reference']}",
                       json={"status": "success"}).json()

# verify the HMAC signature yourself — same scheme as the real gateway
import hmac, hashlib
assert hmac.compare_digest(
    settle["webhook_headers"]["X-Paystack-Signature"],
    hmac.new(b"sk_test_paymock", settle["webhook_body"].encode(), hashlib.sha512).hexdigest(),
)
```

## What it covers

1. *Paystack*: `POST /transaction/initialize`, `GET /transaction/verify/:ref`, Idempotency-Key replay.
2. *Flutterwave*: `POST /v3/payments`, `GET /v3/transactions/:tx_ref/verify`.
3. *Webhooks*: exact HMAC signatures — `X-Paystack-Signature` (SHA-512) and `verif-hash` (SHA-256) — with the same payload shapes your handlers expect.
4. *Stateful*: transactions persist in memory between requests; `pending` until you settle them, like a real checkout.
5. *Failure injection*: `POST /_settle/:ref {"status": "failed"}` — test your decline and timeout code paths on demand.

## Why

`stripe-mock` proved how much better payment DX can be. Africa's gateways never got one — so every fintech team in Lagos, Nairobi and Accra re-invents the same test scaffolding. This is that scaffolding, done once, MIT-licensed.

## Roadmap

Monnify, Interswitch and M-Pesa route mocks, webhook auto-delivery to a registered local URL, and a small dashboard UI to visualize event flow.

## License

MIT.

## Fire the failure scenarios (v0.2)

The sandbox never shows you live-mode behavior — Paystack retries live
webhooks every 3 minutes for the first 4 tries, then hourly for 72
hours. paymock reproduces that against your local dev server:

```bash
# your app runs at localhost:3000/webhook
paymock deliver --scenario duplicate  --url http://localhost:3000/webhook --reference T-1
paymock deliver --scenario failed     --url http://localhost:3000/webhook --reference T-2 --time-scale 0.001
```

`duplicate` delivers the same event 3 times — your handler must credit
exactly once. `failed` follows the real retry schedule (compressed).
`out_of_order` sends the stale pending event after the success.

Drop-in test fixtures: `fixtures/pytest/` (asserts "no double credit")
and `fixtures/jest/`. M-Pesa Daraja scenarios: planned, not yet built.

