# Bangkok Homeservice Architecture Dossier Draft

**DES428 Web Services and Service Architecture**  
**Team:** SorMineMelody  
**Status:** Working draft for team review, 13 November 2026  
**Submission revision and tag:** [Confirm final commit and `capstone-final` tag]  
**Area owners:** [Copy names and pull-request links from `OWNERS.md` when agreed]

This document describes the team's migration of Bangkok Homeservice from a Next.js and SQLite monolith to a system with separate Notifications and Payments services. It brings together the current repository design, the team's captured demonstrations, and the operational checks needed to reproduce them. It is a draft: statements marked **TEAM TO CONFIRM** require an owner to check the exact final commit, add first-hand evidence, or state the team's own architectural judgement. The seven sections follow the structure required by the assignment brief. The attached evidence PDF supports particular captured runs; a screenshot of one run is not a claim that every future run will have the same result.

## 1 System map

We started with Bangkok Homeservice, a home-services marketplace built
as a Next.js monolith with SQLite. Customers book services, providers
manage their work and wallet, and administrators manage the marketplace.

We extracted Notifications and Payments into separate FastAPI services.
Each service uses its own PostgreSQL database. The monolith still serves
the web pages and the business functions that we have not extracted.

nginx is the public entry point at http://localhost:8080. It routes web
pages to the monolith, notification API requests to Notifications,
selected payment API requests to Payments, and authentication requests
to Keycloak.

The monolith also calls the remote services while rendering pages.
Our Jaeger captures show a notification-page request crossing from
Monolith to Notifications and a wallet-page request crossing from
Monolith to Payments.

RabbitMQ carries events between components. The Notifications worker
processes events into inbox records. The Payments worker consumes
billing events and publishes payment results. Booking receives payment
results and updates its local projection.

Prometheus collects metrics, Grafana displays dashboards, and Jaeger
collects traces. These tools let us inspect the requests used in our demo.

### Boundary map

[NEED FROM ME: add the final architecture diagram after the team checks
the HTTP and event arrows against the code.]

### Boundary account

| Boundary | What crosses it | Implemented decision |
| --- | --- | --- |
| Browser → nginx | Page and API requests | We use nginx as the public entry point at localhost:8080. |
| nginx → Next.js | Web pages and retained API routes | We keep the user interface and retained functions in the monolith. |
| nginx → Notifications | Requests under /api/notifications | We route these requests to the Notifications API. |
| nginx → Payments | Payment intent, wallet and transaction API requests | We route these selected payment routes to the Payments API. |
| nginx → Keycloak | Authentication requests under /auth/ | We route authentication requests to Keycloak. |
| Next.js → Notifications | Authenticated remote inbox and mark-read requests | We use the Notifications client for remote notification operations. |
| Next.js → Payments | Authenticated remote payment requests | We use the Payments client for remote payment operations. |
| Monolith outbox → RabbitMQ | Domain events | We publish pending events from the monolith's broker outbox. |
| RabbitMQ → Notifications worker | Subscribed domain events | The worker processes events into the Notifications database. |
| RabbitMQ → Payments worker | Billing events | The worker applies billing events in the Payments service. |
| Payments → RabbitMQ → Booking | Payment result events | Booking consumes payment results into its local projection. |
| Notifications → Notifications PostgreSQL | Inbox records and processing/write receipts | Notifications stores these records in its own database. |
| Payments → Payments PostgreSQL | Payment state, ledger records and outbound events | Payments stores these records in its own database. |
| Services → observability tools | Metrics and traces | We use Prometheus, Grafana and Jaeger to observe the running system. |

### Evidence and source references

- Routing: [nginx configuration](../gateway/nginx.payments.conf).
- Service startup: [root Compose file](../docker-compose.yml) and
  [Payments configuration](../compose.payments.yml).
- Remote calls:
  [Notifications client](../lib/modules/notifications/client.js) and
  [Payments client](../lib/modules/payments/client.js).
- Recorded startup, requests and traces:
  [verification evidence for b8825e0](verification/b8825e0/README.md).

## 2 Boundary decisions

### Notifications

The inherited README ranks Notifications as the cleanest first cut because the existing code already consumed outbox events and wrote its own inbox. The migration turns this into a remote service with an explicit API and its own PostgreSQL storage. The Next.js application reads the inbox over HTTP; the Notifications migration documentation says external mode does not fall back to the old inbox table. An event publisher and RabbitMQ worker replace the in-process delivery path. This changed the failure mode: a notification may arrive after the initiating request, and an event may be delivered again. The service therefore stores processed-event receipts and acknowledges messages only after its database work commits.

