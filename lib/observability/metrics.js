import client from "prom-client";
const KEY = Symbol.for("homeservice.metrics");

if (!globalThis[KEY]) {
  const registry = new client.Registry();
  registry.setDefaultLabels({ service: "monolith" });
  client.collectDefaultMetrics({ register: registry });
  const requests = new client.Counter({ name: "http_requests_total", help: "Completed API requests",
    labelNames: ["method", "route", "status"], registers: [registry] });
  const duration = new client.Histogram({ name: "http_request_duration_seconds", help: "API response duration",
    labelNames: ["method", "route"], buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10], registers: [registry] });
  globalThis[KEY] = { registry, requests, duration };
}
export const metrics = globalThis[KEY];
export const routeLabel = path => path.replace(/\/\d+(?=\/|$)/g, "/:id");
