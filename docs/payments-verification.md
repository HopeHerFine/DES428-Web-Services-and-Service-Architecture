# Payments verification

- Local Wallet recovery rehearsal: stopped only `payments`. Wallet showed a server-side error (digest `3734464984`). After restart, Payments became healthy and Wallet displayed ฿0.00 balance and commission with no transactions. Repeat the rehearsal with this change to verify the temporary-unavailability message and retry link.
- Local observability: Prometheus scrape health was 1, Wallet traffic peaked near 0.6 requests/s and p95 was around 11–15 ms during the refresh burst. Jaeger showed one Wallet trace with 9 monolith spans and 6 Payments spans.
- Automated ownership and race coverage is in `services/payments/tests/test_payments.py`. It checks cross-customer access returns 403, eight concurrent settlements create one charge and one payout credit, and cancellation racing settlement leaves zero balance after compensation. Run the Payments PostgreSQL CI job for the race cases.
