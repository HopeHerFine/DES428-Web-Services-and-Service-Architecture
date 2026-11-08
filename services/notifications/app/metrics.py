from prometheus_client import Counter, Histogram

REQUESTS = Counter("http_requests_total", "Completed API requests", ["service", "method", "route", "status"])
DURATION = Histogram("http_request_duration_seconds", "API response duration", ["service", "method", "route"],
                     buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10])
EVENTS = Counter("notification_events_total", "Consumed domain events", ["event_type", "result"])
