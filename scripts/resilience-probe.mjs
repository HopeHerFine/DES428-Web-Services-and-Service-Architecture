import { readFile, writeFile, rename, unlink } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import assert from 'node:assert/strict';
import { resilientFetch } from './retry.mjs';

const fixture = JSON.parse(await readFile('/probe-data/credentials.json', 'utf8'));
const file = '/faults/notifications.json';
const nativeFetch = globalThis.fetch;
let attempts;
async function switchFault(mode) {
  const temporary = `/faults/${randomUUID()}.tmp`;
  await writeFile(temporary, JSON.stringify({ mode, revision: randomUUID(), delay_seconds: 2.5,
    until: mode === 'unavailable' ? Date.now() / 1000 + 0.6 : 0 }));
  await rename(temporary, file);
}
globalThis.fetch = async (...args) => {
  attempts.total++;
  try {
    const response = await nativeFetch(...args);
    if (response.status === 503) attempts.unavailable++;
    return response;
  } catch (error) { attempts.networkFailures++; throw error; }
};
const headers = key => ({ Authorization: `Bearer ${fixture.token}`, 'Idempotency-Key': key,
  Origin: 'http://localhost:8080', Host: 'localhost:8080' });
const url = id => `http://gateway/api/notifications/${id}/read`;
const results = [];
try {
  for (const row of fixture.fixtures.filter(row => ['lost_reply', 'slow_calls', 'unavailable'].includes(row.mode))) {
    attempts = { total: 0, networkFailures: 0, unavailable: 0 };
    await switchFault(row.mode);
    const response = await resilientFetch(url(row.id), { method: 'POST', headers: headers(row.key) });
    assert.equal(response.status, 200, `${row.mode}: recovery failed`);
    const body = await response.json();
    assert.ok(body.read_at);
    assert.ok(attempts.total >= 2, `${row.mode}: fault did not trigger a retry`);
    if (row.mode === 'unavailable') assert.ok(attempts.unavailable >= 1);
    else assert.ok(attempts.networkFailures >= 1, `${row.mode}: no caller timeout was observed`);
    const measured = { ...attempts };
    await switchFault('none');
    const replay = await resilientFetch(url(row.id), { method: 'POST', headers: headers(row.key) });
    assert.deepEqual(await replay.json(), body, 'Retry/replay changed the committed result');
    results.push({ case: row.mode, final_status: 200, attempts: measured.total,
      timeouts: measured.networkFailures, temporary_503s: measured.unavailable, stable_result: true });
  }
  await switchFault('none');
  attempts = { total: 0, networkFailures: 0, unavailable: 0 };
  const row = fixture.fixtures.find(row => row.mode === 'concurrent');
  const replies = await Promise.all(Array.from({ length: 8 }, async () => {
    const response = await resilientFetch(url(row.id), { method: 'POST', headers: headers(row.key) });
    assert.equal(response.status, 200);
    return response.json();
  }));
  assert.ok(replies.every(reply => reply.read_at === replies[0].read_at));
  const other = fixture.fixtures.find(row => row.mode === 'key_conflict');
  const conflict = await resilientFetch(url(other.id), { method: 'POST', headers: headers(row.key) });
  assert.equal(conflict.status, 409, 'One idempotency key must not update two notifications');
  results.push({ case: 'concurrent', requests: 8, stable_result: true, key_conflict_rejection: 409 });
  const result = { result: 'PASS', cases: results };
  await writeFile('/probe-data/http-results.json', JSON.stringify(result));
  console.log(JSON.stringify(result));
} finally {
  globalThis.fetch = nativeFetch;
  await switchFault('none');
}
