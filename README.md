# paymock

[![ci](https://github.com/mgkvibez/paymock/actions/workflows/ci.yml/badge.svg)](https://github.com/mgkvibez/paymock/actions/workflows/ci.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python: 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)

**stripe-mock for African payments.** A stateful, offline mock server for Paystack and Flutterwave — signed webhooks included, no API keys, no tunnel, no live internet.

If you build with Paystack or Flutterwave, you know the pain: brittle sandboxes, webhooks that need a public tunnel, and no way to test the *failure* paths (bank downtime, declined cards, duplicate deliveries) without hoping they happen.

```bash
pipx install git+https://github.com/mgkvibez/paymock.git
```

Not on PyPI yet: `paymock` is reserved for this project and the release workflow is in place,
so `pipx install paymock` will work as soon as the first tag is pushed.

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
6. *Auto-delivery with real retry schedules*: register your local URL and paymock POSTs signed webhooks to it, retrying failures exactly like the live gateways do.
7. *Failure scenarios*: `duplicate`, `delayed`, `out_of_order` webhooks, built in.

## Webhook auto-delivery and retries

The official sandboxes never show you live retry behavior, so duplicate and late webhooks only surface in production. paymock reproduces it on localhost:

    # register where you want webhooks delivered
    POST /paystack/_webhooks/register
    {"url": "http://localhost:3000/webhooks/paystack"}

    # settle a payment and have the webhook auto-delivered, twice
    POST /paystack/_settle/<ref>
    {"status": "success", "scenario": "duplicate"}

    # inspect every delivery attempt (attempt #, status code, timing)
    GET /paystack/_webhooks/deliveries

Retry schedules, in gateway-accurate seconds:

*Paystack live* (per Paystack's docs): every 3 minutes for the first 4 tries, then hourly for 72 hours.
*Paystack test* (same page): hourly, 10 times.
*Flutterwave*: up to 3 retries on non-2xx per Flutterwave's engineering blog. Their intervals are not officially documented — paymock defaults to 60s/300s/900s, marked clearly as our choice, and the schedule is data you can change.

Time compression: delays are gateway seconds divided by `time_scale`. Default 1.0 (production-faithful waits); the test fixtures use 10000, so a 3-minute retry resolves in under 20ms. Set `PAYMOCK_TIME_SCALE` or pass it at app creation.

## Test fixtures: assert "no double credit"

pytest fixtures ship with the package (entry point `pytest11`, auto-registered on install):

    def test_no_double_credit(paymock, webhook_receiver):
        paymock.register_webhook("paystack", webhook_receiver.url)
        ref = paymock.initialize("paystack", amount=50000)
        paymock.settle("paystack", ref, "success", scenario="duplicate")

        events = webhook_receiver.events("charge.success")
        assert len(events) == 2                    # delivered twice...
        assert events[0]["body"] == events[1]["body"]  # ...identically
        # your app under test must credit this order exactly once

`webhook_receiver.fail_times = 2` makes your endpoint fail twice so you can assert the retry schedule from `paymock.deliveries()`.

For Jest (Node 18+), `jest/paymock.js` provides the same flow against a running paymock:

    const collector = webhookCollector(yourExpressApp);
    await paymock.register("paystack", collector.url);
    await paymock.settle("paystack", ref, "success", "duplicate");
    await collector.waitFor(2);
    expect(new Set(collector.events("charge.success").map(e => e.data.reference)).size).toBe(1);

## Why

`stripe-mock` proved how much better payment DX can be. Africa's gateways never got one — so every fintech team in Lagos, Nairobi and Accra re-invents the same test scaffolding. This is that scaffolding, done once, MIT-licensed.

## Roadmap

Monnify, Interswitch and M-Pesa (Daraja) route mocks, and a small dashboard UI to visualize event flow.

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

