import { config } from "../../config.js";
import { AppError } from "../../errors.js";
import { resilientFetch } from "../../http/retry.js";
import { context, propagation } from "@opentelemetry/api";

export function paymentToken(req) {
  const header = req.headers.get("authorization");
  if (header?.startsWith("Bearer ")) return header.slice(7);
  const raw = req.headers.get("cookie") || "";
  const match = raw.match(/(?:^|;\s*)notifications_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

export async function remotePayments(token, suffix, { method = "GET", body, key } = {}) {
  if (!token) throw new AppError(401, "Sign in with Keycloak to use payments");
  const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  propagation.inject(context.active(), headers);
  if (key) headers["Idempotency-Key"] = key;
  let response;
  try {
    response = await resilientFetch(`${config.paymentsUrl}${suffix}`, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store",
    }, { timeoutMs: 1500 });
  } catch { throw new AppError(503, "Payments are temporarily unavailable. Retry with the same payment key."); }
  if (!response.ok) {
    const message = response.status === 409 ? "Payment is not ready or the booking cannot be paid. Please retry shortly." :
      response.status === 401 ? "Sign in again with Keycloak to use payments" : "Unable to access this payment";
    throw new AppError(response.status, message);
  }
  return response.json();
}
