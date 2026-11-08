# Notifications migration

## Start and verify

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-notifications.ps1
```

Docker Desktop with Linux containers is required. No host Node/Python installation
is needed for startup. The `-WithMonolith` option remains accepted for compatibility;
the full stack is now the default. The root `docker-compose.yml` includes the shared
Notifications Compose definition, so there is one service configuration to maintain.
The first start requires internet for images and packages; offline first boot is not supported.

Startup preserves volumes/passwords, configures Keycloak without deleting its realm,
imports old notifications, then checks RabbitMQ/PostgreSQL delivery, monolith outbox,
real browser PKCE login and ownership, new registrations, dashboard targets and trace links.
Smoke checks create inspectable demo bookings/providers; do not run them against production.

## Ownership and authentication

Notifications owns its PostgreSQL inbox, processed-event receipts and write receipts.
Other contexts remain in the Next.js/SQLite monolith. The monolith reads Notifications
over HTTP; external mode never falls back to its legacy inbox table.
Keycloak subjects are UUIDs; admin-managed `role` plus `legacy_user_id` map recipients
without confusing overlapping customer/provider IDs.

Authorization code + PKCE S256, signed state, nonce, issuer/audience/expiration/signature
checks protect login. The API separately verifies RS256 access tokens and ownership.
Direct browser password grants are disabled. Five-minute access tokens require sign-in again;
no refresh token is stored. nginx blocks cross-origin application writes and serves
the canonical origin http://localhost:8080. Keycloak uses development mode and H2
for this local demonstration. This is not a production identity deployment.

## Historical data

Startup reads the monolith's legacy notifications in a consistent read-only SQLite
transaction and writes a temporary UTF-8 snapshot for the PostgreSQL importer. Nothing is
deleted from SQLite. Role, recipient, text, order link, creation time and read state
are preserved; PostgreSQL assigns new notification IDs.
Each source row has a stable hash of `LEGACY_SOURCE_ID` plus the old row ID.
Receipts make retries skip already imported rows, preserving newer PostgreSQL read state.
Validation occurs before the import transaction. Do not rotate LEGACY_SOURCE_ID or
reuse the same local settings for a different source database. Do not import concurrently.

The importer can be rerun with `migrate-notifications-history.ps1` after startup.
It does not replay historical domain events; that would risk duplicate domain effects.

## Delivery and failure behavior

Domain changes and UUID outbox records commit together. The publisher sends persistent
messages with confirms and marks rows only after broker acceptance. Failed attempts
retain the same event ID. Consumer notification writes and processed-event receipts
commit together, followed by acknowledgement. Malformed events go to the dead-letter queue.
Mark-read is owner-scoped and supports stable Idempotency-Key replay; key reuse on
another notification returns 409. Browser retry uses timeout, bounded exponential
backoff and jitter. Resilience and broker restart probes have passed on the Docker host.

## Verification and remaining limits

- Local unit tests: 72 Node and 39 Python tests passed.
- Pact: five consumer/provider HTTP interactions passed locally; a deliberately
  missing response field was correctly rejected. Local verification used SQLite.
- Docker evidence: registration, token security, three HTTP faults/concurrency,
  broker/worker recovery, dashboard and cross-service trace checks passed.
- Historical import and fresh-source/fresh-volume boot passed on the Docker host.
- The previous migration commit passed all GitHub jobs. Pact now has an isolated
  Docker Compose command shared with CI; use the new commit run to verify this increment.
- Jaeger is memory-backed and loses traces on restart. Logs stay on Docker stdout.
- Prepared offline/fresh-volume boot passed on the owner's host: maximum sampled
  containers 1.13 GiB under a 7.76 GiB Engine budget, during a 60-second workload.
  See [measured result and limitations](offline-memory.md). Rehearse again after Service 2/Saga.
- Literal docker compose up from the unprepared canonical clone remains a delivery
  gap: current normal startup creates settings through the PowerShell script.
- An inherited race repair, Service 2, Saga and the final team report/video are not
  established by these Notifications checks.

For the reproducible completion checklist, see [handoff](notifications-handoff.md).