The first-cut argument in the inherited README is a hypothesis provided with the case study, **not evidence produced by this team**. The team must state whether its own tests and traces support that ranking. For example, the captured Notifications trace shows a real `GET /notifications` request involving both the monolith and Notifications. The trace establishes the HTTP seam and its parent-child relationship; it does not, by itself, prove that Notifications was the best possible first extraction.

**TEAM TO WRITE, Notifications four-part defence:** Claim: [why this seam was appropriate for this team]. Fair alternative: [for example another context or retaining the inbox longer; explain it accurately]. Own evidence: [measured trace, migration test or failure run that would differ under the alternative]. Accepted tradeoff: [the real operational or consistency cost]. The owner must write this in their own words and be ready to answer for it live.

### Payments and Wallet

The inherited README places Payments and Wallet second. It describes an existing asynchronous, idempotent payment boundary, with one important coupling: payment settlement changed Booking-owned `payment_status`. In the current service design, Payments consumes immutable billing snapshots, keeps its own intents and ledger, and publishes payment results for Booking to project. The demo uses a simulated gateway; it does not call a real payment provider. The provider wallet reads a remote ledger rather than the monolith's previous financial tables.

This seam brings stronger consistency and migration obligations than Notifications. A payment can be requested, settled, completed, cancelled and refunded while events are in flight. A retry must not create a second charge. The team also has to consider historical intents and wallet balances before switching an existing deployment. The Payments cutover documentation describes a snapshot, private verification before opening public ingress, a retained source backup and guarded rollback before release. Those are safeguards documented by the project; the final owner should distinguish rehearsed steps from any real migration performed for submission.

The inherited README identifies Booking and Bidding as a more difficult alternative because both use the `slot_holds` uniqueness rule. Extracting those paths without a common database would require a distributed answer to concurrent reservations. This is a useful comparison, but the team's final choice needs its own measured or tested support rather than repeating the inherited wording.

**TEAM TO WRITE, Payments four-part defence:** Claim: [why Payments was the second seam]. Fair alternative: [why another proposed seam or a different order was considered]. Own evidence: [payment/refund test, cutover rehearsal, trace, concurrency test]. Accepted tradeoff: [event lag, extra worker/database, simulated gateway, operational cost]. State what the evidence actually proves and where the demo remains limited.

## 3 Contracts and interfaces

HTTP contracts define what the Next.js consumer expects from each extracted API. The Notifications consumer uses an authenticated inbox endpoint and a mark-read action with an `Idempotency-Key`. The Payments consumer uses intent, simulation, wallet and transaction endpoints. The services also consume and publish events; those event schemas and delivery guarantees are separate from the HTTP Pact tests.

The repository's Pact runner generates contracts from the actual web clients, then checks them against the real FastAPI providers with isolated PostgreSQL test databases. The Notifications suite has five interactions: own inbox, idempotent mark-read, cross-account rejection, empty inbox, and invalid credentials. The Payments suite has six: own intent, idempotent settlement, foreign intent rejection, invalid credentials, provider wallet with remote ledger, and customer transactions. The user supplied a local `act` run in which all eleven interactions passed and the contracts job ended with `Job succeeded`. The project documentation explains an important limit: provider-state setup uses test fixtures and identity verification is stubbed in Pact. Real Keycloak token checks, event delivery and concurrent settlement are verified by other tests, not by the HTTP contracts alone.

The contract command is `docker compose -f compose.contracts.yml run --build --rm contract-tests`. The GitHub Actions `contracts` job uses that same Compose command, checks that generated Pact JSON exists, uploads it on GitHub, and cleans up the isolated test containers. On the owner's Mac, `act` reproduced the job. The local workflow condition skips only artifact upload because that action was not supported by the installed `act` version; the local run still generated and checked both contracts. **TEAM TO CONFIRM:** attach the GitHub Actions result for the final submission commit. A successful local `act` run does not itself prove the remote Actions run passed.

| Interface | Consumer and provider | Evidence and limitation |
|---|---|
| Notifications HTTP | Next.js client to Notifications FastAPI | Five Pact interactions passed locally; JWT signing is tested separately. |
| Payments HTTP | Next.js client to Payments FastAPI | Six Pact interactions passed locally; financial races are tested separately. |
| Domain events | Outbox and RabbitMQ to service workers | Event IDs and receipts address redelivery; Pact does not check this transport. |
| Observability | OpenTelemetry and Prometheus endpoints to Jaeger and Grafana | Captured traces and dashboard show deployed behavior for specific requests. |

