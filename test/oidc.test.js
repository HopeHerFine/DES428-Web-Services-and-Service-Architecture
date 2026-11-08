import { test } from "node:test";
import assert from "node:assert/strict";
import { generateKeyPairSync, createHash } from "node:crypto";
import jwt from "jsonwebtoken";
import { config } from "../lib/config.js";
import { beginLogin, verifyState, safeReturnTo, exchangeCode, verifyKeycloakToken } from "../lib/http/oidc.js";
import { remoteNotifications } from "../lib/modules/notifications/client.js";

test("OIDC protects redirects, state, PKCE, signatures, issuer, audience and nonce", async () => {
  assert.equal(safeReturnTo("//evil.test"), "/notifications");
  assert.equal(safeReturnTo("/\\evil.test"), "/notifications");
  assert.equal(safeReturnTo("/notifications"), "/notifications");
  const login = beginLogin("/notifications");
  const url = new URL(login.url);
  const stored = decodeURIComponent(login.cookie.split(";")[0].split("=")[1]);
  const state = verifyState(stored, url.searchParams.get("state"));
  assert.equal(url.searchParams.get("code_challenge_method"), "S256");
  assert.equal(url.searchParams.get("code_challenge"), createHash("sha256").update(state.verifier).digest("base64url"));
  assert.throws(() => verifyState(stored, "attacker-state"), /expired/);
  assert.throws(() => verifyState("forged", state.state), /expired/);
  const { publicKey, privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
  const jwk = { ...publicKey.export({ format: "jwk" }), kid: "oidc-test", alg: "RS256", use: "sig" };
  const base = { sub: "kc-1", role: "customer", legacy_user_id: "1", email: "nong@example.com", nonce: state.nonce };
  const sign = (audience, overrides = {}) => {
    const { iss = config.oidcIssuer, ...claims } = overrides;
    return jwt.sign({ ...base, ...claims }, privateKey,
      { algorithm: "RS256", keyid: jwk.kid, issuer: iss, audience, expiresIn: 300 });
  };
  const original = globalThis.fetch;
  let idToken = sign("homeservice-web");
  let accessToken = sign("notifications");
  globalThis.fetch = async (url, options) => {
    if (url.endsWith("/certs")) return Response.json({ keys: [jwk] });
    assert.equal(options.body.get("code_verifier"), state.verifier);
    assert.equal(options.body.get("grant_type"), "authorization_code");
    return Response.json({ id_token: idToken, access_token: accessToken, expires_in: 300 });
  };
  try {
    assert.equal((await exchangeCode("valid-code", state)).identity.sub, "kc-1");
    await assert.rejects(verifyKeycloakToken(sign("wrong-audience"), "notifications"), /Invalid/);
    await assert.rejects(verifyKeycloakToken(sign("notifications", { iss: "https://evil.test" }), "notifications"));
    await assert.rejects(verifyKeycloakToken(jwt.sign(base, "forged", { algorithm: "HS256" }), "notifications"), /Invalid/);
    idToken = sign("homeservice-web", { nonce: "wrong-nonce" });
    await assert.rejects(exchangeCode("valid-code", state), /does not match/);
    idToken = sign("homeservice-web");
    accessToken = sign("notifications", { legacy_user_id: "2" });
    await assert.rejects(exchangeCode("valid-code", state), /does not match/);
  } finally { globalThis.fetch = original; }
});

test("remote inbox forwards only the user token; never falls back to a local table", async () => {
  await assert.rejects(remoteNotifications(null), /Sign in/);
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    assert.equal(options.headers.Authorization, "Bearer user-token");
    assert.equal(options.cache, "no-store");
    return Response.json([{ id: 1, title: "Remote notification" }]);
  };
  try {
    assert.equal((await remoteNotifications("user-token"))[0].title, "Remote notification");
    globalThis.fetch = async () => new Response(null, { status: 401 });
    await assert.rejects(remoteNotifications("expired"), /Sign in again/);
    globalThis.fetch = async () => { throw new Error("connection refused"); };
    await assert.rejects(remoteNotifications("user-token"), /temporarily unavailable/);
  } finally { globalThis.fetch = original; }
});
