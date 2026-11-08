import json
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text, update

from .auth import authenticated, build_verifier
from .db import Base, Notification, database, utcnow
from .settings import Settings
from . import faults
from .inbox import mark_read as save_read, public
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from .telemetry import setup
from .metrics import REQUESTS, DURATION

logger = logging.getLogger("notifications")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.propagate = False


def create_app(settings=None, engine=None, sessions=None, verifier=None):
    settings = settings or Settings.from_env()
    if engine is None:
        engine, sessions = database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        Base.metadata.create_all(engine)
        yield
        engine.dispose()

    app = FastAPI(title="Bangkok Homeservice Notifications", lifespan=lifespan)
    provider = setup("notifications")
    if provider:
        SQLAlchemyInstrumentor().instrument(engine=engine)
    app.state.verify_token = verifier or build_verifier(settings)

    @app.middleware("http")
    async def correlation(request: Request, call_next):
        request_id = request.headers.get("x-request-id", "")
        if not request_id or len(request_id) > 128 or not request_id.isprintable():
            request_id = str(uuid4())
        start = time.monotonic()
        config = faults.plan() if request.url.path.startswith("/api/notifications") else {}
        if faults.unavailable(config):
            response = JSONResponse({"detail": "temporarily unavailable (demo fault)"}, status_code=503)
        else:
            fault = request.method == "POST" and faults.take_once(config, request.headers.get("idempotency-key"))
            response = await call_next(request)
            if fault and response.status_code < 400:
                # The handler transaction has committed. Delay/discard its response,
                # never the database write; the caller must retry the same key.
                await asyncio.sleep(min(10, max(0, float(config.get("delay_seconds", 2)))))
                if config["mode"] == "lost_reply":
                    response = JSONResponse({"detail": "reply discarded after commit (demo fault)"}, status_code=503)
        response.headers["x-request-id"] = request_id
        route = getattr(request.scope.get("route"), "path", "unmatched")
        seconds = time.monotonic() - start
        if request.url.path not in {"/health", "/ready", "/metrics"}:
            REQUESTS.labels("notifications", request.method, route, str(response.status_code)).inc()
            DURATION.labels("notifications", request.method, route).observe(seconds)
        current = trace.get_current_span().get_span_context()
        logger.info(json.dumps({"service": "notifications", "correlation_id": request_id,
                               "trace_id": format(current.trace_id, "032x") if current.is_valid else None,
                               "method": request.method, "path": request.url.path,
                               "status": response.status_code,
                               "duration_ms": round((time.monotonic() - start) * 1000, 2)}))
        return response

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/ready")
    def ready():
        with sessions() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.get("/api/notifications")
    def inbox(principal=Depends(authenticated)):
        with sessions() as session:
            rows = session.scalars(select(Notification).where(
                Notification.recipient_role == principal.role,
                Notification.recipient_id == principal.user_id,
            ).order_by(Notification.id.desc())).all()
            return [public(row) for row in rows]

    @app.post("/api/notifications/{notification_id}/read")
    def mark_read(notification_id: int, request: Request, principal=Depends(authenticated)):
        return save_read(sessions, notification_id, principal, request.headers.get("idempotency-key"))

    if provider:
        FastAPIInstrumentor.instrument_app(app, excluded_urls="/health,/ready,/metrics")
    return app
