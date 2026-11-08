import { test } from "node:test";
import assert from "node:assert/strict";

process.env.EXTERNAL_NOTIFICATIONS = "true";
process.env.NODE_ENV = "test";
process.env.DB_PATH = ":memory:";
const { bootstrapDb } = await import("../lib/db/bootstrap.js");
const { getDb } = await import("../lib/db/index.js");
const { approveProvider } = await import("../lib/modules/providers/service.js");
const { runRelayOnce } = await import("../lib/modules/notifications/relay.js");
const { pending } = await import("../lib/db/broker-outbox.js");
const { insertEvent } = await import("../lib/db/events.js");

test("external mode sends approval via outbox, preserves pending rows on reboot, keeps ratings local", () => {
  bootstrapDb();
  const db = getDb();
  const provider = db.prepare("SELECT id FROM providers WHERE email='glow@example.com'").get();
  approveProvider(provider.id);
  assert.equal(pending()[0].type, "provider.approved");
  assert.equal(db.prepare("SELECT count(*) n FROM notifications").get().n, 0);
  const eventId = pending()[0].event_id;
  bootstrapDb();
  assert.equal(pending()[0].event_id, eventId, "reboot must not erase unconfirmed events");
  assert.equal(db.prepare("SELECT is_approved FROM provider_profiles WHERE provider_id=?").get(provider.id).is_approved, 1);
  // Verify rollback removes both local domain-event log and broker outbox entry.
  const before = pending().length;
  assert.throws(() => db.transaction(() => {
    insertEvent("review.created", "review", 1, { service_id: 2, provider_id: 1 });
    throw new Error("rollback");
  })(), /rollback/);
  assert.equal(pending().length, before);
  // Exercise rating recomputation with the real repository on an empty review set.
  db.prepare("UPDATE services SET rating_count=99,rating_avg=5 WHERE id=2").run();
  db.prepare("UPDATE provider_profiles SET rating_count=99,rating_avg=5 WHERE provider_id=1").run();
  insertEvent("review.created", "review", 1, { service_id: 2, provider_id: 1, rating: 5, order_id: 8001 });
  runRelayOnce();
  assert.equal(db.prepare("SELECT rating_count FROM services WHERE id=2").get().rating_count, 0);
  assert.equal(db.prepare("SELECT rating_count FROM provider_profiles WHERE provider_id=1").get().rating_count, 0);
  assert.equal(db.prepare("SELECT count(*) n FROM notifications").get().n, 0);
});
