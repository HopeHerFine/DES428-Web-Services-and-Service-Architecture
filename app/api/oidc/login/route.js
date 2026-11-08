export const runtime = "nodejs";
export const dynamic = "force-dynamic";
import { beginLogin } from "#lib/http/oidc.js";
import { config } from "#lib/config.js";

export async function GET(req) {
  if (!config.externalNotifications) return Response.redirect(new URL("/login", req.url));
  const login = beginLogin(new URL(req.url).searchParams.get("returnTo"));
  return new Response(null, { status: 302, headers: {
    Location: login.url, "Set-Cookie": login.cookie, "Cache-Control": "no-store",
  } });
}
