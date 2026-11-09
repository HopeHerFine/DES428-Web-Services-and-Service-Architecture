import amqp from "amqplib";
import { config } from "../config.js";
import { getDb } from "../db/index.js";
import { logger } from "../logger.js";

const STATE = Symbol.for("homeservice.payments.consumer");

export const PAYMENT_PROJECTION_SCHEMA = `CREATE TABLE IF NOT EXISTS payment_event_receipts (
  event_id TEXT PRIMARY KEY, type TEXT NOT NULL, order_id INTEGER NOT NULL
);`;

// Booking owns payment_status. A refund is terminal, even if messages arrive out
// of order; acknowledgement follows this local transaction, never precedes it.
export function applyPaymentEvent(event) {
  if (!event || typeof event.id !== "string" || !event.id || event.id.length > 128 ||
      !["payment.succeeded", "payment.refunded"].includes(event.type) ||
      !Number.isSafeInteger(event.payload?.order_id) || event.payload.order_id <= 0) {
    throw new TypeError("Invalid payment event");
  }
  const db = getDb();
  return db.transaction(() => {
    const old = db.prepare("SELECT * FROM payment_event_receipts WHERE event_id=?").get(event.id);
    if (old) {
      if (old.type !== event.type || old.order_id !== event.payload.order_id) throw new TypeError("Payment event ID conflict");
      return false;
    }
    const order = db.prepare("SELECT * FROM orders WHERE id=?").get(event.payload.order_id);
    if (!order) throw new TypeError("Unknown booking in payment event");
    // Legacy paid events already represented in the frozen migration snapshot
    // may still be pending in the old outbox. Acknowledge them without applying
    // a second financial transition; Notifications still consumes its own copy.
    if (event.type==='payment.succeeded' && event.payload.customer_id===undefined) {
      const exists=db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='payments_legacy_orders'").get();
      const covered=exists && db.prepare('SELECT * FROM payments_legacy_orders WHERE order_id=?').get(order.id);
      if (covered && ['paid','refunded'].includes(covered.payment_status) &&
          covered.provider_id===event.payload.provider_id && covered.amount_cents===event.payload.amount_cents) {
        db.prepare('INSERT INTO payment_event_receipts(event_id,type,order_id) VALUES(?,?,?)').run(event.id,event.type,order.id);
        return false;
      }
    }
    if (order.customer_id !== event.payload.customer_id || order.provider_id !== event.payload.provider_id ||
        order.total_cents !== event.payload.amount_cents || order.payment_method !== "gateway") {
      throw new TypeError("Payment event does not match booking");
    }
    db.prepare("INSERT INTO payment_event_receipts(event_id,type,order_id) VALUES(?,?,?)")
      .run(event.id, event.type, order.id);
    if (event.type === "payment.refunded") {
      db.prepare("UPDATE orders SET payment_status='refunded' WHERE id=?").run(order.id);
    } else {
      db.prepare("UPDATE orders SET payment_status='paid' WHERE id=? AND payment_status!='refunded'").run(order.id);
    }
    return true;
  }).immediate();
}

export function startPaymentConsumer() {
  if (globalThis[STATE]) return;
  const state = { connection: null, channel: null, busy: false };
  globalThis[STATE] = state;
  const connect = async () => {
    if (state.channel || state.busy) return;
    state.busy = true;
    try {
      const connection = await amqp.connect(config.rabbitmqUrl, { timeout: 5000 });
      state.connection = connection;
      connection.on("error", () => {});
      connection.on("close", () => { state.channel = null; });
      const channel = await connection.createChannel();
      channel.on("error", () => {});
      channel.on("close", () => { state.channel = null; });
      await channel.assertExchange("homeservice.events", "topic", { durable: true });
      await channel.assertQueue("booking.payments.dead", { durable: true });
      await channel.assertQueue("booking.payments", { durable: true, arguments: {
        "x-dead-letter-exchange": "", "x-dead-letter-routing-key": "booking.payments.dead",
      } });
      for (const type of ["payment.succeeded", "payment.refunded"]) {
        await channel.bindQueue("booking.payments", "homeservice.events", type);
      }
      await channel.prefetch(1);
      await channel.consume("booking.payments", message => {
        if (!message) return;
        try {
          applyPaymentEvent(JSON.parse(message.content.toString()));
          channel.ack(message);
        } catch (error) {
          if (error instanceof SyntaxError || error instanceof TypeError) channel.nack(message, false, false);
          else void connection.close().catch(() => {}); // requeue after reconnect, with backoff
        }
      });
      state.channel = channel;
    } catch {
      state.channel = null;
      if (state.connection) await state.connection.close().catch(() => {});
      logger.warn("Payment event consumer reconnecting; broker queue retained");
    } finally { state.busy = false; }
  };
  state.timer = setInterval(connect, 3000);
  state.timer.unref();
  void connect();
}
