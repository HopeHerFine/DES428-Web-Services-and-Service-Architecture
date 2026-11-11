"""Verify deployed scrapes, provisioned dashboard and one real cross-service trace.

Run on the host with GATEWAY_CONNECT_HOST=127.0.0.1 and GATEWAY_CONNECT_PORT=8080.
No tokens, cookies or passwords are printed or saved.
"""
import json
import os
import time
from uuid import uuid4
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from .smoke_gateway import browser_login, ORIGIN


def fetch(base, path):
    with urlopen(base + path, timeout=15) as response:
        return json.load(response)


def main():
    prometheus = os.getenv("PROMETHEUS_BASE", "http://prometheus:9090")
    jaeger = os.getenv("JAEGER_BASE", "http://jaeger:16686")
    grafana = os.getenv("GRAFANA_BASE", "http://grafana:3000")
    client = browser_login("sparkle@example.com")
    trace_id, parent_id = uuid4().hex, uuid4().hex[:16]
    with client.open(Request(ORIGIN + "/provider/wallet", headers={
        "traceparent": f"00-{trace_id}-{parent_id}-01", "X-Request-Id": "observe-" + trace_id,
    }), timeout=30) as response:
        page = response.read().decode()
        assert response.status == 200 and "temporarily unavailable" not in page
    deadline = time.monotonic() + 60
    services, linked, jobs = set(), False, set()
    while time.monotonic() < deadline:
        targets = fetch(prometheus, "/api/v1/targets")["data"]["activeTargets"]
        jobs = {target["labels"]["job"] for target in targets if target["health"] == "up"}
        try:
            traces = fetch(jaeger, "/api/traces/" + trace_id).get("data") or []
        except HTTPError as error:
            if error.code != 404:
                raise
            traces = []
        if traces:
            item = traces[0]
            services = {process["serviceName"] for process in item["processes"].values()}
            spans = {span["spanID"]: span for span in item["spans"]}
            linked = any(item["processes"][span["processID"]]["serviceName"] == "payments" and
                any(ref["spanID"] in spans and item["processes"][spans[ref["spanID"]]["processID"]]["serviceName"] == "monolith"
                    for ref in span.get("references", [])) for span in spans.values())
        if {"payments", "monolith"} <= jobs and linked:
            break
        time.sleep(2)
    assert {"payments", "monolith"} <= jobs, f"Missing healthy scrapes: {jobs}"
    assert {"payments", "monolith"} <= services and linked, "Cross-service parent/child trace missing"
    dashboard = fetch(grafana, "/api/dashboards/uid/payments")["dashboard"]
    assert len(dashboard["panels"]) >= 4
    print(json.dumps({"result": "PASS", "probe": "payments-observability", "scrape_jobs": sorted(jobs),
        "trace_id": trace_id, "trace_services": sorted(services), "cross_service_parent_child": linked,
        "dashboard_uid": dashboard["uid"]}))


if __name__ == "__main__":
    main()
