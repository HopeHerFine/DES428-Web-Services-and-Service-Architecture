import json
import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy import select, text, update

from .auth import authenticated, build_verifier
from .db import Base, Notification, database, utcnow
from .settings import Settings

logger = logging.getLogger("notifications")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.propagate = False


def public(row):
    return {key: getattr(row, key) for key in
            ("id", "type", "title", "body", "order_id", "read_at", "created_at")}


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
    app.state.verify_token = verifier or build_verifier(settings)

    @app.middleware("http")
    async def correlation(request: Request, call_next):
        request_id = request.headers.get("x-request-id", "")
        if not request_id or len(request_id) > 128 or not request_id.isprintable():
            request_id = str(uuid4())
        start = time.monotonic()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        logger.info(json.dumps({"service": "notifications", "correlation_id": request_id,
                               "method": request.method, "path": request.url.path,
                               "status": response.status_code,
                               "duration_ms": round((time.monotonic() - start) * 1000, 2)}))
        return response

    @app.get("/health")
    def health():
        return {"status": "ok"}

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
    def mark_read(notification_id: int, principal=Depends(authenticated)):
        with sessions.begin() as session:
            row = session.get(Notification, notification_id)
            if row is None:
                raise HTTPException(404, "notification not found")
            if (row.recipient_role, row.recipient_id) != (principal.role, principal.user_id):
                raise HTTPException(403, "not your notification")
            session.execute(update(Notification).where(
                Notification.id == notification_id, Notification.read_at.is_(None),
            ).values(read_at=utcnow()))
            session.refresh(row)
            return public(row)

    return app
