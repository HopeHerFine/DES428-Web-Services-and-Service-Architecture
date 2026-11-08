"""Payments owns this database. Order IDs are external references, never cross-DB FKs."""
from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Intent(Base):
    __tablename__ = "payment_intents"
    order_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    customer_id: Mapped[int] = mapped_column(Integer, index=True)
    provider_id: Mapped[int] = mapped_column(Integer, index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    commission_cents: Mapped[int] = mapped_column(BigInteger)
    method: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="requires_payment")
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)


class Entry(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("order_id", "kind"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    customer_id: Mapped[int] = mapped_column(Integer, index=True)
    provider_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(24))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    method: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="succeeded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Receipt(Base):
    __tablename__ = "processed_events"
    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    response: Mapped[str] = mapped_column(Text, default="{}")


class Outbox(Base):
    __tablename__ = "outbox"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    id: Mapped[str] = mapped_column(String(128), unique=True)
    type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text)
    trace_headers: Mapped[str] = mapped_column(Text, default="{}")
    published: Mapped[bool] = mapped_column(Boolean, default=False)


def database(url):
    engine = create_engine(url, pool_pre_ping=True)
    return engine, sessionmaker(engine, expire_on_commit=False)
