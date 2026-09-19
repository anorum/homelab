# Certificate monitoring

Alex approved existing Prometheus alerts on 2026-09-19, within the session's delegated deployment scope.

Use node-exporter's existing textfile collector instead of introducing another exporter or pushing metrics from the renewal protocol.
Systemd runs a separate status publisher after every renewal service attempt, including failures and timeouts.
Publication failure does not change renewal's exit status; stale or absent metrics catch a broken publisher.

## Interfaces and scope

- `telemetry/certificate-status.sh` reads the existing certificate paths and systemd `SERVICE_RESULT`; it atomically publishes `/var/lib/telemetry/metrics/certificate.prom` as mode `0644`.
- Gauges expose check completion time, check success, and expiry timestamps with fixed `certificate=device|intermediate|root` labels.
  Unreadable certificates yield expiry zero and unsuccessful status.
- Node-exporter reads that public directory through its existing read-only host mount.
  Both nodes need the directory; only the enrolled worker writes status.
- Prometheus rules cover failure for five minutes, status older than two hours or missing for ten minutes, device expiry at 21/7 days, and CA expiry at 90/30 days.
  Missing-status detection names the enrolled worker's existing scrape endpoint, independent of the status file.
- Use existing Alertmanager routes and receivers.
  Keep private identity files mode `0600` inside their `0700` directory.
- No new dependencies, S3 changes, identity rotation, or changes to renewal validation.

## Implementation and verification

- [x] Test status publication using disposable real certificates: success, failure/timeout, unreadable certificate, replacement, permissions, and failed publication preserving previous output.
- [x] Add the publisher and systemd post-stop hook, then node-exporter configuration and Prometheus rules.
- [x] Use promtool rule tests for normal, warning/critical expiry, failure/recovery, stale and missing status.
- [x] Verify installed systemd integration on the Pi, including a failed service and recovery.
- [x] Simplify and obtain fresh-context standards/spec review; run secret scan and PR CI.
- [x] Deploy and verify live metrics, healthy rule evaluation, and ArgoCD synchronization.
  Synthetic alert conditions stay in offline tests to avoid unnecessary notifications.

## Verification evidence

On 2026-09-19, all four status acceptance tests passed on the Pi in 4.859 seconds using disposable certificates.
The deployed Prometheus image's `promtool` binary passed all 14 rule scenarios on the master host.
The Helm 82.10.1 render preserves existing filesystem exclusions and adds the textfile directory.
`systemd-analyze verify --man=no` passed for the installed service.
An isolated service with the same post-stop hook published unsuccessful status after both `exit-code` and `timeout` failures.
The real renewal service then restored success; the normal hourly timer remained active.
UID `nobody` could read the metrics, while identity-directory mode remained `0700` and private-key mode `0600`.
`gitleaks dir . --redact --no-banner` found no leaks.

PR [#20](https://github.com/anorum/homelab/pull/20) merged after GitGuardian, secret scan, and SOPS encryption checks passed.
Fresh-context spec and standards reviews and the simplification pass found no issues.
After deployment, node-exporter exposed all five samples and Prometheus ingested `telemetry_certificate_check_success=1`.
Both node-exporters reported `node_textfile_scrape_error=0`.
All four live alert rules evaluated with `health=ok`, `state=inactive`, and no errors.
ArgoCD reported `Synced`, `Healthy`, and operation `Succeeded` at revision `e5e6edb6ce7549423a2873ff0d0bb13722bb2818`.
No synthetic notification was sent to Discord.
