import { randomBytes, createHash, createPublicKey } from "node:crypto";
import jwt from "jsonwebtoken";
import { config } from "../config.js";
import { UnauthorizedError } from "../errors.js";

export const CLIENT_ID = "homeservice-web";
export const ACCESS_COOKIE = "notifications_token";
export const STATE_COOKIE = "homeservice_oidc";
export const callbackUrl = () => `${config.publicOrigin}/api/oidc/callback`;

export function safeReturnTo(value) {
  return typeof value === "string" && value.startsWith("/") && !value.startsWith("//") &&
    !/[\\\r\n]/.test(value) ? value : "/notifications";
}

export function makeCookie(name, value, age, path = "/") {
  const secure = config.publicOrigin.startsWith("https:") ? "; Secure" : "";
  return `${name}=${encodeURIComponent(value)}; Path=${path}; HttpOnly; SameSite=Lax; Max-Age=${age}${secure}`;
}

export function beginLogin(returnTo) {
  const state = randomBytes(24).toString("base64url");
  const nonce = randomBytes(24).toString("base64url");
  const verifier = randomBytes(32).toString("base64url");
  const stored = jwt.sign({ state, nonce, verifier, returnTo: safeReturnTo(returnTo) },
    config.jwtSecret, { algorithm: "HS256", expiresIn: "5m", audience: "oidc-state" });
  const url = new URL(`${config.oidcIssuer}/protocol/openid-connect/auth`);
  const params = { client_id: CLIENT_ID, response_type: "code", scope: "openid email profile",
    prompt: "login",
    redirect_uri: callbackUrl(), state, nonce, code_challenge_method: "S256",
    code_challenge: createHash("sha256").update(verifier).digest("base64url") };
  for (const [key, value] of Object.entries(params)) url.searchParams.set(key, value);
  return { url: url.toString(), cookie: makeCookie(STATE_COOKIE, stored, 300, "/api/oidc") };
}

export function verifyState(stored, state) {
  try {
    const parsed = jwt.verify(stored, config.jwtSecret, { algorithms: ["HS256"], audience: "oidc-state" });
    if (!state || state !== parsed.state) throw new Error("state mismatch");
    return parsed;
  } catch { throw new UnauthorizedError("Login session expired. Please sign in again."); }
}

let keyCache;
export async function verifyKeycloakToken(token, audience) {
  const decoded = jwt.decode(token, { complete: true });
  if (!decoded || decoded.header.alg !== "RS256") throw new UnauthorizedError("Invalid identity token");
  if (!keyCache || keyCache.until < Date.now() || !keyCache.keys.some((key) => key.kid === decoded.header.kid)) {
    const response = await fetch(`${config.oidcInternalBase}/protocol/openid-connect/certs`, {
      cache: "no-store", signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error("Identity provider unavailable");
    keyCache = { keys: (await response.json()).keys, until: Date.now() + 60000 };
  }
  const jwk = keyCache.keys.find((key) => key.kid === decoded.header.kid);
  if (!jwk) throw new UnauthorizedError("Unknown identity signing key");
  try {
    const claims = jwt.verify(token, createPublicKey({ key: jwk, format: "jwk" }), {
      algorithms: ["RS256"], issuer: config.oidcIssuer, audience,
    });
    if (!claims.exp || !claims.sub) throw new Error("Required claims missing");
    return claims;
  } catch (error) {
    // JWT verification errors describe validation rules, not the raw token.
    // Keep these distinctions visible during local integration instead of
    // collapsing issuer/audience/signature problems into an unhelpful 401.
    throw new UnauthorizedError(`Invalid or expired identity token: ${error.name}: ${error.message}`);
  }
}

export async function exchangeCode(code, state) {
  const response = await fetch(`${config.oidcInternalBase}/protocol/openid-connect/token`, {
    method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "authorization_code", client_id: CLIENT_ID,
      code, code_verifier: state.verifier, redirect_uri: callbackUrl() }),
    cache: "no-store", signal: AbortSignal.timeout(10000),
  });
  if (!response.ok) throw new UnauthorizedError("Sign-in could not be completed. Please try again.");
  const tokens = await response.json();
  const identity = await verifyKeycloakToken(tokens.id_token, CLIENT_ID);
  const access = await verifyKeycloakToken(tokens.access_token, "notifications");
  if (identity.nonce !== state.nonce || access.sub !== identity.sub ||
      identity.role !== access.role || identity.legacy_user_id !== access.legacy_user_id) {
    throw new UnauthorizedError("Identity does not match login session");
  }
  return { identity, tokens };
}
