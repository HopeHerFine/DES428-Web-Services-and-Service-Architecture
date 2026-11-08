# Offline cold boot and memory rehearsal

This rehearsal measures the running Notifications increment. It does not establish
the memory requirement for the future second service and Saga.

## Run on the Docker host

Start Docker Desktop with Linux containers. Configure Docker/WSL to provide no more
than 8 GiB to the Engine. The script checks Engine MemTotal and stops before changing
containers if it exceeds that limit. Do not guess a RAM number from the configuration.

From the source repository root, run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\check-offline-memory.ps1
```

The rehearsal has two explicit phases:

1. Online preparation: copy a clean set of source files into the ignored
   `runtime/offline/` directory, validate the source configuration, pull the tool images,
   and build two application images. Existing application credentials are not copied.
2. Offline execution: temporarily stop the regular stack without deleting its data,
   then start the prepared stack with fresh volumes. Its generated Compose file has
   no build directives, all pull policies are `never`, and its only network is internal.
   Containers cannot access the internet. Keycloak configuration runs automatically.
   The canonical bootstrap generates settings inside its own fresh test volume.

Boot uses this single command inside the prepared directory (the script adds wait
options so that it can assert readiness):

```powershell
docker compose up
```

The script checks RabbitMQ delivery, the monolith outbox, real Keycloak browser login,
registration, traces and dashboard targets. It checks blocked outbound connections
and runs two authenticated clients doing inbox reads, idempotent read updates and
server-rendered page reads for 60 seconds. Duration can be changed with
`-ObserveSeconds 60` (10..180).

Containers have explicit memory limits totaling less than 8 GiB, with swap disabled
for each container. A hidden local process samples actual Docker stats from cold boot
through the workload. Any functional failure, sampler failure or OOM prevents PASS.
Finally, only the fresh test project's volumes are deleted and the original running
stack is restored. Run while teammates are not using the local website.

## Recorded Docker-host result

The owner completed the rehearsal on 2026-11-09 03:45 Bangkok time.
The sanitized, versioned result is [offline-memory-result.json](offline-memory-result.json).

| Measurement | Actual result |
|---|---:|
| Engine memory budget | 7.76 GiB |
| Maximum sampled aggregate container usage | 1.13 GiB |
| Valid samples / samples during workload | 45 / 19 |
| Discarded incomplete polling attempts | 3 |
| Authenticated clients / workload duration | 2 / 60 seconds |
| Successful requests / read updates | 1050 / 524 |

Fresh-volume offline boot, blocked container egress and original-stack restoration
passed. No images were pulled or built during the offline execution phase. This is
an observed result for this workload, not a capacity claim for arbitrary traffic.

## Evidence and its limits

Only a successful real run writes:

- `docs/evidence/offline-memory-latest.json`: allocated Engine memory, maximum
  sampled aggregate container usage, sample count and workload duration.
- `docs/evidence/offline-memory-samples.json`: per-container measurements over time.

Docker CLI memory usage excludes cache on Linux. The reported maximum is the maximum
of the samples, not a continuously measured instantaneous peak, and does not include
all VM/kernel overhead. Engine MemTotal records the actual VM budget under which the
functional checks completed. Build-time memory is outside the offline runtime window.

Raw samples are saved as `memory-samples.jsonl` in the test directory while running.
Incomplete Docker polls are discarded and counted, not replaced with zero. Sampler
diagnostics remain in `memory-sampling-errors.jsonl` and `memory-sampler.stderr.log`.
A passing report requires samples during the workload and near its end; valid boot
samples alone are insufficient. The sampler is a hidden local process, independent
of PowerShell remoting/background-job support.

This tests a **prepared cached-image offline boot**. A never-prepared computer cannot
download images without internet. The generated demo directory contains resolved
credentials, so do not commit or share that directory. Prepared images remain cached
locally for reuse. No image registry account or cloud runtime is needed.

The canonical root now also starts directly with docker compose up and scoped
volume initialization; see [canonical boot](canonical-boot.md). The measurement above
was recorded before that packaging change. Run this rehearsal again for the final
submission's exact combined system rather than reusing it as a new measurement.

The measured result above comes from the owner's Docker host. CI tests the source,
sampler regression cases and image builds; it does not reproduce this laptop RAM run.

References: [internal networks](https://docs.docker.com/reference/compose-file/networks/),
[Docker stats cache accounting](https://docs.docker.com/reference/cli/docker/container/stats/).
