import amqp from "amqplib";
import { config } from "../config.js";
import { logger } from "../logger.js";
import { publishPending } from "../db/broker-outbox.js";
import { context, propagation, trace, SpanKind, SpanStatusCode } from "@opentelemetry/api";

const STATE = Symbol.for("homeservice.broker.publisher");
const EXCHANGE = "homeservice.events";
const TYPES = ["review.created", "booking.status_changed", "booking.completed", "bid.accepted", "payment.succeeded", "provider.approved"];

// Declaring the durable queue before publishing prevents first-boot message loss
// if the notification worker has not connected yet.
async function connect(state) {
  const connection = await amqp.connect(config.rabbitmqUrl, { timeout: 5000 });
  state.connection = connection;
  connection.on("error", () => {}); // reconnect on the next tick; never log credentials
  connection.on("close", () => { state.channel = null; });
  const channel = await connection.createConfirmChannel();
  channel.on("error", () => {});
  channel.on("close", () => { state.channel = null; });
  await channel.assertExchange(EXCHANGE, "topic", { durable: true });
  await channel.assertQueue("notifications.dead", { durable: true });
  await channel.assertQueue("notifications.events", { durable: true, arguments: {
    "x-dead-letter-exchange": "", "x-dead-letter-routing-key": "notifications.dead",
  } });
  for (const type of TYPES) await channel.bindQueue("notifications.events", EXCHANGE, type);
  state.channel = channel;
}

export function startPublisher() {
  if (globalThis[STATE]) return;
  if (!config.rabbitmqUrl) throw new Error("RABBITMQ_URL required for external notifications");
  const state = { busy: false, connection: null, channel: null };
  globalThis[STATE] = state;
  const tick = async () => {
    if (state.busy) return;
    state.busy = true;
    try {
      if (!state.channel) await connect(state);
      const channel = state.channel;
      const count = await publishPending((event) => trace.getTracer("homeservice").startActiveSpan(
        `publish ${event.type}`, { kind: SpanKind.PRODUCER },
        propagation.extract(context.active(), event.trace_context || {}), async span => {
        try {
          const headers = {};
          propagation.inject(context.active(), headers);
          await new Promise((resolve, reject) => {
        // On confirm timeout close the transport. The row remains pending; if the
        // broker already accepted it, redelivery uses the same event ID.
        const timer = setTimeout(() => {
          state.channel = null;
          state.connection?.close().catch(() => {});
          reject(new Error("broker confirm timed out"));
        }, 10000);
        timer.unref();
        try {
          channel.publish(EXCHANGE, event.type, Buffer.from(JSON.stringify(event)), {
            persistent: true, contentType: "application/json", messageId: event.id,
            headers,
          }, (error) => {
            clearTimeout(timer);
            if (error) reject(error); else resolve();
          });
        } catch (error) { clearTimeout(timer); reject(error); }
          });
        } catch (error) { span.setStatus({ code: SpanStatusCode.ERROR }); throw error; }
        finally { span.end(); }
      }));
      if (count) logger.info({ count }, "outbox messages confirmed by broker");
    } catch {
      state.channel = null;
      if (state.connection) {
        await state.connection.close().catch(() => {});
        state.connection = null;
      }
      logger.warn("broker unavailable; outbox retained for retry");
    } finally { state.busy = false; }
  };
  state.timer = setInterval(tick, 2000);
  state.timer.unref();
  void tick();
}
