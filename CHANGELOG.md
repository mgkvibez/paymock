# Changelog

## v0.2.0 - 2026-10-31

- `paymock --version` and `paymock --help` now exist. Before this the CLI had no
  argument handling at the top level, so `--version` fell through to the server and
  blocked, which meant nobody (including CI) could confirm which build was installed.
- The module version now matches the package version; they had drifted (module
  0.1.0, package 0.2.0), the same split that made 0.1.1 report the wrong version.
- `scripts/verify.sh` added: version consistency, suite, `--version` output check,
  and a help smoke that must exit 0 without starting uvicorn. Every check is
  wrapped in `timeout`, because this CLI's default action is a blocking server.


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
