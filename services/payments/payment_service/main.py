import json
import logging
import os
import time
from contextlib import asynccontextmanager
from uuid import uuid4
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from .auth import authenticated, verifier as jwt_verifier
from .db import Base, Entry, Intent, HistoryBatch, CutoverBinding, database
from .target import verify_target
from .domain import settle, wallet, public_entry
from .telemetry import setup
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

logger = logging.getLogger("payments")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.propagate = False
REQUESTS = Counter("payments_http_requests_total", "Payments requests", ["method", "route", "status"])
DURATION = Histogram("payments_http_duration_seconds", "Payments latency", ["method", "route"])


class PaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    order_id: int = Field(gt=0, le=2147483647)


def create_app(engine=None, sessions=None, verifier=None):
    if engine is None:
        engine, sessions = database(os.environ["DATABASE_URL"])

    @asynccontextmanager
    async def lifespan(app):
        Base.metadata.create_all(engine)
        verify_target(sessions)
        yield
        engine.dispose()

    app = FastAPI(title="Bangkok Homeservice Payments & Wallet", lifespan=lifespan,
                  openapi_url="/payments-openapi.json", docs_url="/payment-docs")
    app.state.verify = verifier or jwt_verifier(os.environ["JWT_ISSUER"], os.environ["JWT_JWKS_URL"])
    if setup("payments"):
        SQLAlchemyInstrumentor().instrument(engine=engine)
        FastAPIInstrumentor.instrument_app(app, excluded_urls="/health,/ready,/metrics")

    @app.middleware("http")
    async def correlation(request, call_next):
        request_id = request.headers.get("x-request-id", "")
        if not request_id or len(request_id) > 128 or not request_id.isprintable():
            request_id = str(uuid4())
        start = time.monotonic()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        if request.url.path not in {"/health", "/ready", "/metrics"}:
            route = getattr(request.scope.get("route"), "path", "unmatched")
            duration = time.monotonic() - start
            REQUESTS.labels(request.method, route, str(response.status_code)).inc()
            DURATION.labels(request.method, route).observe(duration)
            logger.info(json.dumps({"service": "payments", "correlation_id": request_id,
                "method": request.method, "route": route, "status": response.status_code,
                "duration_ms": round(duration * 1000, 2)}))
        return response

    @app.exception_handler(SQLAlchemyError)
    async def database_unavailable(request, error):
        # Do not expose connection strings or SQL parameters to API clients/logs.
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Payments storage temporarily unavailable"}, status_code=503)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        with sessions() as session:
            session.execute(text("SELECT 1"))
            batch=session.get(HistoryBatch,'initial')
            binding=session.get(CutoverBinding,'initial')
            return {"status": "ok", "history_snapshot_sha256":batch.snapshot_hash if batch else None,
                "history_cutover_run_id":binding.run_id if binding else None}

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/api/payments/intents/{order_id}")
    def intent(order_id: int, principal=Depends(authenticated)):
        with sessions() as session:
            order = session.get(Intent, order_id)
            if order is None:
                raise HTTPException(404, "Payment not found")
            if principal.role != "customer" or order.customer_id != principal.user_id:
                raise HTTPException(403, "You do not own this payment")
            return {"order_id": order.order_id, "amount_cents": order.amount_cents,
                    "status": order.status, "method": order.method}

    @app.post("/api/payments/simulate")
    def pay(input: PaymentRequest, request: Request, principal=Depends(authenticated)):
        if principal.role != "customer":
            raise HTTPException(403, "Customer role required")
        return settle(sessions, input.order_id, principal.user_id, request.headers.get("idempotency-key"))

    @app.get("/api/payments/wallet")
    def own_wallet(principal=Depends(authenticated)):
        if principal.role != "provider":
            raise HTTPException(403, "Provider role required")
        return wallet(sessions, principal.user_id)

    @app.get("/api/payments/transactions")
    def own_transactions(principal=Depends(authenticated)):
        if principal.role != "customer":
            raise HTTPException(403, "Customer role required")
        with sessions() as session:
            return [public_entry(row) for row in session.scalars(select(Entry).where(
                Entry.customer_id == principal.user_id).order_by(Entry.id.desc())).all()]
    return app
