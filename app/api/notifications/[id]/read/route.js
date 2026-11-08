export const runtime = "nodejs";
export const dynamic = "force-dynamic";

import { handle } from "#lib/http/handle.js";
import { json } from "#lib/http/respond.js";
import { getAuth } from "#lib/http/auth.js";
import { parseId } from "#lib/http/validate.js";
import * as notifications from "#lib/modules/notifications/service.js";
import { config } from "#lib/config.js";
import { remoteNotifications } from "#lib/modules/notifications/client.js";
import { ACCESS_COOKIE } from "#lib/http/oidc.js";
import { cookies } from "next/headers";

export const POST = handle(async (req, { params }) => {
  if (config.externalNotifications) return json(await remoteNotifications(
    req.headers.get("authorization")?.replace(/^Bearer /, "") || cookies().get(ACCESS_COOKIE)?.value,
    `/${parseId(params.id, "notification id")}/read`, "POST",
  ));
  const auth = getAuth(req);
  return json(notifications.markRead(parseId(params.id, "notification id"), auth));
});
