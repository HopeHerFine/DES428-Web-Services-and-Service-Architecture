# Payments & Wallet — second-service pilot

An independent FastAPI deployment and PostgreSQL database own payment intents,
transaction receipts, append-only financial entries and an outbound event table.
This is a **simulated gateway**, not a connection to a payment provider.

Booking owns orders and slot holds. It publishes immutable billing snapshots in
the same SQLite transaction as placement/completion/cancellation. Payments consumes
those snapshots over RabbitMQ and never opens the monolith database. The Node
subscriber applies `payment.succeeded` and `payment.refunded` to Booking-owned
payment status after its own deduplicated transaction.

## Run the pilot

The default `docker compose up` remains the verified Notifications increment.
The Payments pilot is explicitly selected with both files:

```powershell
docker compose -p payments-pilot -f docker-compose.yml -f compose.payments.yml up --build -d --wait --wait-timeout 360
docker compose -p payments-pilot -f docker-compose.yml -f compose.payments.yml run --rm --no-deps notifications-worker python -m app.smoke_payments
```

Use a **fresh project**, with the existing stack stopped first to release the same
localhost ports. Do not remove its volumes. Do not copy its host settings into the
pilot. The pilot creates its own random settings volume and database. A project
with existing legacy payment intents/transactions/nonzero wallet balances is
rejected until a payment-history migration is implemented. A project that has
enabled external Payments must continue to use both Compose files on restart.

Application: http://localhost:8080. Payments docs: http://localhost:8080/payment-docs.
Use the existing Keycloak demo logins and password documented in the root README.
The customer can book a gateway service and use **Pay now (simulate)**. The provider
can open Wallet after completion. Delivery/projection is asynchronous; an intent
not ready yet returns 409. Retry after delivery, retaining the same request key.

Stop the pilot without deleting data:

```powershell
docker compose -p payments-pilot -f docker-compose.yml -f compose.payments.yml down
docker compose up -d --wait
```

Never use `down --volumes` on a project whose data you need to keep.

## Contracts and consistency

- `billing.booking_created`, `billing.booking_completed`, `billing.booking_cancelled`
  contain order/customer/provider IDs, amount/commission in integer cents, and method.
  They carry commercial snapshots, not customer tokens or passwords.
- The authenticated API requires RS256 Keycloak tokens with issuer, expiry and
  `payments` audience, plus mapped role/legacy ID. Ownership comes from those claims.
  Customer IDs and prices in payment requests are rejected.
- `POST /api/payments/simulate` accepts `{ "order_id": 8001 }` and an Idempotency-Key.
  A row lock serializes settlement/cancellation. One charge and one payout per order
  are additionally guarded by database uniqueness constraints.
- `GET /api/payments/intents/{order_id}`, `/api/payments/wallet`, and
  `/api/payments/transactions` expose only the caller's permitted data.
- Wallet totals are sums of authoritative ledger entries. COD completion records
  commission owed; paid gateway completion records provider earnings.
- Cancellation before payment blocks payment. Cancellation after payment records a
  single simulated refund and publishes the result. Reordered create events cannot
  resurrect a cancellation; late paid projections cannot overwrite a refund.
- The API does not share the broker credential. Its worker publishes the outbox
  with publisher confirms; a crash after publish can redeliver the same event ID.
  Consumers commit their receipts with their effects before acknowledging.
- Invalid/conflicting billing events go to `payments.dead`. Database/broker outages
  reconnect and retain undelivered work. Operators must inspect dead letters.
- The legacy secret-only webhook is disabled in external mode. A production gateway
  webhook and real refunds are outside this simulated pilot.

## Verification and remaining scope

`payments` CI runs the service suite on PostgreSQL, including eight concurrent
settlements and a pay/cancel race. It then builds an isolated full stack, signs in
through Keycloak, books/pays/completes, checks remote server-rendered Wallet,
rejects forged/foreign access, cancels/refunds another booking and repeats after
restarting Payments. It checks the monolith's legacy payment tables remain empty.

Local service tests: `python -m pytest tests -q` from this directory after installing
requirements-dev.txt. SQLite-only runs skip PostgreSQL concurrency tests explicitly.
Only a disposable database named `payments_test` is accepted for PostgreSQL tests.

This increment is **not yet the finished second seam**: legacy payment-history
import, Pact across this boundary, dedicated dashboard/fault rehearsal, offline/RAM
measurement for the combined stack, and the team's explicit Saga workflow/recovery
evidence remain. The current asynchronous refund is a building block, not a claim
that all Saga requirements are fulfilled. Do not replace the original project's
payment history or mark the team checklist complete based only on this pilot.
