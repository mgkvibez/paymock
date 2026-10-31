"""FastAPI app factory + entrypoint."""
from __future__ import annotations

from fastapi import FastAPI

from . import __version__
from .gateways import flutterwave, paystack


def create_app(port: int = 9090, time_scale: float | None = None) -> FastAPI:
    import os

    from .delivery import engine
    from .registry import registry

    if time_scale is None:
        time_scale = float(os.getenv("PAYMOCK_TIME_SCALE", "1.0"))
    engine.time_scale = time_scale
    preset = os.getenv("PAYMOCK_WEBHOOK_URL")
    if preset:
        for gw in ("paystack", "flutterwave"):
            registry.register(gw, preset)

    app = FastAPI(title="paymock", version=__version__,
                  description="stripe-mock for African payments. Offline, stateful, signed.")
    app.state.port = port

    # Gateway namespaces mirror the real hosts: mount under /paymock/paystack etc.
    app.include_router(paystack.router, prefix="/paystack")
    app.include_router(flutterwave.router, prefix="/flutterwave")

    @app.get("/health")
    def health():
        from .delivery import engine

        return {"status": "ok", "version": __version__,
                "time_scale": engine.time_scale}

    @app.get("/paymock/deliveries")
    def all_deliveries():
        from .delivery import engine

        return {"deliveries": engine.log()}

    return app


app = create_app()


def serve():
    import os
    import uvicorn

    port = int(os.getenv("PAYMOCK_PORT", "9090"))
    uvicorn.run(create_app(port), host="0.0.0.0", port=port)


def deliver_cli() -> None:
    """`paymock deliver` — fire a scenario at your local webhook URL."""
    import argparse
    import json as _json

    from .scenarios import run
    from .store import Transaction

    ap = argparse.ArgumentParser(prog="paymock deliver",
                                 description="Fire a webhook scenario at a local URL")
    ap.add_argument("--url", required=True, help="webhook receiver, e.g. http://localhost:3000/webhook")
    ap.add_argument("--scenario", default="duplicate",
                    choices=["duplicate", "delayed", "out_of_order", "failed"])
    ap.add_argument("--gateway", default="paystack", choices=["paystack", "flutterwave"])
    ap.add_argument("--reference", required=True)
    ap.add_argument("--amount", type=int, default=50000)
    ap.add_argument("--currency", default="NGN")
    ap.add_argument("--email", default="dev@paymock.local")
    ap.add_argument("--copies", type=int, default=3, help="duplicate scenario: how many copies")
    ap.add_argument("--delay", type=float, default=2.0, help="delayed scenario: seconds to hold")
    ap.add_argument("--schedule", default="live", choices=["test", "live"],
                    help="failed scenario: which real retry schedule")
    ap.add_argument("--time-scale", type=float, default=1.0,
                    help="multiply every retry delay (1/3600 turns hours into seconds)")
    args = ap.parse_args()

    txn = Transaction(reference=args.reference, amount=args.amount,
                      currency=args.currency, email=args.email, gateway=args.gateway)
    result = run(args.scenario, args.url, args.gateway, txn,
                 schedule=args.schedule, time_scale=args.time_scale,
                 delay_s=args.delay, copies=args.copies)
    print(_json.dumps(result, indent=2))


def cli() -> None:
    """`paymock` — serve the sandbox, or `paymock deliver` a scenario."""
    import sys

    argv = sys.argv[1:]
    if argv and argv[0] in ("--version", "-V"):
        print("paymock %s" % __version__)
        return
    if argv and argv[0] in ("--help", "-h"):
        print("paymock %s\n\nusage:\n  paymock              serve the sandbox on $PAYMOCK_PORT (default 9090)\n  paymock deliver ...  fire a scenario at your webhook\n  paymock --version    print the installed version" % __version__)
        return
    if argv and argv[0] == "deliver":
        sys.argv.pop(1)
        sys.argv.pop(1)
        deliver_cli()
    else:
        serve()
