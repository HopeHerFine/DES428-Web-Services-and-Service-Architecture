import json

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .db import Notification, WriteReceipt, utcnow


def public(row):
    return {key: getattr(row, key) for key in
            ("id", "type", "title", "body", "order_id", "read_at", "created_at")}


def mark_read(sessions, notification_id, principal, key=None):
    if key is not None and (not key.strip() or len(key) > 128):
        raise HTTPException(400, "invalid Idempotency-Key")
    scope = f"{principal.role}:{principal.user_id}:{key}" if key else None
    try:
        with sessions.begin() as session:
            # Serialize writes to this notification in PostgreSQL. Ownership is
            # checked before looking up any receipt, so a replay cannot bypass it.
            row = session.scalar(select(Notification).where(Notification.id == notification_id).with_for_update())
            if row is None:
                raise HTTPException(404, "notification not found")
            if (row.recipient_role, row.recipient_id) != (principal.role, principal.user_id):
                raise HTTPException(403, "not your notification")
            receipt = session.get(WriteReceipt, scope) if scope else None
            if receipt:
                if receipt.notification_id != notification_id:
                    raise HTTPException(409, "Idempotency-Key already used for another notification")
                return json.loads(receipt.response_json)
            session.execute(update(Notification).where(
                Notification.id == notification_id, Notification.read_at.is_(None),
            ).values(read_at=utcnow()))
            session.refresh(row)
            response = jsonable_encoder(public(row))
            if scope:
                session.add(WriteReceipt(key=scope, notification_id=notification_id,
                                         response_json=json.dumps(response)))
            return response
    except IntegrityError:
        # Concurrent use of one key against different rows must not commit twice.
        with sessions() as session:
            receipt = session.get(WriteReceipt, scope) if scope else None
            if receipt and receipt.notification_id == notification_id:
                return json.loads(receipt.response_json)
            if receipt:
                raise HTTPException(409, "Idempotency-Key already used for another notification")
        raise
