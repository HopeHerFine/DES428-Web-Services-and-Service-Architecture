# Notifications observability

Run from PowerShell at the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\check-observability.ps1
```

This builds and starts the migration stack, reloads nginx, logs in through Keycloak,
loads the real SSR inbox with a sampled trace, and checks three healthy Prometheus
scrapes, a monolith-to-notifications parent/child span, and the provisioned Grafana dashboard.
Only a successful deployed check writes `docs/evidence/observability-latest.json`.

- Dashboard: http://localhost:3000/d/notifications (local anonymous Viewer)
- Jaeger: http://localhost:16686 (select monolith, notifications, or notifications-worker)
- Prometheus targets: http://localhost:9090/targets

The dashboard shows healthy targets, request rate, server errors, response p95,
and applied/duplicate event counts since worker startup. Generate requests before
expecting traffic graphs; a rate needs at least two scrapes. Low traffic can leave
p95 empty. These are measured values, not example data.

HTTP spans propagate W3C trace context from the SSR client into FastAPI. Domain
transactions store their trace carrier in the outbox, so delayed publisher retries
and RabbitMQ consumers can join the initiating trace. Older outbox rows without
context start a new trace. API and worker logs contain trace IDs; gateway logs
contain correlation IDs. Logs remain on Docker stdout; no central log store is included.

Prometheus keeps seven days on its volume. Jaeger uses bounded memory (5,000 traces)
and loses history on restart. Monitoring ports bind only to this machine. The gateway
blocks `/api/metrics` and `/metrics`; Prometheus scrapes services internally.

References: [OpenTelemetry propagation](https://opentelemetry.io/docs/languages/js/propagation/),
[Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/).
