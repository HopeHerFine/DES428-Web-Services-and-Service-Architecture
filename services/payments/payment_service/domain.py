"""Atomic event receipts, payment transitions, ledger entries and outbound events."""
import hashlib
import json
from typing import Literal
from uuid import uuid4
from fastapi import HTTPException
from opentelemetry import propagate
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .db import Intent, Entry, Receipt, Outbox, WalletOpening

KINDS = ("billing.booking_created", "billing.booking_completed", "billing.booking_cancelled")


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    order_id: int = Field(gt=0, le=2147483647)
    customer_id: int = Field(gt=0, le=2147483647)
    provider_id: int = Field(gt=0, le=2147483647)
    amount_cents: int = Field(gt=0, le=1000000000000)
    commission_cents: int = Field(ge=0, le=1000000000000)
    method: Literal["gateway", "cod"]

    @model_validator(mode="after")
    def commission_within_total(self):
        if self.commission_cents > self.amount_cents:
            raise ValueError("commission exceeds total")
        return self


class Event(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    type: Literal["billing.booking_created", "billing.booking_completed", "billing.booking_cancelled"]
    payload: Snapshot


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def emit(session, kind, order):
    headers = {}
    propagate.inject(headers)
    session.add(Outbox(id=str(uuid4()), type=kind, payload=json.dumps({
        "order_id": order.order_id, "customer_id": order.customer_id,
        "provider_id": order.provider_id, "amount_cents": order.amount_cents,
    }), trace_headers=json.dumps(headers)))


def entry(session, order, kind, amount):
    session.add(Entry(order_id=order.order_id, customer_id=order.customer_id,
        provider_id=order.provider_id, kind=kind, amount_cents=amount, method=order.method,
        status="refunded" if kind == "refund" else "succeeded"))


def completion(session, order):
    # The order row is locked by both the consumer and the HTTP settlement path.
    if not order.completed or order.cancelled:
        return
    kind = "payout_credit" if order.method == "gateway" else "commission_owed"
    if order.method == "gateway" and order.status != "succeeded":
        return
    exists = session.scalar(select(Entry.id).where(Entry.order_id == order.order_id, Entry.kind == kind))
    if exists is None:
        amount = order.amount_cents - order.commission_cents if kind == "payout_credit" else order.commission_cents
        entry(session, order, kind, amount)


def consume(sessions, event):
    payload = event.payload.model_dump()
    digest = fingerprint({"type": event.type, "payload": payload})
    key = "event:" + event.id
    try:
        with sessions.begin() as session:
            session.add(Receipt(id=key, fingerprint=digest))
            session.flush()
            order = session.scalar(select(Intent).where(Intent.order_id == event.payload.order_id).with_for_update())
            if order is None:
                order = Intent(**payload)
                session.add(order)
                session.flush()
            elif any(getattr(order, name) != value for name, value in payload.items()):
                raise ValueError("Conflicting immutable booking snapshot")
            if event.type == "billing.booking_cancelled":
                if order.completed:
                    raise ValueError("Cannot cancel a completed booking")
                order.cancelled = True
                if order.status == "succeeded":
                    entry(session, order, "refund", order.amount_cents)
                    order.status = "refunded"
                    emit(session, "payment.refunded", order)
                elif order.status == "requires_payment":
                    order.status = "cancelled"
            elif event.type == "billing.booking_completed":
                if not order.cancelled:
                    order.completed = True
                    completion(session, order)
        return True
    except IntegrityError:
        with sessions() as session:
            old = session.get(Receipt, key)
            if old is not None:
                if old.fingerprint != digest:
                    raise ValueError("Event ID reused with different payload") from None
                return False
        # A concurrent first event for the same order won the insert. Retrying
        # delivery serializes on that newly created row, without losing a receipt.
        raise


def settle(sessions, order_id, customer_id, key):
    if not key or len(key) > 128:
        raise HTTPException(400, "Idempotency-Key is required (maximum 128 characters)")
    receipt_key = f"settle:{customer_id}:{key}"
    digest = fingerprint({"order_id": order_id})
    try:
        with sessions.begin() as session:
            session.add(Receipt(id=receipt_key, fingerprint=digest))
            session.flush()
            order = session.scalar(select(Intent).where(Intent.order_id == order_id).with_for_update())
            if order is None:
                raise HTTPException(409, "Payment intent is not ready; retry after event delivery")
            if order.customer_id != customer_id:
                raise HTTPException(403, "You do not own this payment")
            if order.method != "gateway" or order.cancelled or order.status not in {"requires_payment", "succeeded"}:
                raise HTTPException(409, "This booking cannot be paid")
            if order.status == "requires_payment":
                order.status = "succeeded"
                entry(session, order, "charge", order.amount_cents)
                emit(session, "payment.succeeded", order)
                completion(session, order)
            result = {"ok": True, "order_id": order_id, "status": order.status}
            session.get(Receipt, receipt_key).response = json.dumps(result)
            return result
    except IntegrityError:
        with sessions() as session:
            old = session.get(Receipt, receipt_key)
            if old is None:
                raise
            if old.fingerprint != digest:
                raise HTTPException(409, "Idempotency-Key was used for a different order") from None
            return json.loads(old.response)


def wallet(sessions, provider_id):
    with sessions() as session:
        rows = session.scalars(select(Entry).where(Entry.provider_id == provider_id).order_by(Entry.id.desc())).all()
        opening = session.get(WalletOpening, provider_id)
        return {"provider_id": provider_id,
            "balance_cents": (opening.balance_cents if opening else 0) + sum(r.amount_cents for r in rows if r.kind == "payout_credit" and r.status == "succeeded"),
            "commission_owed_cents": (opening.commission_cents if opening else 0) + sum(r.amount_cents for r in rows if r.kind == "commission_owed" and r.status == "succeeded"),
            "transactions": [public_entry(row) for row in rows]}


def public_entry(row):
    return {name: getattr(row, name) for name in (
        "id", "order_id", "kind", "amount_cents", "method", "status") } | {"created_at": row.created_at.isoformat()}
