# Notifications service

Independent FastAPI API and RabbitMQ consumer with their own PostgreSQL database.
See ../../docs/notifications-migration.md for current integration status and limitations.

## Integrated development stack

From the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-notifications.ps1 -WithMonolith
```

The script builds/starts nginx, Keycloak, the monolith, PostgreSQL, RabbitMQ, the API and
worker, then runs three probes. Open http://localhost:8080 after all probes pass.
The previous direct API port 8001 is intentionally no longer published by Compose.
The original root docker-compose.yml remains separate until final team integration.

## API and ownership

GET /health, GET /ready, GET /api/notifications, POST /api/notifications/{id}/read.
RS256 tokens require issuer, audience, subject and expiration. role and legacy_user_id
claims identify the recipient. Every inbox/read update checks both values. Repeated mark-read
preserves the original timestamp. Request IDs and request logs support troubleshooting.

## Events

The worker consumes the durable homeservice.events topic exchange via notifications.events.
Persistent messages have this shape:

```json
{"id":"globally-unique-stable-event-id","type":"booking.completed","payload":{"order_id":8001,"customer_id":1}}
```

Supported types: review.created, booking.status_changed, booking.completed, bid.accepted,
payment.succeeded, provider.approved. Receipt and notifications commit in one transaction;
acknowledgement follows commit. Invalid messages go to notifications.dead. Producers confirm
broker acceptance before marking their outbox sent. Rating recomputation stays in the monolith.

## Local tests

Use Python 3.12+ from this directory:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
```

Tests use temporary SQLite databases and generated RSA keys; network key retrieval is stubbed,
but production JWT verification is exercised. These tests are not PostgreSQL/Keycloak evidence.
For an isolated local API process, run run-local.ps1 with the chosen Python interpreter.
It uses SQLite, no worker, and requires a real configured issuer for protected calls.

## Docker probes

app.smoke: eight RabbitMQ deliveries, exactly one PostgreSQL notification; removes its rows.
app.smoke_monolith: real monolith approval reaches PostgreSQL; leaves synthetic provider data.
app.smoke_gateway: real code+PKCE login, booking, remote SSR inbox, mark-read, ownership 403,
forged-token 401; leaves its booking as inspectable demo data. Startup runs them in this order.

Collect evidence from actual Docker runs. Passing tests alone does not complete the capstone.
