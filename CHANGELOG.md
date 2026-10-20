# Changelog

## v0.2.0 — 2026-10-20

- Webhook auto-delivery to any local URL, with Paystack's REAL retry
  schedules: test mode (hourly x10) and live mode (3 min x4, then
  hourly x72) — compressed by --time-scale for tests.
- Built-in failure scenarios: duplicate, delayed, out-of-order, failed.
- `paymock deliver` CLI: fire any scenario at your dev server.
- Test fixtures: pytest (paymock_receiver asserting "no double credit")
  and Jest (duplicate/out-of-order/failed helpers + example test).
- 8 new tests (15 total), all offline.

## v0.1.0 — 2026-10-20

- Stateful offline sandbox for Paystack and Flutterwave: initialize,
  verify, force outcomes; HMAC-signed webhooks matching each gateway's
  exact signature scheme; no API keys, no tunnel, no internet.