**TEAM TO CONFIRM:** list the exact event names and payload fields used at the two service seams in the final code. For each, identify the producer, consumer, event ID, retry behavior and versioning decision. Add links to the corresponding source and tests.

## 4 Security model

Keycloak is the identity provider for the integrated system. The new APIs verify access tokens rather than trusting a token merely because it passed through nginx. The Notifications migration documentation records issuer, audience, expiration and signature checks and a mapping from Keycloak subjects to legacy customer/provider identifiers. The Payments service likewise requires token claims and derives the caller's role and legacy ID from them. The service should not accept a customer ID or price supplied by the caller as authority over a different person's payment.

The supplied evidence PDF captures Beat 3 returning `401` for missing, forged, wrong-audience and expired tokens and `200` for a valid token. Beat 1 captures Notifications rejecting a cross-account mark-read with `403` and a forged token with `401`. Another captured test shows a corrected object-level authorization case: an owner can read job details while an unrelated customer is denied; the screenshot labels the suite as seven passed and zero failed. **TEAM TO CONFIRM:** identify the exact inherited vulnerable route, the original failing request, the code change, and the after-fix result. Do not claim that a before-fix attack was shown unless the team has that capture.

Authentication and object-level authorization answer different questions. A `401` means the request did not carry an acceptable identity token. A `403` after valid authentication means the caller is identified but lacks permission for that record. The live defence should show both, because a valid token is not enough to prove that users cannot read one another's data.

The gateway keeps a canonical local origin and blocks application writes from unrelated origins according to the migration documentation. Local demo accounts and the Keycloak development configuration are for a laptop demonstration, not a claim of production identity hardening. The final report should include the exact role mapping and any remaining access-control risks that the team's owner has reviewed.

## 5 Consistency model

The migration crosses transaction boundaries that were once inside one SQLite process. The documented pattern is a transactional outbox: a domain change and a UUID event record commit together. A publisher sends persistent messages to RabbitMQ with confirms and marks an outbox row as sent only after broker acceptance. If the reply or acknowledgement is lost, the same event may appear again. The consumer saves its effect and processed-event receipt in one local transaction before acknowledging the message. This yields at-least-once transport with one intended business effect for a repeated event ID; it is not a claim that RabbitMQ delivers exactly once.

Notifications and Payments have different effects. Notifications produces an inbox record. Payments consumes billing snapshots and records financial entries, while the monolith's Booking context projects payment results. The Payments README describes settlement and cancellation guards, unique financial entries, and event receipts. The user supplied a happy-path probe with `paid`, `cancellation_requested`, then `refunded`, reporting one charge, one refund and `refund_cents: 64200`. The newer evidence PDF captures an equivalent order-8005 run: paid then refunded, one charge and one refund of 64,200 satang. These are specific observed demo runs; the team should use one consistent order ID and matching screenshot set in the final dossier.

The assignment also asks the team to defend orchestration or choreography for its saga. **TEAM TO WRITE:** draw the actual steps from booking to payment and refund, identify the owner of each local transaction, identify the compensation, and state who decides the next step after failure. Do not label the flow orchestration or choreography until the owners agree on how the code actually coordinates it. Explain the consequence of a message arriving late or twice using a test from the final commit. The existing screenshots prove the reported happy path and refund outcome; they do not by themselves prove every failure and recovery branch of the saga.

Historical data is another consistency issue. Notifications migration documentation describes a read-only SQLite snapshot and idempotent importer into PostgreSQL. Payments cutover documentation describes a retained backup and guarded switchover for existing financial history. **TEAM TO CONFIRM:** document which of these paths was exercised on the final clean demo and which was only rehearsed with synthetic fixtures. The report should not imply that production-like financial data was migrated if the team only used a disposable project.

## 6 Failure model

Cross-service HTTP calls can time out even after the remote write has committed. A caller that retries without a stable key can create duplicate effects. The Notifications client uses a timeout, bounded exponential backoff and jitter for eligible writes, while the mark-read endpoint binds an idempotency key to the authenticated caller and notification. The service stores the result with the write so a retry can return the same result. Reusing the key for a different notification is rejected.

