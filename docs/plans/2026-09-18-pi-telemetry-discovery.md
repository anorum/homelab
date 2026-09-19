# Pi telemetry discovery plan

Status: approved by Alex and completed on 2026-09-18.
Verification and reproduction commands are recorded in [the telemetry runbook](../../telemetry/README.md#verified-result-2026-09-18).

## Goal and ownership

Inspect actual Pi telemetry through a local OpenTelemetry Collector before choosing the S3 representation or sizing the offline queue.
This project belongs in the homelab repository.
Explain the mechanics and recommend a design; Alex and the agent decide interfaces, data shapes, dependencies, and module boundaries together.
Prefer existing implementations and compare total ownership cost before proposing custom software.

## Established direction

- Collect on the device, independently of Kubernetes, and eventually upload to AWS S3.
- Use the Collector's native persistent exporter queue for a week of network disconnection, subject to measured capacity and tested retry behavior.
- Accept small gaps during application or Collector failures and duplicate delivery; measure loss and make downstream summaries duplicate-safe.
- Preserve individual collected samples and perform summarization in a separate job.
- Target roughly a week of raw data in S3, with longer-lived summaries; raw retention and local queue retention are separate policies.
- Inspect real records before fixing their representation or identity scheme.

The earlier Java sensor application and custom log-event shape are superseded as the starting proposal by existing metric collectors.
This discovery unit does not establish delivery or durability guarantees.

## Evidence

Read-only discovery identified swagman-2 as a Raspberry Pi 4 Model B running Debian 12 on aarch64.
The earlier homelab documentation describing this node as a Pi 5 is inaccurate.
The root device is an approximately 64 GB SD card; a prior inspection found about 19 GiB available, which must be rechecked before allocating a queue.
The separate USB hard drive is not selected for this experiment.

On 2026-09-18, an HTTP scrape of the existing local node_exporter returned:

```text
node_thermal_zone_temp{type="cpu-thermal",zone="0"} 55.017
```

The endpoint also returned two hardware-monitor temperature series with the same value.
Select only the thermal-zone series for the first experiment to avoid counting multiple representations of the temperature.
A subsequent sysfs read returned 54530 millidegrees Celsius; sequential samples can differ.
No service was changed during inspection.

## First implementation unit

Run a five-minute discovery experiment with temporary host processes on swagman-2.
Use a standalone node_exporter bound to an unused loopback port, proposed as 19100, so the experiment does not depend on the cluster-managed exporter or disturb its port 9100 service.
Run the Collector as a temporary host process, scraping every five seconds.
Leave permanent systemd deployment for a later unit.

### Interfaces and data

- Source: Linux thermal-zone readings through node_exporter's HTTP `/metrics` interface.
- Collection: Collector Prometheus receiver scrapes `127.0.0.1:19100`, retaining only `node_thermal_zone_temp` for type `cpu-thermal`, zone `0`.
- Output: Collector file exporter writes native OTLP JSON metric envelopes to a unique run directory under the Pi's temporary directory.
- Sample semantics: temperature gauge in Celsius with collection timestamp and source labels; no custom event UUID or log schema is introduced.
- Verification: inspect metric points inside envelopes rather than counting file lines; report timestamps, labels, values, record count, and serialized bytes.

### Dependencies and files

Use official Linux ARM64 node_exporter and OpenTelemetry Collector Contrib binaries, pinned to exact stable release versions with published checksums verified before execution.
Version selection is an implementation detail within these two approved dependencies; introduce no additional runtime or library without discussion.
Use shell tooling already on the hosts and an available JSON parser for inspection; stop to discuss if an additional dependency is necessary.

- `telemetry/README.md`: reproducible commands, pinned versions/checksums, observed results, and cleanup.
- `telemetry/collector-discovery.yaml`: the Prometheus receiver, metric selection, and local file exporter configuration.
- Temporary run directory: binaries, collected telemetry, and process output; keep these out of git.

### Steps and verification

- [x] Check available disk space and the proposed port, then obtain and verify the two binaries without system-wide installation.
- [x] Validate the Collector configuration using the pinned binary's validation command.
- [x] Start the dedicated node_exporter and verify that its selected temperature metric is present before starting collection.
- [x] Run the Collector for five minutes and stop it gracefully to flush output.
- [x] Verify that only the selected temperature series appears, with numeric Celsius values and increasing timestamps at approximately five-second intervals.
- [x] Report the actual sample count and any gaps; expect approximately 60 points, accounting explicitly for the startup and shutdown boundaries rather than asserting an exact count from wall-clock duration alone.
- [x] Compare a nearby source reading for unit and plausibility, without asserting equality between sequential measurements.
- [x] Measure uncompressed serialized bytes and bytes per sample; explicitly distinguish this from future S3 compression and persistent-queue disk usage.
- [x] Stop only the experiment's processes and verify that the existing exporter still responds on port 9100.

No unit tests are needed for a configuration-only discovery run; configuration validation and actual Pi-to-file collection are the verification surface.

## Excluded from this unit

AWS resources and authentication, S3 uploads, persistent queue configuration, outage/restart/power-loss tests, permanent services, custom Java code, CPU/memory expansion, summarization, deduplication implementation, and retention/deletion automation are outside this unit.
The resulting measurements inform the next short plan; adding those features requires their own agreed interfaces and verification.
