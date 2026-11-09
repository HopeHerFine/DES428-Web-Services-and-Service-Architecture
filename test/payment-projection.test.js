import { test } from "node:test";
import assert from "node:assert/strict";
import { freshBoot, getDb } from "../test-helpers/boot.js";
import { placeBooking } from "../lib/modules/booking/service.js";
import { applyPaymentEvent } from "../lib/messaging/payment-consumer.js";
import { futureWeekday } from "../test-helpers/auth.js";

freshBoot();

test("Booking payment projection deduplicates, rejects mismatches and never reverses a refund", () => {
  const placed = placeBooking(1, { provider_id: 1, service_date: futureWeekday(3),
    starting_time: "09:00", items: [{ service_id: 2, quantity: 1 }], payment_method: "gateway" }, "projection-test");
  const order = placed.body.order;
  const paid = { id: "payment-1", type: "payment.succeeded", payload: {
    order_id: order.id, customer_id: 1, provider_id: 1, amount_cents: order.total_cents,
  } };
  assert.equal(applyPaymentEvent(paid), true);
  assert.equal(applyPaymentEvent(paid), false);
  assert.throws(() => applyPaymentEvent({ ...paid, id: "bad", payload: { ...paid.payload, amount_cents: 1 } }), TypeError);
  assert.equal(applyPaymentEvent({ ...paid, id: "refund", type: "payment.refunded" }), true);
  assert.equal(applyPaymentEvent({ ...paid, id: "late-paid" }), true);
  assert.equal(getDb().prepare("SELECT payment_status FROM orders WHERE id=?").get(order.id).payment_status, "refunded");
  assert.equal(getDb().prepare("SELECT COUNT(*) AS n FROM payment_event_receipts").get().n, 3);
  getDb().prepare('INSERT INTO payments_legacy_orders(order_id,customer_id,provider_id,amount_cents,payment_status) VALUES(?,?,?,?,?)')
    .run(order.id,1,1,order.total_cents,'paid');
  const legacy={id:'old-financial-outbox',type:'payment.succeeded',payload:{order_id:order.id,provider_id:1,amount_cents:order.total_cents}};
  assert.equal(applyPaymentEvent(legacy),false);
  assert.equal(getDb().prepare('SELECT payment_status FROM orders WHERE id=?').get(order.id).payment_status,'refunded');
  assert.throws(()=>applyPaymentEvent({...legacy,id:'wrong-old-amount',payload:{...legacy.payload,amount_cents:1}}),TypeError);
});
