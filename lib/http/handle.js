// The single wrapper every route handler is built with. It derives a request id, runs the handler,
// stamps X-Request-Id on whatever response comes back, and funnels any thrown error through
// toResponse so status + body + logging stay uniform. This is the App Router analogue of Ride's
// requestId + errorHandler middleware pair.
import { requestId } from "./requestId.js";
import { toResponse } from "./respond.js";
import { context, propagation, trace, SpanKind, SpanStatusCode } from "@opentelemetry/api";
import { metrics, routeLabel } from "../observability/metrics.js";
import { logger } from "../logger.js";

export function handle(fn) {
  return async (req, ctx = {}) => {
    const id = requestId(req);
    const path = routeLabel(new URL(req.url).pathname);
    const parent = propagation.extract(context.active(), Object.fromEntries(req.headers));
    return trace.getTracer("homeservice").startActiveSpan(`${req.method} ${path}`,
      { kind: SpanKind.SERVER, attributes: { "http.request.method": req.method, "http.route": path } }, parent, async span => {
    const started = performance.now();
    let status = 500;
    try {
      const res = await fn(req, ctx, id);
      status = res.status;
      if (res && res.headers && !res.headers.get("X-Request-Id")) {
        res.headers.set("X-Request-Id", id);
      }
      return res;
    } catch (err) {
      const res = toResponse(err, id);
      status = res.status;
      if (status >= 500) span.setStatus({ code: SpanStatusCode.ERROR });
      return res;
    } finally {
      span.setAttribute("http.response.status_code", status);
      const seconds = (performance.now() - started) / 1000;
      metrics.requests.inc({ method: req.method, route: path, status: String(status) });
      metrics.duration.observe({ method: req.method, route: path }, seconds);
      const traceId = span.spanContext().traceId;
      logger.info({ correlation_id: id, trace_id: traceId, method: req.method, route: path,
        status, duration_ms: Math.round(seconds * 1000) }, "request completed");
      span.end();
    }
    });
  };
}