Beat 2 injects three controlled faults: a reply delayed after the write, a slow reply beyond the client's timeout, and temporary API unavailability. The supplied evidence PDF reports PASS for all three and one persisted write receipt per case. Its terminal capture also prints `PASS: three faults survived; 8 concurrent requests committed one receipt.` The repository's resilience documentation explains that eight requests target one notification with one key and should return one read timestamp and one write receipt. The final dossier should retain the full run output and identify the exact commit used; the screenshot is evidence of this captured run, not a general throughput benchmark.

The Payments service has separate tests for concurrent settlement and a payment/cancellation race. The supplied evidence PDF has a capture labelled 23 passed, one warning, and explicitly says it predates an additional completion/payment race test. Do not present that screenshot as evidence for the later test. The final owner should attach the more recent test result and explain the database constraint, lock, or receipt that prevents duplicate financial entries.

The failure model also includes broker and worker outages, malformed events, and observability gaps. Project documentation describes durable RabbitMQ messages, reconnecting workers, dead-letter handling and a broker-recovery script. Some older documentation still says that a particular recovery script had not been run. **TEAM TO CONFIRM:** use only the final run log or captured result to claim live recovery, and update stale status paragraphs in the repository before submission. The demo's local Jaeger storage is memory-backed and loses traces on restart. A missing old trace can be a storage limit rather than proof that tracing was absent. Prometheus needs enough scrapes and traffic to compute rates and p95.

## 7 Operations and delivery

The root README documents `docker compose up` from a fresh clone as the intended one-command startup. It lists the local application at port 8080, Grafana at 3000 and Jaeger at 16686, along with seeded accounts. The canonical-boot documentation explains that a non-root bootstrap generates random settings in a dedicated Docker volume, that each service receives only its own read-only settings subdirectory, and that Keycloak configuration completes before the website starts. The supplied evidence PDF shows a clean-source rehearsal in which the combined Notifications and refund Saga checks passed and the original stack was restored. The final dossier should identify the exact commit used for that rehearsal and whether the same command was rerun after the last merge.

The README names four marker scripts: `scripts/beat1-happy-path.sh`, `scripts/beat2-failure-recovery.sh`, `scripts/beat3-auth-rejection.sh`, and `scripts/beat4-find-the-trace.sh`. Beat 1 exercises the Notifications browser flow and Payments/refund flow. Beat 2 injects the three fault cases. Beat 3 checks token rejection. Beat 4 runs two observability probes and prints a trace ID for each seam. The user ran Beat 4 on a Mac and captured separate Jaeger traces: Monolith to Notifications and Monolith to Payments. The probes reported `cross_service_parent_child: true`, and both services appeared in their respective traces. These are two separate requests, not one trace traversing all three services.

The supplied evidence PDF labels the Notifications trace as two services, 16 spans and 18.59 ms for the captured `GET /notifications` request. It labels the Payments trace as two services, 15 spans and 27.26 ms for the captured `GET /provider/wallet` request. Those numbers describe the captured requests only. Earlier screenshots on the owner's Mac show different durations; choose one screenshot and its exact numbers when writing a final caption, rather than combining runs.

Both services emit structured request logs carrying a `correlation_id`. The owner verified a Notifications log for `GET /api/notifications` with a non-null `trace_id`, status 200 and duration. After enabling a Payments log handler, the owner reran the Payments observability probe and saw a JSON Payments log for `GET /api/payments/wallet` with a correlation ID, status 200 and duration. The two log entries do not prove that the same correlation ID is propagated between services; the Jaeger traces establish the cross-service request relationship. **TEAM TO CONFIRM:** capture the final Payments log, its corresponding trace and dashboard after the final merge.

Grafana dashboards exist for Notifications and Payments. The owner's Payments screenshot shows scrape health 1, request-rate spikes after demo traffic, a server-error panel at zero during that displayed period, and p95 response-time samples. The Notifications dashboard screenshot shows healthy targets and traffic around the demo. A scrape-health value of 1 means Prometheus reached the target; it does not prove every user request succeeded. An empty or sparse p95 graph at low traffic is not, on its own, a service failure. Record the selected time window and endpoint when interpreting dashboard captures.

The supplied combined offline rehearsal reports PASS with a maximum **sampled** aggregate container usage of 1.29 GiB under a Docker Engine memory limit of 7.76 GiB. The project documentation says the sampler recorded 48 observations, 20 during workload, and that the result excludes cache and is not a continuous peak or general capacity guarantee. This addresses the brief's ordinary-laptop constraint for that prepared, cached-image run. **TEAM TO CONFIRM:** match the PDF screenshot to the retained result file and to the exact final commit. A first build still needs images and dependencies available; offline execution means the prepared images were already cached.

