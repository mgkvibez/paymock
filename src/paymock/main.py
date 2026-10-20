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
