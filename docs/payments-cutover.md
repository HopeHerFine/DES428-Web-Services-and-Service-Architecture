# Payments cutover and recovery

## Rehearse on Windows

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\check-payments-cutover.ps1
```

The helper temporarily stops the original stack without removing its volumes,
exports clean source to a unique fixture project, and creates synthetic financial
history through the inherited booking/payment/completion APIs. It imports that
history, verifies the new Wallet through an unpublished gateway, rolls back before
release, verifies the old Wallet, then repeats cutover into another retained target.
It exercises new payments after release, restarts the committed target, stops only
the fixture containers and restores the original installation.

No original application data is copied into this rehearsal. Fixture volumes and
backups are retained for inspection. Its result is written to
`docs/evidence/payments-cutover-rehearsal-latest.json`. CI separately asserts that
public ingress is closed before release and rejects rollback after public release.

## Actual cutover

After the rehearsal passes, the operator can run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\switch-payments.ps1
```

This changes the running installation. Stop any custom writers outside Compose
first. The existing integrated Notifications project must be selected, and its
seeded Keycloak provider login must remain available for the read-only browser
check. A fresh Payments pilot has no legacy cutover to perform and is rejected.

The script stops public ingress and all source/target writers. It retains the
original SQLite database and saves a consistent backup inside the monolith volume
at `payments-cutover-backups/<run-id>.db`. An immutable financial snapshot is saved
in the dedicated `cutover-source` volume. Neither historical source tables nor
financial volumes are dropped. Each new attempt uses a new PostgreSQL volume
whose name contains the project and run ID; previous imported copies are retained.

The importer validates all rows and reconciles Wallet totals. Only after matching
the frozen source does it activate a guarded source marker. A private gateway with
no published port checks Keycloak login, the remote Wallet and SSR without financial
writes. Writers are stopped again and the complete target is rechecked before
committing public release and opening the ordinary gateway.

Source startup is blocked in the prepared phase. The activated phase starts only
with explicit private-verification settings. The monolith also checks that the
Payments readiness snapshot hash and cutover run ID match its committed source marker.
Both the API and Worker also read a small read-only marker volume and verify their
database binding before serving or consuming events; an empty/older copy is refused.
They do not receive the source snapshot or SQLite volume. Readiness is an internal management endpoint;
business calls continue to validate Keycloak tokens and ownership.

## Pause and rollback before opening

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\switch-payments.ps1 -PauseBeforeOpen
```

The import and read-only checks finish but localhost:8080 stays closed. To continue,
run the same command without the switch. To return to the original installation:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\switch-payments.ps1 -RollbackBeforeOpen
```

Rollback requires an unchanged legacy snapshot and a target with no new receipts,
ledger effects, payment-state changes, Wallet changes or outbound events. It changes
only the source runtime marker back to legacy and opens the original stack. It
does not overwrite SQLite or delete the PostgreSQL copy. A later attempt chooses
a different target. Pre-release failures attempt the same guarded rollback.

If verification is unavailable, maintenance stays closed and all copies remain.
After release, old-wallet rollback is refused: recover forward instead of restoring
an old balance over new work. Do not remove a maintenance marker manually merely
to get a green healthcheck.

## Restart and recovery

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-payments.ps1
```

Non-secret project/run/hash/phase and volume-selection receipts live under
`runtime/payments-cutover/`. Keep them with the retained Docker volumes. If the host
receipt is lost, `switch-payments.ps1` reconstructs the deterministic target choice
from a released SQLite marker. The source backup remains retained. No credential
is exported into a host settings file. Never substitute an empty target or start
the legacy-reset Compose file against a migrated source.

## Pending events and ownership

Old `payment.succeeded` events may be published after migration. A source witness
records which paid/refunded orders the snapshot covered. Matching legacy events
are acknowledged without a second financial transition; Notifications still receives
its own durable copy. Mismatched provider IDs/amounts fail validation. Existing
billing-producer history is refused rather than mixed into a legacy import.

After activation, booking detail no longer reads the legacy intent table and provider
registration no longer writes the old Wallet table. Those historical tables remain
retained for audit and pre-release rollback. Deployment still selects the Payments
Compose extension explicitly; final canonical-stack integration and combined
offline/RAM acceptance remain separate steps.
