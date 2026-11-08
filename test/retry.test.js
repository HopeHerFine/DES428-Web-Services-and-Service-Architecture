import { test } from "node:test";
import assert from "node:assert/strict";
import { resilientFetch } from "../lib/http/retry.js";

test("retries use a stable write key, exponential backoff and jitter", async () => {
  const original = globalThis.fetch;
  const keys = [], delays = [];
  let calls = 0;
  globalThis.fetch = async (url, options) => {
    keys.push(options.headers.get("Idempotency-Key"));
    return new Response("{}", { status: ++calls < 3 ? 503 : 200 });
  };
  try {
    const response = await resilientFetch("http://test/inbox", { method: "POST" }, {
      baseDelayMs: 10, random: () => 0.5, sleep: async ms => delays.push(ms),
    });
    assert.equal(response.status, 200);
    assert.equal(new Set(keys).size, 1);
    assert.ok(keys[0]);
    assert.deepEqual(delays, [15, 25]);
  } finally { globalThis.fetch = original; }
});

test("network timeout is retried, authentication failures are not", async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async (url, options) => {
    if (++calls === 1) return new Promise((resolve, reject) => options.signal.addEventListener("abort", () => reject(new Error("timeout"))));
    return new Response("{}", { status: 401 });
  };
  try {
    const result = await resilientFetch("http://test/inbox", {}, { timeoutMs: 5, sleep: async () => {} });
    assert.equal(result.status, 401);
    assert.equal(calls, 2);
  } finally { globalThis.fetch = original; }
});
