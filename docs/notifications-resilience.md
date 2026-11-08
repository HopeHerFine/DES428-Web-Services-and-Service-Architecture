# Notifications fault and recovery checks

## Run

Keep Docker Desktop and the integrated stack running, then run from any PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\degde\Downloads\bangkok-homeservice\bangkok-homeservice\check-resilience.ps1"
```

This rebuilds the Notifications API/worker, prepares a Node test image before obtaining
short-lived credentials, and briefly simulates failures. It does not delete Docker volumes.
The fixture uses the seeded provider's real Keycloak login; temporary access tokens stay
in the ignored runtime/probes directory and are removed during cleanup, never printed.

## Scenarios

1. **lost_reply:** the write commits, then its successful response is delayed past the
   caller timeout and discarded. The caller retries the same Idempotency-Key and gets
   the committed result. This simulates a reply lost after a write, not packet-level loss.
2. **slow_calls:** the first response to a write is delayed 2.5 seconds. The real shared
   client helper times out after 1 second and retries with exponential backoff and jitter.
3. **unavailable:** API calls receive 503 during a short explicit time window, then recover.
4. **concurrency:** eight requests target one notification with one key. Every successful
   reply must have the same read timestamp, and PostgreSQL must contain one write receipt.
   Reusing that key for another notification returns 409 and must not change that row.

The Node probe imports the same resilientFetch source used by the browser and remote inbox
client, rather than reimplementing its retry algorithm. It asserts an actual timeout or 503
was observed, not only that a final 200 occurred. Authentication failures are not retried.

## Controls and persistence

Faults come from runtime/faults/notifications.json, mounted read-only in the API. There is
no public endpoint or user-supplied request header that enables faults. Probes have write
access to that local operator file; normal startup and probe finally blocks reset mode=none.
Health endpoints remain available during the deliberately injected business-API failure.
Slow/lost-response switches apply only once per revision and idempotency key.

The mark-read transaction locks the notification, checks ownership, updates only an unread
row, and saves its response receipt atomically. Unique receipt keys are scoped by role and
user, and cannot be reused across different notification IDs. The consumer's event receipts
remain a separate deduplication mechanism for RabbitMQ deliveries.

The fixture records its synthetic event IDs before mutations, so cleanup can remove only
its own notifications, event receipts and write receipts even if preparation fails halfway.
No real user notifications or accounts are removed. On success, the host saves the actual
measured result to docs/evidence/resilience-latest.json; failed checks do not save PASS evidence.

## Verification status

Local unit tests pass for receipt replay, ownership, key conflicts, retry/backoff/jitter,
timeout recovery, fault defaults and bounded outage flags. The new live fault/PG-concurrency
probe still requires its first Docker run. Do not treat this document as live evidence.

These cases do not yet demonstrate RabbitMQ process shutdown/restart or consumer crash
recovery. They also do not prove a repair of an inherited monolith race: the provided
booking/bidding races already have guards, and that separate team requirement needs its
own documented finding and test. Grafana/Jaeger and contract tests are subsequent work.
