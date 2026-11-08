import { test } from "node:test";
import assert from "node:assert/strict";
import { NodeSDK } from "@opentelemetry/sdk-node";
import { InMemorySpanExporter, SimpleSpanProcessor } from "@opentelemetry/sdk-trace-base";
import { trace, propagation, context } from "@opentelemetry/api";
import { freshBoot, getDb } from "../test-helpers/boot.js";
import { enqueue, publishPending } from "../lib/db/broker-outbox.js";

test("transactional outbox preserves original parent trace across a failed delivery", async () => {
  const exporter = new InMemorySpanExporter();
  const sdk = new NodeSDK({ spanProcessor: new SimpleSpanProcessor(exporter) });
  sdk.start();
  try {
    freshBoot();
    let parentId;
    await trace.getTracer("test").startActiveSpan("domain update", async span => {
      parentId = span.spanContext().traceId;
      getDb().transaction(() => enqueue("provider.approved", {provider_id: 3}))();
      span.end();
    });
    let first;
    await assert.rejects(publishPending(async event => {
      first = event.trace_context.traceparent;
      throw new Error("broker offline");
    }), /broker offline/);
    await publishPending(async event => {
      assert.equal(event.trace_context.traceparent, first);
      const parent = propagation.extract(context.active(), event.trace_context);
      assert.equal(trace.getSpanContext(parent).traceId, parentId);
    });
    assert.match(first, /^00-[a-f0-9]{32}-[a-f0-9]{16}-01$/);
  } finally { await sdk.shutdown(); }
});
