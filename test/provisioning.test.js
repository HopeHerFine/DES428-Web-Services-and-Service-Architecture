import { test } from "node:test";
import assert from "node:assert/strict";
process.env.NODE_ENV = "test";
process.env.DB_PATH = ":memory:";
process.env.EXTERNAL_NOTIFICATIONS = "true";
process.env.PROVISIONER_CLIENT_SECRET = "unit-test-only";
const { bootstrapDb } = await import("../lib/db/bootstrap.js");
const { getDb } = await import("../lib/db/index.js");
const { registerLinkedAccount } = await import("../lib/http/provisioning.js");
const identity = await import("../lib/modules/identity/service.js");

test("registration retries pending provisioning without duplicates or password takeover", async () => {
  bootstrapDb();
  const original = globalThis.fetch;
  const input = { email: "new-customer@example.com", password: "StrongDemo123!", name: "New customer" };
  let remoteDown = true;
  let conflict = false;
  globalThis.fetch = async (url, options) => {
    if (url.endsWith("/token")) return Response.json({ access_token: "unit-only-token" });
    if (remoteDown) return new Response(null, { status: 503 });
    if (options.method === "POST") return new Response(null, { status: conflict ? 409 : 201 });
    const row = getDb().prepare("SELECT id FROM customers WHERE email=?").get(input.email);
    return Response.json([{ email: input.email, attributes: { role: ["customer"], legacy_user_id: [String(row.id)] } }]);
  };
  try {
    await assert.rejects(registerLinkedAccount("customer", input), /finish sign-up/);
    assert.throws(() => identity.loginCustomer(input), /Finish sign-up/);
    assert.equal(getDb().prepare("SELECT count(*) n FROM customers WHERE email=?").get(input.email).n, 1);
    await assert.rejects(registerLinkedAccount("customer", { ...input, password: "wrong-password" }), /already registered/);
    remoteDown = false;
    conflict = true; // The first remote create committed but its reply was lost.
    const account = await registerLinkedAccount("customer", input);
    assert.equal(getDb().prepare("SELECT state FROM identity_provisioning WHERE user_id=? AND role='customer'").get(account.id).state, "active");
    assert.equal(getDb().prepare("SELECT count(*) n FROM customers WHERE email=?").get(input.email).n, 1);
    await assert.rejects(registerLinkedAccount("customer", input), /already registered/);
    await assert.rejects(registerLinkedAccount("provider", input), /another role/);
  } finally { globalThis.fetch = original; }
});

for (const role of ["customer", "provider"]) {
  test(`${role}: creation and legacy account linking use server-owned mappings`, async () => {
    bootstrapDb();
    const original = globalThis.fetch;
    const input = { email: `linked-${role}@example.com`, password: "StrongDemo123!", name: `New ${role}`,
      role: "admin", legacy_user_id: "1" };
    let sent;
    globalThis.fetch = async (url, options) => {
      if (url.endsWith("/token")) {
        assert.equal(options.body.get("grant_type"), "client_credentials");
        return Response.json({ access_token: "unit-only-token" });
      }
      sent = JSON.parse(options.body);
      return new Response(null, { status: 201 });
    };
    try {
      const account = await registerLinkedAccount(role, input);
      assert.deepEqual(sent.attributes, { role: [role], legacy_user_id: [String(account.id)] });
      assert.equal(sent.credentials[0].value, input.password);
      assert.equal(sent.emailVerified, false);
      if (role === "provider") {
        assert.equal(getDb().prepare("SELECT is_approved FROM provider_profiles WHERE provider_id=?").get(account.id).is_approved, 0);
        assert.ok(getDb().prepare("SELECT 1 FROM provider_wallets WHERE provider_id=?").get(account.id));
      }
      const legacy = { ...input, email: `before-upgrade-${role}@example.com` };
      const previous = role === "customer" ? identity.registerCustomer(legacy) : identity.registerProvider(legacy);
      await assert.rejects(registerLinkedAccount(role, { ...legacy, password: "wrong-password" }), /already registered/);
      const linked = await registerLinkedAccount(role, legacy);
      assert.equal(linked.id, previous.id, "linking must preserve old account IDs and domain data");
    } finally { globalThis.fetch = original; }
  });
}

test("existing Keycloak identity with a different mapping is never overwritten", async () => {
  const original = globalThis.fetch;
  const input = { email: "conflicting@example.com", password: "StrongDemo123!", name: "Conflict" };
  globalThis.fetch = async (url, options) => {
    assert.notEqual(options.method, "PUT", "provisioning must not reset an existing account");
    if (url.endsWith("/token")) return Response.json({ access_token: "unit-only-token" });
    if (options.method === "POST") return new Response(null, { status: 409 });
    return Response.json([{ email: input.email, attributes: { role: ["admin"], legacy_user_id: ["1"] } }]);
  };
  try {
    await assert.rejects(registerLinkedAccount("customer", input), /another account/);
    const state = getDb().prepare("SELECT state FROM identity_provisioning WHERE email=?").get(input.email);
    assert.equal(state.state, "pending");
  } finally { globalThis.fetch = original; }
});
