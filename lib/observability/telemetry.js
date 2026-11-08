const STARTED = Symbol.for("homeservice.telemetry.started");

export async function startTelemetry() {
  if (globalThis[STARTED] || !process.env.OTEL_EXPORTER_OTLP_ENDPOINT) return;
  globalThis[STARTED] = true;
  const { NodeSDK } = await import("@opentelemetry/sdk-node");
  const { OTLPTraceExporter } = await import("@opentelemetry/exporter-trace-otlp-http");
  const endpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT.replace(/\/$/, "");
  const sdk = new NodeSDK({ serviceName: "monolith",
    traceExporter: new OTLPTraceExporter({ url: `${endpoint}/v1/traces` }) });
  sdk.start();
  globalThis[STARTED] = sdk;
}
