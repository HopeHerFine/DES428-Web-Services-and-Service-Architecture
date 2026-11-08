# RabbitMQ and Notifications worker process recovery

## Run

With the integrated Docker stack running:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\check-broker-recovery.ps1
```

The test briefly stops RabbitMQ and the worker, delaying notifications for any concurrent
users. It restores both through the host script's finally block. No volumes are deleted.

## Live checks

1. Stop the worker and verify consumer_count=0. Publish eight copies of one persistent
   event plus an ordered sentinel with publisher confirms; PostgreSQL must have no effect yet.
2. Stop and start the RabbitMQ process while the worker remains stopped. The queue must
   retain at least nine messages and the event must still have no notification effect.
3. Start the worker. Wait for the sentinel receipt, then verify the eight duplicate deliveries
   created exactly one notification.
4. Stop RabbitMQ again. Approve a newly registered synthetic provider through the real
   monolith API; the domain change must succeed while no notification exists yet.
5. Restore RabbitMQ. The monolith publisher and worker must reconnect automatically and
   the pending outbox event must produce exactly one approval notification in PostgreSQL.

On success, actual observed results are saved to docs/evidence/broker-recovery-latest.json.
The new script has not yet been verified in a Docker run; these are assertions to execute,
not a claim that recovery has passed.

## Cleanup and limits

The synthetic provider account and its real approval notification remain as inspectable demo
data. Credentials are random and never printed. Directly queued test notifications and their
event receipts are removed using IDs recorded in runtime/probes/broker-recovery.json.
Cleanup sends a fresh ordered barrier and waits for its receipt before deleting those rows,
so a queued duplicate cannot recreate a fixture after its receipt was deleted.

If restoration/cleanup fails, the manifest is kept for the next cleanup attempt. Restore the
stack and rerun the script; it attempts old fixture cleanup before creating new fixtures.
Do not delete the manifest or volumes to hide a failing test.

These tests restart the existing broker and worker processes with their volumes intact;
they do not test forced broker-container recreation, disk loss or a worker crash exactly
between database commit and acknowledgement. Event-duplicate behavior has separate tests.
