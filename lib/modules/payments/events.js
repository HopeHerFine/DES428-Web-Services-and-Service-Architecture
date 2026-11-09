import { config } from "../../config.js";
import { enqueue } from "../../db/broker-outbox.js";

// Booking supplies an immutable commercial snapshot; Payments never reads SQLite.
export function billingEvent(kind, order) {
  if (!config.externalPayments) return;
  enqueue(`billing.booking_${kind}`, {
    order_id: order.id, customer_id: order.customer_id, provider_id: order.provider_id,
    amount_cents: order.total_cents,
    commission_cents: Math.round(order.total_cents * order.commission_pct / 100),
    method: order.payment_method,
  });
}
