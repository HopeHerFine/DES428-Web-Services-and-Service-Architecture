# Notifications migration: Keycloak and gateway increment

## Run

From any PowerShell directory:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\degde\Downloads\bangkok-homeservice\bangkok-homeservice\start-notifications.ps1" -WithMonolith
```

The script preserves database/broker passwords, adds missing session/Keycloak admin secrets,
updates managed issuer URLs to include /auth, builds images and starts the stack. No volumes
are deleted. Three probes check duplicate delivery, real monolith approval events, and the
new Keycloak/browser inbox flow. The first two passed on the user's Docker host previously;
the new third probe still requires the next Docker run. Local tests are not proof of deployment.

## Browser URLs

- Application and inbox: http://localhost:8080 and /notifications
- API docs: http://localhost:8080/notification-docs
- Keycloak: http://localhost:8080/auth/
- RabbitMQ screen: http://127.0.0.1:15672

Use localhost for the application because OIDC fixes the issuer and callback origin.
The previous direct ports 3080 and 8001 are no longer published in this Compose stack.
Only the gateway and RabbitMQ tool screen publish ports.

## Login

The seven original demo accounts are imported into Keycloak at first boot:
nong/somchai/aom@example.com, sparkle/fixit/glow@example.com and admin@edemand.test.
All use the inherited demo-only password eDemand-2026!.

Customer/provider/admin login pages redirect to Keycloak. Authorization code + PKCE S256,
a signed five-minute HttpOnly state cookie, nonce checks and RS256 token checks protect the
callback. ID/access tokens must agree on subject and mapped identity; local email/role/ID
must match before a monolith session cookie is issued. No password grant, impersonation,
client secret or auth bypass is used. Tokens do not appear in redirect query strings.

The service independently checks signature, issuer, audience, expiration and mapped recipient.
Keycloak subjects are UUIDs; role + legacy_user_id map to the monolith's overlapping integer
IDs. Keep mapping attributes admin-controlled and never enable user editing of them.
Nginx forwards an explicit bearer header preferentially, otherwise the HttpOnly access-token
cookie. Cross-origin writes are refused. Server-rendered inbox reads go through nginx with
the user's bearer token and never fall back to stale local SQLite notifications.

Access tokens last five minutes; users sign in again rather than storing refresh tokens in
the browser. Logout clears app cookies; prompt=login requires credentials on the next login.
Local HTTP is intentional; Secure cookies are added for a configured HTTPS public origin.
Keycloak uses start-dev with a persistent H2 volume for this single-laptop demonstration.
Realm import skips existing realms: later realm changes need an explicit admin update, not
volume deletion.

## Event transport

External mode writes UUID outbox records in the domain transaction. Persistent messages
use publisher confirms and are marked published only after confirmation. Failed sends remain
pending; restart preserves domain state and outbox. The consumer commits the dedupe receipt
and notifications together. Lost confirms can produce redelivery with the same UUID, not a
second effect. Invalid messages are dead-lettered. Rating recomputation stays with local
Catalog/Providers. Admin approval emits provider.approved instead of a local notification.

## What the new probe checks

It signs in three seeded accounts using Keycloak's real browser form, authorization code and
PKCE callback through nginx. It books a service via the customer API, reads the provider's
notification from the API and server-rendered page, marks it read, expects 403 for another
provider's update, and expects 401 for a forged bearer token even with a valid cookie present.
It leaves the test booking as demo data; the approval probe leaves its synthetic provider.

## Remaining work

- Provision/synchronize newly registered monolith accounts into Keycloak. Browser login in
  this increment supports the seven seeded accounts only; new local registrations are not
  automatically provisioned and cannot yet use Keycloak browser login.
- Migrate historical SQLite notifications if required; old development data is not copied.
- Add resilience switches, failure/reconnect evidence, metrics/traces, Pact and CI.
- Assemble the final root Compose with the team's second service and observability tools,
  then verify offline clean-clone boot within the 8 GB Docker budget.
- Collect actual measurements and write the team's own architecture reasoning.
