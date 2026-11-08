export const runtime = "nodejs";
export const dynamic = "force-dynamic";

import { handle } from "#lib/http/handle.js";
import { json } from "#lib/http/respond.js";
import { getAuth } from "#lib/http/auth.js";
import * as payments from "#lib/modules/payments/service.js";
import { config } from "#lib/config.js";
import { paymentToken, remotePayments } from "#lib/modules/payments/client.js";

export const GET = handle(async (req) => {
  if (config.externalPayments) return json(await remotePayments(paymentToken(req), "/wallet"));
  const auth = getAuth(req, "provider");
  return json(payments.getWallet(auth.sub));
});
