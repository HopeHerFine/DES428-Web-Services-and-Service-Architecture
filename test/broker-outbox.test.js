import { test } from "node:test";
import assert from "node:assert/strict";
import { freshBoot, getDb } from "../test-helpers/boot.js";
import { enqueue, pending, publishPending } from "../lib/db/broker-outbox.js";

test("broker outbox commits and rolls back with domain state; failed send retains stable ID", async () => {
  freshBoot();
  const db = getDb();
  assert.throws(() => enqueue("provider.approved", { provider_id: 1 }), /domain transaction/);
  assert.throws(() => db.transaction(() => {
    db.prepare("UPDATE provider_profiles SET is_approved=1 WHERE provider_id=3").run();
    enqueue("provider.approved", { provider_id: 3 });
    throw new Error("domain rollback");
  })(), /domain rollback/);
  assert.equal(pending().length, 0);
  assert.equal(db.prepare("SELECT is_approved FROM provider_profiles WHERE provider_id=3").get().is_approved, 0);
  const id = db.transaction(() => enqueue("provider.approved", { provider_id: 3 }))();
  await assert.rejects(publishPending(async () => { throw new Error("confirm lost"); }), /confirm lost/);
  assert.equal(pending()[0].event_id, id);
  let sent;
  assert.equal(await publishPending(async (event) => { sent = event; }), 1);
  assert.equal(sent.id, id);
  assert.deepEqual(sent.payload, { provider_id: 3 });
  assert.equal(pending().length, 0);
  assert.equal(await publishPending(async () => assert.fail("must not resend confirmed row")), 0);
});
