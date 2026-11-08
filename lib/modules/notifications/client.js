import { config } from "../../config.js";
import { AppError } from "../../errors.js";
import { resilientFetch } from "../../http/retry.js";
import { context, propagation, trace, SpanKind, SpanStatusCode } from "@opentelemetry/api";

export async function remoteNotifications(token, suffix = "", method = "GET", requestId, incomingTrace) {
  if (!token) throw new AppError(401, "Sign in to view notifications");
  const parent = incomingTrace ? propagation.extract(context.active(), incomingTrace) : context.active();
  return trace.getTracer("homeservice").startActiveSpan(`notifications.${method}`,
    { kind: SpanKind.CLIENT, attributes: { "server.address": "notifications", "http.request.method": method } }, parent, async span => {
  try {
  const headers = { Authorization: `Bearer ${token}` };
  propagation.inject(context.active(), headers);
  if (requestId) headers["X-Request-Id"] = requestId;
  let response;
  try {
    response = await resilientFetch(`${config.notificationsUrl}${suffix}`, {
      method, headers, cache: "no-store",
    }, { timeoutMs: config.notificationsTimeoutMs });
  } catch { throw new AppError(503, "Notifications are temporarily unavailable. Please try again."); }
  if (!response.ok) throw new AppError(response.status, response.status === 401 ?
    "Sign in again to view notifications" : "Unable to access this notification");
  span.setAttribute("http.response.status_code", response.status);
  return await response.json();
  } catch (error) { span.setStatus({ code: SpanStatusCode.ERROR }); throw error; }
  finally { span.end(); }
  });
}
