# Verification evidence — b8825e0

We ran this rehearsal on 13 November 2026 using commit
b8825e04132649210932809fe0096be73849344e.

Run by: Nititom Pongthoy, on a Mac with Docker Desktop.
Evidence collection started at 16:28:46 (+07).

We cloned the published docs/final-submission-prep branch into a new
directory. We used a separate Compose project and fresh volumes.
The original project's containers were stopped, and its data was retained.

Startup commands:

    export COMPOSE_PROJECT_NAME=homeservice-rehearsal-b8825e0
    docker compose up --build -d

## Recorded results

| Check | Recorded result | Evidence |
| --- | --- | --- |
| Startup | Application services started; configured health checks reported healthy. | [Startup](startup.txt), [commit and time](run-info.txt) |
| Notifications browser flow | Login, inbox and mark-read probe reported PASS. | [Beat 1](beat1.txt) |
| Payments refund flow | Order 8003 reached refunded, with one charge and one refund. | [Beat 1](beat1.txt) |
| Lost reply | Final status 200 after two attempts; one write receipt. | [Beat 2](beat2.txt) |
| Slow reply | Final status 200 after two attempts; one write receipt. | [Beat 2](beat2.txt) |
| Temporary unavailability | Final status 200 after three attempts, including two 503 responses; one write receipt. | [Beat 2](beat2.txt) |
| Concurrent notification writes | Eight requests returned a stable result; one write receipt. | [Beat 2](beat2.txt) |
| Invalid tokens | Missing, forged, wrong-audience and expired tokens returned 401 in the security probe. | [Beat 3](beat3.txt) |
| Valid token | The security probe returned 200 for a valid Keycloak token. | [Beat 3](beat3.txt) |
| Cross-origin write | The security probe returned 403. | [Beat 3](beat3.txt) |
| Notifications trace | Monolith and Notifications appeared in one linked trace: 2 services, 16 spans, 22.56 ms. | [Probe](beat4.txt), [Jaeger](notifications-trace.png) |
| Payments trace | Monolith and Payments appeared in one linked trace: 2 services, 15 spans, 131.83 ms. | [Probe](beat4.txt), [Jaeger](payments-trace.png) |
| Notifications monitoring | The dashboard displayed scrape health, request rate, server error rate and p95 response time. | [Dashboard](notifications-dashboard.png) |
| Payments monitoring | The dashboard displayed scrape health, request rate, server error rate and p95 response time. | [Dashboard](payments-dashboard.jpg) |
| Notifications logs | Structured API request logs included correlation_id and trace_id. | [Request logs](request-logs.txt) |
| Payments logs | Structured API request logs included correlation_id. | [Request logs](request-logs.txt) |
| Notifications Pact | The provider verified all five consumer interactions. | [Pact](pact.txt) |
| Payments Pact | The provider verified all six consumer interactions. | [Pact](pact.txt) |
| Local CI | The act contracts job ended with Job succeeded. | [act output](act-contracts.txt) |

## Trace IDs

- Notifications: c29b8e7e2f1844b7a0d120b9d64f130a
- Payments: 1540453c413a406d9f6926ab7c2ccbb8

## Scope and remaining checks

The dashboard screenshots cover 16:28–16:40 (+07), including the
fault-injection tests. Trace durations describe individual requests.

This rehearsal used online builds and cached layers. It does not establish
offline startup or a memory limit result.

The refund probe reported refund_cents: 64200.
[NEED FROM TEAM: confirm the currency unit against the implementation.]

[NEED FROM TEAM: link the hosted GitHub Actions result for the final
submission commit.]