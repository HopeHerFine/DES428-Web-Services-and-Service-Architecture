"""Offline, all-or-nothing initial history import into an unused Payments DB.

The source snapshot must be taken after stopping all legacy writers. This module
never connects to SQLite and never emits historical events or changes Booking.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from .db import Base, Entry, HistoryBatch, Intent, Outbox, Receipt, WalletOpening, database
from .domain import Snapshot, fingerprint

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OldOrder(Snapshot):
    status: Literal["awaiting", "confirmed", "started", "completed", "cancelled", "rescheduled"]
    payment_status: Literal["unpaid", "paid", "refunded"]


class OldIntent(Strict):
    id: int = Field(gt=0)
    order_id: int = Field(gt=0)
    amount_cents: int = Field(gt=0, le=1000000000000)
    gateway_ref: str = Field(min_length=1, max_length=256)
    status: Literal["requires_payment", "succeeded", "failed"]
    created_at: str


class OldEntry(Strict):
    id: int = Field(gt=0, le=2147483647)
    order_id: int = Field(gt=0)
    customer_id: int = Field(gt=0)
    provider_id: int = Field(gt=0)
    kind: Literal["charge", "payout_credit", "commission_owed", "refund"]
    amount_cents: int = Field(ge=0, le=1000000000000)
    method: Literal["gateway", "cod"]
    gateway_ref: str | None
    status: Literal["pending", "succeeded", "failed", "refunded"]
    created_at: str


class OldWallet(Strict):
    provider_id: int = Field(gt=0)
    balance_cents: int = Field(ge=-1000000000000, le=1000000000000)
    commission_owed_cents: int = Field(ge=-1000000000000, le=1000000000000)


class History(Strict):
    version: Literal[1]
    source: str = Field(min_length=1, max_length=128)
    orders: list[OldOrder]
    intents: list[OldIntent]
    transactions: list[OldEntry]
    wallets: list[OldWallet]


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def indexed(rows, field):
    result = {getattr(row, field): row for row in rows}
    if len(result) != len(rows):
        raise ValueError("Duplicate legacy identifiers")
    return result


def validate(history):
    orders = indexed(history.orders, "order_id")
    intents = indexed(history.intents, "order_id")
    indexed(history.intents, "id")
    indexed(history.intents, "gateway_ref")
    indexed(history.transactions, "id")
    wallets = indexed(history.wallets, "provider_id")
    for item in history.intents:
        order = orders.get(item.order_id)
        if order is None or order.method != "gateway" or order.amount_cents != item.amount_cents:
            raise ValueError("Legacy payment intent does not match its booking")
        timestamp(item.created_at)
    seen = set()
    for row in history.transactions:
        order = orders.get(row.order_id)
        if order is None or row.customer_id != order.customer_id or row.provider_id != order.provider_id or row.method != order.method:
            raise ValueError("Legacy transaction ownership does not match booking")
        if row.provider_id not in wallets:
            raise ValueError("Legacy transaction has no authoritative provider wallet")
        pair = (row.order_id, row.kind)
        if pair in seen:
            raise ValueError("Multiple legacy effects for the same booking/kind require manual reconciliation")
        seen.add(pair)
        expected = {"charge":order.amount_cents, "refund":order.amount_cents,
            "payout_credit":order.amount_cents-order.commission_cents,
            "commission_owed":order.commission_cents}[row.kind]
        if row.amount_cents != expected:
            raise ValueError("Legacy transaction amount does not match booking snapshot")
        if (row.kind == "commission_owed") != (row.method == "cod"):
            raise ValueError("Legacy ledger kind does not match payment method")
        timestamp(row.created_at)
    for order in history.orders:
        intent = intents.get(order.order_id)
        if (order.method == "gateway") != (intent is not None):
            raise ValueError("Legacy booking/payment intent relationship is incomplete")
        if order.payment_status in {"paid", "refunded"} and (intent is None or intent.status != "succeeded"):
            raise ValueError("Legacy settlement status is inconsistent")
        if intent is not None and intent.status == "succeeded" and order.payment_status == "unpaid":
            raise ValueError("Legacy succeeded intent has an unpaid booking")
    return intents


def import_history(sessions, document):
    history = History.model_validate(document)
    intents = validate(history)
    canonical = history.model_dump()
    digest = fingerprint(canonical)
    source_hash = hashlib.sha256(history.source.encode()).hexdigest()

    def replay(batch):
        if batch.source_hash != source_hash or batch.snapshot_hash != digest:
            raise ValueError("A different history snapshot was already imported; no rows were changed")
        return json.loads(batch.report_json) | {"already_imported": True}

    try:
        with sessions.begin() as session:
            if session.bind.dialect.name == "postgresql":
                # Block API/consumer writes during the empty-target check and import.
                session.execute(text("LOCK TABLE payment_intents, transactions, processed_events, outbox, wallet_openings, history_imports IN EXCLUSIVE MODE"))
            old = session.get(HistoryBatch, "initial")
            if old is not None:
                return replay(old)
            for model in (Intent, Entry, Receipt, Outbox, WalletOpening):
                if session.scalar(select(func.count()).select_from(model)):
                    raise ValueError("History import requires an unused Payments database")
            for order in history.orders:
                data = order.model_dump(exclude={"status", "payment_status"})
                status = "requires_payment"
                if order.payment_status == "refunded":
                    status = "refunded"
                elif order.payment_status == "paid":
                    status = "succeeded"
                elif order.status == "cancelled":
                    status = "cancelled"
                elif order.order_id in intents:
                    status = intents[order.order_id].status
                session.add(Intent(**data, status=status, completed=order.status=="completed", cancelled=order.status=="cancelled"))
            for row in history.transactions:
                data = row.model_dump(exclude={"gateway_ref", "created_at"})
                session.add(Entry(**data, created_at=timestamp(row.created_at)))
            for wallet in history.wallets:
                entries = [row for row in history.transactions if row.provider_id == wallet.provider_id and row.status == "succeeded"]
                earned = sum(row.amount_cents for row in entries if row.kind == "payout_credit")
                owed = sum(row.amount_cents for row in entries if row.kind == "commission_owed")
                session.add(WalletOpening(provider_id=wallet.provider_id,
                    balance_cents=wallet.balance_cents-earned, commission_cents=wallet.commission_owed_cents-owed))
            session.flush()
            # Preserve transaction IDs and allow future PostgreSQL inserts above them.
            if history.transactions and session.bind.dialect.name == "postgresql":
                session.execute(text("SELECT setval(pg_get_serial_sequence('transactions','id'), :last_id, true)"),
                    {"last_id":max(row.id for row in history.transactions)})
            # Reconcile in this transaction so any mismatch rolls back every row.
            for old_wallet in history.wallets:
                opening = session.get(WalletOpening, old_wallet.provider_id)
                rows = session.scalars(select(Entry).where(Entry.provider_id==old_wallet.provider_id, Entry.status=="succeeded")).all()
                balance = opening.balance_cents + sum(row.amount_cents for row in rows if row.kind=="payout_credit")
                owed = opening.commission_cents + sum(row.amount_cents for row in rows if row.kind=="commission_owed")
                if (balance, owed) != (old_wallet.balance_cents, old_wallet.commission_owed_cents):
                    raise ValueError("Imported wallet reconciliation failed")
            report = {"result":"PASS", "probe":"payments-history", "snapshot_sha256":digest,
                "orders":len(history.orders), "transactions":len(history.transactions),
                "wallets":len(history.wallets), "wallets_reconciled":True,
                "historical_events_emitted":0, "already_imported":False}
            session.add(HistoryBatch(id="initial",source_hash=source_hash,snapshot_hash=digest,
                archive_json=json.dumps(canonical),report_json=json.dumps(report)))
            session.flush()
            return report
    except IntegrityError:
        with sessions() as session:
            batch=session.get(HistoryBatch,"initial")
            if batch is not None:
                return replay(batch)
        raise


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--file",required=True)
    parser.add_argument("--report")
    parser.add_argument("--confirm-offline",action="store_true")
    args=parser.parse_args()
    if not args.confirm_offline:
        parser.error("Stop all source and target writers first, then pass --confirm-offline")
    engine,sessions=database(os.environ["DATABASE_URL"])
    try:
        Base.metadata.create_all(engine)
        result=import_history(sessions,json.loads(Path(args.file).read_text(encoding="utf-8-sig")))
        if args.report:
            Path(args.report).write_text(json.dumps(result),encoding="utf-8")
        print(json.dumps(result))
    finally:
        engine.dispose()


if __name__=="__main__":
    main()
