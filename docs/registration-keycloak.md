# New account registration and Keycloak

## Upgrade and test

From the project root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-notifications.ps1 -WithMonolith
```

This preserves existing passwords/volumes, generates a new local provisioner secret if
missing, updates the existing Keycloak realm's client configuration, and tests both new
customer and provider accounts. Look for PASS with flow:

`new registration -> Keycloak login -> own inbox`

The live probe passed against the running Docker stack through localhost on 2026-11-08.
It registered customer ID 5 and provider ID 7, received notification ID 19, and confirmed
duplicate registration 409 and cross-user ownership rejection 403. It registers
two synthetic accounts, signs in through the real code+PKCE flow, checks the /me account
mapping and empty own inbox, rejects duplicate registration, approves the new provider,
waits for its RabbitMQ-driven notification, marks it read and checks another user gets 403.
The synthetic users and their approval notification remain as inspectable demo data.
Random probe passwords are never printed or saved in evidence.

## User flow

Customers sign up at http://localhost:8080/register and providers at
http://localhost:8080/provider/register. They then continue to the normal Keycloak sign-in
page using the same email and password. Providers remain pending until admin approval.
The application's name/phone/company fields remain in their original domain tables.

An account made locally before this upgrade can be linked by submitting the same role's
registration form with its existing email and password. The application checks the stored
bcrypt hash and preserves its ID and domain data. It never resets an existing Keycloak
password. Already linked active accounts get 409 when registered again.

## Failure and identity safety

- Local account/profile/wallet creation and its pending registration record are atomic.
- Only the hashed password is stored locally. The chosen password is sent to Keycloak once
  over the private Docker network; it is not stored in an outbox, log or registration record.
- If Keycloak is unavailable, return 503 and leave pending state. Retry with the same email
  and password; no duplicate local account is created. Legacy local-password login is blocked
  while provisioning is pending. A successful Keycloak login remains authoritative.
- If Keycloak created the account but its response was lost, a retry confirms the existing
  role, legacy ID and email mapping before marking local registration active. A mismatch
  returns 409 without changing the remote user's password, roles or attributes.
- Role and legacy ID come from server-owned account data, never client JSON fields.
- New email addresses are not falsely marked verified; this local demo has no SMTP email
  confirmation requirement. It does not prove real-world email ownership.
- One email is reserved for one role in this demo to match Keycloak's unique email policy.

The provisioning client is confidential, uses client credentials and receives manage-users
only in the homeservice realm. Its secret exists only in the ignored environment file and
the monolith/configuration containers. It has no browser flow or direct password grant.
The ordinary Notifications API and worker never receive that secret or admin credentials.
Keycloak 26.8.2 additionally requires the built-in kc-admin-api scope for Admin REST access.
The provisioner has basic/roles/kc-admin-api scopes; the browser client does not receive
the admin API scope. The setup checks an actual service token against the user-management
endpoint rather than merely asserting that a role assignment exists.
The setup container uses the bootstrap admin only to configure the realm/client and then
exits. Mapping attributes are admin-only in the Keycloak user profile.

## Verification status

Local Node tests cover both roles, provider profile/wallet creation, retry after unavailable
Keycloak, lost-response confirmation, old-account linking, malicious mapping fields and
conflicting remote identities. Existing identity/OIDC and Notifications tests also pass.
Live Keycloak profile behavior and browser login also passed in the probe described above.
