"""FastAPI app factory + entrypoint."""
from __future__ import annotations

from fastapi import FastAPI

from . import __version__
from .gateways import flutterwave, paystack


def create_app(port: int = 9090) -> FastAPI:
    app = FastAPI(title="paymock", version=__version__,
                  description="stripe-mock for African payments. Offline, stateful, signed.")
    app.state.port = port

    # Gateway namespaces mirror the real hosts: mount under /paymock/paystack etc.
    app.include_router(paystack.router, prefix="/paystack")
    app.include_router(flutterwave.router, prefix="/flutterwave")

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__}

    return app


app = create_app()


def serve():
    import os
    import uvicorn

    port = int(os.getenv("PAYMOCK_PORT", "9090"))
    uvicorn.run(create_app(port), host="0.0.0.0", port=port)
