import { randomUUID } from "node:crypto";
import { getDb } from "./index.js";
import { context, propagation } from "@opentelemetry/api";

export const BROKER_SCHEMA = `
CREATE TABLE IF NOT EXISTS broker_outbox (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  trace_headers_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  published_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_broker_pending ON broker_outbox(sequence) WHERE published_at IS NULL;
`;

export function enqueue(type, payload) {
  if (!getDb().inTransaction) throw new Error("outbox writes require a domain transaction");
  const id = randomUUID();
  const carrier = {};
  propagation.inject(context.active(), carrier);
  getDb().prepare("INSERT INTO broker_outbox(event_id,type,payload_json,trace_headers_json) VALUES(?,?,?,?)")
    .run(id, type, JSON.stringify(payload), JSON.stringify(carrier));
  return id;
}

export function pending(limit = 100) {
  return getDb().prepare("SELECT * FROM broker_outbox WHERE published_at IS NULL ORDER BY sequence LIMIT ?")
    .all(limit);
}

export function markPublished(id) {
  getDb().prepare("UPDATE broker_outbox SET published_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE event_id=? AND published_at IS NULL")
    .run(id);
}

// Exported separately from the network transport so transaction/failure semantics
// can be tested without substituting the database with a mock.
export async function publishPending(sendConfirmed) {
  let count = 0;
  for (const row of pending()) {
    await sendConfirmed({ id: row.event_id, type: row.type, payload: JSON.parse(row.payload_json),
      trace_context: JSON.parse(row.trace_headers_json || "{}") });
    markPublished(row.event_id);
    count += 1;
  }
  return count;
}
