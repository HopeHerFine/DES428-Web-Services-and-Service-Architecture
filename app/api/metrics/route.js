export const runtime = "nodejs";
export const dynamic = "force-dynamic";
import { metrics } from "#lib/observability/metrics.js";

export async function GET() {
  return new Response(await metrics.registry.metrics(), { headers: { "Content-Type": metrics.registry.contentType } });
}
