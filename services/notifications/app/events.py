from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from .db import Notification, ProcessedEvent


class DomainEvent(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    type: Literal["review.created", "booking.status_changed", "booking.completed", "bid.accepted", "payment.succeeded", "provider.approved"]
    payload: dict[str, Any]


def notifications_for(event):
    p = event.payload
    order_id = p.get("order_id")
    rows = []

    def add(role, user_id, kind, title, body, order=order_id):
        if user_id is None or role not in {"customer", "provider", "admin"}:
            raise ValueError("invalid recipient")
        rows.append(Notification(event_id=event.id, recipient_role=role,
                                 recipient_id=str(user_id), type=kind, title=title,
                                 body=body, order_id=order))

    if event.type == "provider.approved":
        add("provider", p["provider_id"], "provider_approved", "You're approved",
            "Your provider account has been approved. Your services are now visible to customers.")
    elif event.type == "review.created":
        add("provider", p["provider_id"], "new_review", "New review",
            f"You received a {p['rating']}-star review on booking #{order_id}.")
    elif event.type == "booking.status_changed":
        customer = p["actor_role"] == "provider"
        add("customer" if customer else "provider", p["customer_id"] if customer else p["provider_id"],
            "booking_status", f"Booking {p['to']}", f"Booking #{order_id} is now {p['to']}.")
    elif event.type == "booking.completed":
        add("customer", p["customer_id"], "rating_request", "How did it go?",
            f"Booking #{order_id} is complete — leave a review for your provider.")
    elif event.type == "bid.accepted":
        add("provider", p["winner_provider_id"], "bid_accepted", "Your bid was accepted",
            f"Your bid on job #{p['job_request_id']} was accepted — booking #{order_id} created.")
        for user_id in set(p.get("loser_provider_ids", [])):
            add("provider", user_id, "bid_rejected", "Bid not selected",
                f"Your bid on job #{p['job_request_id']} was not selected.", None)
    elif event.type == "payment.succeeded" and p.get("provider_id") is not None:
        add("provider", p["provider_id"], "payment_received", "Payment received",
            f"Payment of {p['amount_cents']} cents was received for booking #{order_id}.")
    return rows


def consume_event(sessions, event):
    # The receipt and every notification commit together. Concurrent redeliveries
    # contend on the receipt primary key, so only one transaction applies the event.
    rows = notifications_for(event)
    try:
        with sessions.begin() as session:
            session.add(ProcessedEvent(id=event.id))
            session.flush()
            session.add_all(rows)
        return True
    except IntegrityError:
        with sessions() as session:
            if session.get(ProcessedEvent, event.id) is not None:
                return False
        raise
