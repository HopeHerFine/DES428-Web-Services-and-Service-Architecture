// Next.js boot hook. Runs once when the server process starts (dev and production alike). This is
// where the monolith gets its deterministic behaviour: a fresh, migrated, seeded database on every
// boot, and the outbox relay draining domain events in the background.
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { startTelemetry } = await import("./lib/observability/telemetry.js");
    await startTelemetry();
    const { bootstrapDb } = await import("./lib/db/bootstrap.js");
    bootstrapDb();
    const { startRelay } = await import("./lib/modules/notifications/relay.js");
    startRelay();
    const { config } = await import("./lib/config.js");
    if (config.externalNotifications) {
      const { startPublisher } = await import("./lib/messaging/publisher.js");
      startPublisher();
    }
  }
}
