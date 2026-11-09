// Next.js boot hook. Runs once when the server process starts (dev and production alike). This is
// where the monolith gets its deterministic behaviour: a fresh, migrated, seeded database on every
// boot, and the outbox relay draining domain events in the background.
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { startTelemetry } = await import("./lib/observability/telemetry.js");
    await startTelemetry();
    const { bootstrapDb } = await import("./lib/db/bootstrap.js");
    bootstrapDb();
    const { verifyCutoverTarget } = await import("./lib/modules/payments/cutover-state.js");
    const { getDb } = await import("./lib/db/index.js");
    const { config } = await import("./lib/config.js");
    if (config.externalPayments) await verifyCutoverTarget(getDb(),config.paymentsUrl);
    const { startRelay } = await import("./lib/modules/notifications/relay.js");
    startRelay();
    if (config.externalNotifications) {
      const { startPublisher } = await import("./lib/messaging/publisher.js");
      startPublisher();
    }
    if (config.externalPayments) {
      const { startPaymentConsumer } = await import("./lib/messaging/payment-consumer.js");
      startPaymentConsumer();
    }
  }
}
