import { config } from "../config.js";
import { AppError, ConflictError } from "../errors.js";
import { getDb } from "../db/index.js";
import * as identity from "../modules/identity/service.js";
import bcrypt from "bcryptjs";
import { logger } from "../logger.js";

function unavailable(stage, upstreamStatus, message) {
  logger.warn({ stage, upstreamStatus }, "Keycloak account provisioning unavailable");
  return new AppError(503, message);
}

async function call(url, options = {}) {
  try { return await fetch(url, { ...options, cache: "no-store", signal: AbortSignal.timeout(10000) }); }
  catch { throw new AppError(503, "Sign-up is temporarily unavailable. Retry with the same email and password."); }
}

export async function provisionAccount(role, account, password) {
  if (!config.provisionerSecret) throw unavailable("missing_provisioner_secret", null, "Account registration is not ready yet");
  const auth = await call(`${config.oidcInternalBase}/protocol/openid-connect/token`, {
    method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "client_credentials", client_id: "homeservice-provisioner",
      client_secret: config.provisionerSecret }),
  });
  if (!auth.ok) throw unavailable("client_authentication", auth.status, "Account registration is not ready yet");
  const bearer = (await auth.json()).access_token;
  const base = config.oidcInternalBase.replace(/\/realms\/[^/]+$/, "/admin/realms/homeservice");
  const headers = { Authorization: `Bearer ${bearer}`, "content-type": "application/json" };
  const response = await call(`${base}/users`, { method: "POST", headers, body: JSON.stringify({
    username: account.email, email: account.email, enabled: true, emailVerified: false,
    firstName: account.name || "Homeservice", lastName: "User", requiredActions: [],
    attributes: { role: [role], legacy_user_id: [String(account.id)] },
    credentials: [{ type: "password", value: password, temporary: false }],
  }) });
  if (response.status === 409) {
    // An earlier attempt may have succeeded remotely before its reply was lost.
    // Never reset or take over an existing user's password or account mapping.
    const found = await call(`${base}/users?exact=true&username=${encodeURIComponent(account.email)}`, { headers });
    if (!found.ok) throw new AppError(503, "Unable to confirm account registration");
    const users = await found.json();
    const user = users.length === 1 ? users[0] : null;
    if (!user || user.email?.toLowerCase() !== account.email.toLowerCase() ||
        user.attributes?.role?.[0] !== role || user.attributes?.legacy_user_id?.[0] !== String(account.id)) {
      throw new ConflictError("Email is already linked to another account");
    }
  } else if (response.status === 400) {
    throw new AppError(400, "Please check your name and password requirements, then retry sign-up.");
  } else if (!response.ok) {
    throw unavailable("create_keycloak_user", response.status, "Unable to finish sign-up. Retry with the same email and password.");
  }
}

export async function registerLinkedAccount(role, input) {
  if (!["customer", "provider"].includes(role)) throw new AppError(400, "Invalid registration role");
  if (!config.externalNotifications) return role === "customer" ? identity.registerCustomer(input) : identity.registerProvider(input);
  const db = getDb();
  const email = input.email.toLowerCase();
  const table = role === "customer" ? "customers" : "providers";
  let account;
  db.transaction(() => {
    const existing = db.prepare(`SELECT * FROM ${table} WHERE lower(email)=?`).get(email);
    if (existing) {
      const pending = db.prepare("SELECT state FROM identity_provisioning WHERE role=? AND user_id=?").get(role, existing.id);
      if (pending?.state === "active" || !bcrypt.compareSync(input.password, existing.password_hash)) {
        throw new ConflictError("Email is already registered");
      }
      if (!pending) db.prepare("INSERT INTO identity_provisioning(role,user_id,email,state) VALUES(?,?,?,'pending')").run(role, existing.id, existing.email);
      account = { id: existing.id, email: existing.email, name: existing.name };
    } else {
      const used = ["customers", "providers", "admins"].some(name => db.prepare(`SELECT 1 FROM ${name} WHERE lower(email)=?`).get(email));
      if (used) throw new ConflictError("Email is already registered for another role");
      account = role === "customer" ? identity.registerCustomer({ ...input, email }) : identity.registerProvider({ ...input, email });
      db.prepare("INSERT INTO identity_provisioning(role,user_id,email,state) VALUES(?,?,?,'pending')").run(role, account.id, email);
    }
  })();
  await provisionAccount(role, account, input.password);
  db.prepare("UPDATE identity_provisioning SET state='active' WHERE role=? AND user_id=?").run(role, account.id);
  return account;
}
