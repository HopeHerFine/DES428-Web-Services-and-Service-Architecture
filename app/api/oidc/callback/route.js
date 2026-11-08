export const runtime = "nodejs";
export const dynamic = "force-dynamic";
import { cookies } from "next/headers";
import { handle } from "#lib/http/handle.js";
import { verifyState, exchangeCode, makeCookie, STATE_COOKIE, ACCESS_COOKIE, safeReturnTo } from "#lib/http/oidc.js";
import { signToken, tokenCookie } from "#lib/http/auth.js";
import { getMe } from "#lib/modules/identity/service.js";
import { UnauthorizedError } from "#lib/errors.js";
import { config } from "#lib/config.js";

export const GET = handle(async (req) => {
  const url = new URL(req.url);
  const state = verifyState(cookies().get(STATE_COOKIE)?.value, url.searchParams.get("state"));
  if (!url.searchParams.get("code")) throw new UnauthorizedError("Sign-in cancelled or unsuccessful");
  const { identity, tokens } = await exchangeCode(url.searchParams.get("code"), state);
  const id = Number(identity.legacy_user_id);
  if (!Number.isSafeInteger(id) || id <= 0 || !["customer", "provider", "admin"].includes(identity.role)) {
    throw new UnauthorizedError("Account is not linked to Homeservice");
  }
  const account = getMe({ role: identity.role, sub: id });
  if (account.email.toLowerCase() !== identity.email?.toLowerCase()) {
    throw new UnauthorizedError("Account mapping does not match");
  }
  const ttl = Math.max(1, Math.min(Number(tokens.expires_in) || 300, 3600));
  const session = signToken({ sub: id, role: identity.role, email: account.email });
  const response = new Response(null, { status: 302, headers: {
    Location: `${config.publicOrigin}${safeReturnTo(state.returnTo)}`, "Cache-Control": "no-store",
  } });
  response.headers.append("Set-Cookie", tokenCookie(session));
  response.headers.append("Set-Cookie", makeCookie(ACCESS_COOKIE, tokens.access_token, ttl));
  response.headers.append("Set-Cookie", makeCookie(STATE_COOKIE, "", 0, "/api/oidc"));
  // Refresh tokens stay out of the browser; sign in again after access token expiry.
  return response;
});
