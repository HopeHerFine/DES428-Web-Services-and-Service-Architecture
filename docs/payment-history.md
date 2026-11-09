# Payments history: import tooling and isolated rehearsal

The importer/exporter are implemented. The guarded live cutover and rollback
procedure is described in [payments-cutover.md](payments-cutover.md).
Do not bypass that guard or run these tools against a changing source. The safe
command available now is a **synthetic rehearsal**, using dedicated fixture data:

```powershell
docker compose -f compose.payments-history.yml run --build --rm history-check
```

This command uses an in-memory SQLite source, exports a fixed financial fixture,
and imports it into its own disposable PostgreSQL database. It opens no application
database, uses no application settings/volumes, publishes no ports and does not
stop the original stack. The check resets only the explicitly named fixture DB.
It imports twice, checks all wallet totals, preserves historical transaction IDs
and timestamps, settles an imported pending intent, and confirms another replay
does not overwrite the new payment. Expected final output contains:

```text
"result": "PASS"
"probe": "synthetic-payments-history"
"wallets_reconciled": true
"historical_events_emitted": 0
"reimport_preserved_new_payments": true
```

These are synthetic test values, not measurements of a user's actual balances.
CI runs the same command in the Payments job. To clean up only this test project:

```powershell
docker compose -f compose.payments-history.yml down --volumes --remove-orphans
```

## Import rules

`scripts/export-payments-history.mjs` opens SQLite read-only and selects financial
fields in a single SQLite read transaction: commercial booking snapshots, payment
intents, transaction rows and provider wallet balances. It excludes OTPs, addresses,
emails and account passwords. The CLI requires `PAYMENTS_SOURCE_OFFLINE=true`, a
stable `LEGACY_SOURCE_ID`, `LEGACY_DB_PATH` and a new `LEGACY_EXPORT_FILE`; it refuses
to overwrite an existing snapshot and never prints the snapshot to the console.

`payment_service.import_history` reads that file, validates ownership, amounts,
references and unique legacy effects, and writes one transaction into an **unused**
Payments database. PostgreSQL table locks serialize the empty-target check/import
against concurrent target writes. Only an identical initial snapshot can be replayed.
A changed snapshot/source or pre-existing Payments data is rejected. No historical
notification/payment events are emitted. Sequence state allows new PostgreSQL
transaction IDs to continue above the imported IDs.

Historical transaction IDs, timestamps and visible financial fields are retained.
The complete exported snapshot is also retained in `history_imports`, including
old gateway references and intent IDs. The pilot's new API addresses an intent by
order ID; it does not reactivate the old secret-only gateway webhook.

Wallet balances are authoritative source values. They need not equal the sum of
the exported payout rows, for example if money was adjusted previously. For each
provider, `wallet_openings` stores the difference between its source balance and
the successful imported ledger effects. Wallet reads add that opening adjustment
to the ledger sum. A negative opening adjustment is allowed and is auditable from
the archived source; it is not an invented transaction. Both balance and commission
owed are reconciled before the transaction commits.

Malformed/missing ownership, invalid amounts, duplicate effects and inconsistent
settlement states fail the whole import. The importer never silently repairs them.
Unexpected legacy states require review before a cutover can proceed. Old webhook
retry payloads are outside this financial snapshot; the old webhook stays disabled
in external Payments mode.

For an operator-controlled offline import inside the Payments runtime:

```text
python -m payment_service.import_history --file /history/payment-history.json --confirm-offline
```

Its DATABASE_URL must refer to the intended unused Payments DB. The explicit flag
is an acknowledgement, not a way for the importer to detect/stop other writers.

## Before a real cutover

Stop gateway access, the monolith and every old/target writer; back up the original
database and keep the immutable snapshot and its reported SHA-256. Export and
import while frozen, reconcile against that exact source, and only then activate
external Payments together with its Booking projection. Do not resume legacy
payment writes after the snapshot and later activate a stale imported database.

The original source tables are never dropped. The cutover procedure adds source
markers, target verification, private browser checks, pending legacy financial
event handling and guarded pre-release rollback. The original installation is
not migrated until an operator explicitly commits that procedure.