| Cross-cutting concern | Technology in this demo | What it adds to operate | Industrial comparison for team review |
|---|---|---|---|
| Gateway | nginx | Routing configuration and one entry point to test | [Name a scale alternative and its real cost.] |
| Identity | Keycloak | An identity service, token configuration and account mapping | [Compare with an external IdP using team judgement.] |
| Messaging | RabbitMQ with outbox | Broker, queues, worker retries and dead-letter inspection | [Compare with a managed broker and operating cost.] |
| Consistency | Local transactions, event IDs and receipts | Lag, duplicate handling, reconciliation and saga reasoning | [Explain why a distributed transaction was not used.] |
| Resilience | Timeouts, bounded retries, idempotency keys | More client logic and careful retry classification | [Discuss operational limits of retries.] |
| Observability | OpenTelemetry, Prometheus, Grafana, Jaeger | Metric storage, dashboards, trace storage and log review | [Discuss retention and hosting cost.] |
| Delivery | Docker Compose, GitHub Actions, Pact and `act` | Image builds, CI maintenance and repeatable laptop checks | [Discuss when a larger deployment platform would be justified.] |

This landscape table names the technologies used in the repository. **TEAM TO WRITE:** the final column must contain the team's own fair comparison to named industrial technology and a real running cost, including the judgement to say when a larger tool is unnecessary at this scale. Do not fill it with generic claims that a technology is simply “more scalable.”

### Evidence index for editing the final dossier

| Evidence | What it supports | Source to attach or confirm |
|---|---|---|
| Clean startup | Combined services and gateway healthy | Supplied evidence PDF, page 1; final clean-clone log to confirm |
| Beat 1 | Notifications flow and payment/refund result | Supplied evidence PDF, pages 2–3 |
| Beat 2 | Three injected faults and eight concurrent requests with one receipt | Supplied evidence PDF, page 4 |
| Beat 3 | Token rejection and valid-token result | Supplied evidence PDF, page 5 |
| Beat 4 | Two parent-child cross-service traces | Supplied evidence PDF, pages 6–9 |
| BOLA and concurrency | Captured ownership and Payments test suites | Supplied evidence PDF, pages 10–11; later tests to confirm |
| Combined boot and memory | Clean-source and offline rehearsal | Supplied evidence PDF, pages 12–13 |
| Pact and local CI | Five plus six interactions, `act` job succeeded | Owner's terminal output; attach final screenshot/log |
| Payments metrics and logs | Dashboard samples and structured wallet request log | Owner's Grafana screenshot and terminal output |

**Figures in the illustrated Word draft:** the Jaeger trace captures from pages 8–9 of the supplied evidence PDF and the owner's Grafana screenshot are included beside the corresponding paragraphs. Additional captures sent by teammates can replace placeholders after each owner checks the caption. Each final figure should name the command or request, the run date, the exact commit and what the image proves.

### Submission checks before this draft becomes final

1. Replace every **TEAM TO CONFIRM** and **TEAM TO WRITE** passage with the responsible owner's verified wording, or remove the claim.
2. Add `OWNERS.md` names and links to each owner's commits or pull requests.
3. Check the final README, script commands, repository privacy, final tag and GitHub Actions run for the same submission commit.
4. Record `capstone-demo.mp4` for 8–12 minutes from a clean clone and show all four beats.
5. Have each member review one area they do not own before the 20-minute live defence.
6. Each member submits the required confidential peer review.

**AI assistance disclosure draft:** An AI assistant helped organize this draft, explain the project structure and improve wording. Before submission, the team must check each claim against its own code and captured runs, and write the boundary defences and tradeoff judgements itself. [Edit this sentence to describe what the team actually did.]

### Source documents used for this draft

- DES428 week-15 assignment brief, pages 1–6.
- `README.md`, `docs/notifications-migration.md`, `services/payments/README.md`, `docs/contracts-and-ci.md`, `docs/combined-boot-verification.md`, `docs/canonical-boot.md`, `docs/observability.md`, and the four `scripts/beat*.sh` files in the local repository.
- `SorMineMelody-pass-evidence.pdf`, 13 pages, supplied by the user.
- Owner E terminal outputs and screenshots supplied in this conversation, including the local Pact/`act` result and Jaeger/Grafana captures.

