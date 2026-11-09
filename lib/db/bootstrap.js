// One call that gets a fresh, migrated, seeded database ready to serve. Used by instrumentation.js
// on real boot and by test-helpers/boot.js to stand up an isolated in-process app per test file.
import { getDb } from "./index.js";
import { migrate } from "./migrate.js";
import { seed } from "./seed.js";
import { logger } from "../logger.js";
import { config } from "../config.js";
import { BROKER_SCHEMA } from "./broker-outbox.js";
import { PAYMENT_PROJECTION_SCHEMA } from "../messaging/payment-consumer.js";
import { guardCutover, cutoverState } from "../modules/payments/cutover-state.js";

export function bootstrapDb() {
  const db = getDb();
  const exists = db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='customers'").get();
  if (exists) {
    const state=cutoverState(db);
    if (state && state.phase!=='rolled_back') guardCutover(db,config.externalPayments,config.paymentsCutoverProbe);
    const hasMode=db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='payments_runtime_mode'").get();
    if (hasMode && db.prepare("SELECT 1 FROM payments_runtime_mode WHERE mode='external'").get() &&
        (!config.externalPayments || !config.externalNotifications)) throw new Error('External Payments data must not be reset by legacy boot.');
  }
  // A restart must not erase domain state or undelivered outbox entries.
  // Tests and the inherited monolith mode retain their deterministic reset.
  if (!config.externalNotifications || !exists) {
    migrate(db);
    seed(db);
    logger.info("database migrated and seeded");
  }
  db.exec(BROKER_SCHEMA);
  guardCutover(db,config.externalPayments,config.paymentsCutoverProbe);
  db.exec("CREATE TABLE IF NOT EXISTS payments_runtime_mode (mode TEXT PRIMARY KEY)");
  const externalMode = db.prepare("SELECT 1 FROM payments_runtime_mode WHERE mode='external'").get();
  if (externalMode && !config.externalPayments) {
    throw new Error("This project uses external Payments. Start it with compose.payments.yml to avoid stale legacy wallet data.");
  }
  if (config.externalPayments && !externalMode) {
    const legacy = db.prepare(`SELECT
      (SELECT COUNT(*) FROM payment_intents) + (SELECT COUNT(*) FROM transactions) +
      (SELECT COUNT(*) FROM provider_wallets WHERE balance_cents!=0 OR commission_owed_cents!=0) AS n`).get();
    if (legacy.n > 0) throw new Error("Legacy payment history needs migration. Use a fresh isolated project for the Payments pilot.");
    db.prepare("INSERT INTO payments_runtime_mode(mode) VALUES('external')").run();
  }
  db.exec(PAYMENT_PROJECTION_SCHEMA);
  if (!db.prepare("PRAGMA table_info(broker_outbox)").all().some(column => column.name === "trace_headers_json")) {
    db.exec("ALTER TABLE broker_outbox ADD COLUMN trace_headers_json TEXT NOT NULL DEFAULT '{}'");
  }
  db.exec(`CREATE TABLE IF NOT EXISTS identity_provisioning (
    role TEXT NOT NULL, user_id INTEGER NOT NULL, email TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','active')),
    PRIMARY KEY(role,user_id), UNIQUE(email)
  )`);
  return db;
}
