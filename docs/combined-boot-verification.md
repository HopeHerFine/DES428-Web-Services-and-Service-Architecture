# Combined startup verification

From a fresh checkout, run `docker compose up` to start the demo project with Notifications and Payments. For an existing released Payments migration, use `start-payments.ps1` to select the retained database.

The team rehearsed a clean source copy with fresh volumes and verified Notifications through the gateway and the refund Saga. Run `check-offline-memory.ps1 -Combined` on Windows to reproduce the offline rehearsal. It prepares images online, then starts the disposable project from cached images on an internal network. It runs the refund Saga and an authenticated Notifications workload before restoring the original containers.

The combined run passed with a sampled peak of 1,385,653,338 bytes (1.29 GiB) and a Docker Engine limit of 8,328,622,080 bytes (7.76 GiB). The sampler collected 48 observations, 20 during the workload. This is the maximum sampled container usage, excluding cache, rather than a continuous peak measurement.
