import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { config } from "../../config.js";
import { remotePayments } from "./client.js";
import { getWallet } from "./service.js";

export async function ownWallet(providerId, returnTo) {
  if (!config.externalPayments) return getWallet(providerId);
  const token = cookies().get("notifications_token")?.value;
  if (!token) redirect(`/api/oidc/login?returnTo=${encodeURIComponent(returnTo)}`);
  try { return await remotePayments(token, "/wallet"); }
  catch (error) {
    if (error.statusCode === 401 || error.status === 401) {
      redirect(`/api/oidc/login?returnTo=${encodeURIComponent(returnTo)}`);
    }
    // Null means the balance is unavailable. Zero remains a valid balance.
    if (error.statusCode >= 500) return null;
    throw error;
  }
}
