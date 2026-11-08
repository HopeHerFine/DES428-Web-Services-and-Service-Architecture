// One call that gets a fresh, migrated, seeded database ready to serve. Used by instrumentation.js
// on real boot and by test-helpers/boot.js to stand up an isolated in-process app per test file.
import { getDb } from "./index.js";
import { migrate } from "./migrate.js";
import { seed } from "./seed.js";
import { logger } from "../logger.js";
import { config } from "../config.js";
import { BROKER_SCHEMA } from "./broker-outbox.js";

export function bootstrapDb() {
  const db = getDb();
  const exists = db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='customers'").get();
  // A restart must not erase domain state or undelivered outbox entries.
  // Tests and the inherited monolith mode retain their deterministic reset.
  if (!config.externalNotifications || !exists) {
    migrate(db);
    seed(db);
    logger.info("database migrated and seeded");
  }
  db.exec(BROKER_SCHEMA);
  return db;
}
