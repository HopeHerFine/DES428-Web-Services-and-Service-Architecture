export const runtime = "nodejs";
export const dynamic = "force-dynamic";

import { handle } from "#lib/http/handle.js";
import { json } from "#lib/http/respond.js";
import { getAuth, clearCookie } from "#lib/http/auth.js";
import { ACCESS_COOKIE, STATE_COOKIE, makeCookie } from "#lib/http/oidc.js";

export const POST = handle(async (req) => {
  getAuth(req); // any authenticated user
  const response = json({ ok: true });
  response.headers.append("Set-Cookie", clearCookie());
  response.headers.append("Set-Cookie", makeCookie(ACCESS_COOKIE, "", 0));
  response.headers.append("Set-Cookie", makeCookie(STATE_COOKIE, "", 0, "/api/oidc"));
  return response;
});
