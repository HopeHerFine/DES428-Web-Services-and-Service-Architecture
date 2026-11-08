export const dynamic = "force-dynamic";

import { redirect } from "next/navigation";
import { getSession } from "#lib/http/session.js";
import * as notifications from "#lib/modules/notifications/service.js";
import { ActionButton } from "../_ui/client.js";
import { cookies, headers } from "next/headers";
import { config } from "#lib/config.js";
import { remoteNotifications } from "#lib/modules/notifications/client.js";
import { ACCESS_COOKIE, verifyKeycloakToken } from "#lib/http/oidc.js";

export default async function NotificationsPage() {
  const session = getSession();
  if (!session) redirect(config.externalNotifications ? "/api/oidc/login" : "/login");
  let list;
  if (config.externalNotifications) {
    const token = cookies().get(ACCESS_COOKIE)?.value;
    if (!token) redirect("/api/oidc/login");
    let identity;
    try { identity = await verifyKeycloakToken(token, "notifications"); } catch { /* redirect below */ }
    if (!identity || identity.role !== session.role || String(identity.legacy_user_id) !== String(session.sub)) redirect("/api/oidc/login");
    let error;
    const incoming = headers();
    const traceHeaders = Object.fromEntries(["traceparent", "tracestate"].map(key => [key, incoming.get(key)]).filter(([,value]) => value));
    try { list = await remoteNotifications(token, "", "GET", incoming.get("x-request-id"), traceHeaders); } catch (err) { error = err; }
    if (error?.statusCode === 401) redirect("/api/oidc/login");
    if (error) return <div><h1>Notifications</h1><p role="alert">Notifications are temporarily unavailable. Please try again.</p></div>;
  } else list = notifications.listForUser({ sub: session.sub, role: session.role });

  return (
    <div>
      <h1>Notifications</h1>
      {list.length === 0 ? <p className="muted">Nothing here yet.</p> : (
        <ul className="plain">
          {list.map((n) => (
            <li key={n.id} style={{ opacity: n.read_at ? 0.55 : 1 }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div>
                  <strong>{n.title}</strong> <span className="muted small">· {n.type}</span>
                  <div className="small">{n.body}</div>
                </div>
                {!n.read_at ? <ActionButton url={`/api/notifications/${n.id}/read`} label="Mark read" className="secondary" /> : <span className="muted small">read</span>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
