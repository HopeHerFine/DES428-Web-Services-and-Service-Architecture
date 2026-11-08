import { config } from "../../config.js";
import { AppError } from "../../errors.js";

export async function remoteNotifications(token, suffix = "", method = "GET", requestId) {
  if (!token) throw new AppError(401, "Sign in to view notifications");
  const headers = { Authorization: `Bearer ${token}` };
  if (requestId) headers["X-Request-Id"] = requestId;
  let response;
  try {
    response = await fetch(`${config.notificationsUrl}${suffix}`, {
      method, headers, cache: "no-store", signal: AbortSignal.timeout(5000),
    });
  } catch { throw new AppError(503, "Notifications are temporarily unavailable. Please try again."); }
  if (!response.ok) throw new AppError(response.status, response.status === 401 ?
    "Sign in again to view notifications" : "Unable to access this notification");
  return response.json();
}
