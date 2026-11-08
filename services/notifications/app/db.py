from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ProcessedEvent(Base):
    __tablename__ = "processed_events"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("event_id", "recipient_role", "recipient_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128))
    recipient_role: Mapped[str] = mapped_column(String(20), index=True)
    recipient_id: Mapped[str] = mapped_column(String(128), index=True)
    type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def database(url):
    engine = create_engine(url, pool_pre_ping=True)
    return engine, sessionmaker(engine, expire_on_commit=False)
