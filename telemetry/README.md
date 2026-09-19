# Pi telemetry discovery

Certificate enrollment and AWS authentication are described in [the certificate runbook](certificates.md) and [the Roles Anywhere runbook](roles-anywhere.md).

This experiment collects CPU temperature on the Pi through existing software.
It runs standalone host processes and writes local OTLP JSON for inspection.
The [approved plan](../docs/plans/2026-09-18-pi-telemetry-discovery.md) defines the scope and later S3 direction.

```text
Linux thermal zone
  -> node_exporter on 127.0.0.1:19100
  -> OpenTelemetry Collector, scraping every 5 seconds
  -> local metrics.jsonl
```

The Collector filters out other series, including automatically generated scrape-health metrics.
Its own metrics listener is disabled for this temporary experiment to avoid occupying another port.
Production pipeline monitoring will need a separate decision.
The output uses the native OTLP metric representation, without a custom event schema or Java producer.

## Device identity

`host.id` is `raspberrypi:<board-serial>`, read from `/sys/firmware/devicetree/base/serial-number` at startup.
The prefix distinguishes the identifier's source; it does not guarantee global uniqueness across an arbitrary fleet.
`host.name` is the current hostname, retained as a readable label rather than the identity used to connect history.
The setup commands refresh both values when starting a new experiment; changing the OS hostname does not update an already-running Collector's environment.
Renaming or reinstalling the OS preserves the board-derived ID; replacing the board changes it.
Queries that need continuity across renames should group by `host.id`, not the complete set of resource attributes.
This identifies the Pi's board, not a logical robot that might outlive a computer replacement.

## Dependencies

The experiment uses Linux ARM64 release binaries, Bash, curl, tar, sha256sum, timeout, and Python 3's standard library.
No Python packages or system-wide installations are required.

| Binary | Version | Archive SHA-256 |
| --- | --- | --- |
| node_exporter | 1.12.1 | `ad35b605f9954b9f1ffddf5ba054bdc5a98d790b9eae5291e1eeb83f1ecbd0e7` |
| otelcol-contrib | 0.161.0 | `cd5de93213a0dbb90e4998b3b9e4e15ed691ec635cf7cf4147f95799fb16b676` |

The node_exporter hash was checked against its [release checksum manifest](https://github.com/prometheus/node_exporter/releases/download/v1.12.1/sha256sums.txt).
The Collector hash was checked against the archive's `digest` in the [official release metadata](https://api.github.com/repos/open-telemetry/opentelemetry-collector-releases/releases/tags/v0.161.0).
Pinned versions make the experiment reproducible; component stability levels differ within the Collector distribution.

## Prepare on the Pi

Copy `collector-discovery.yaml` to the Pi and start a Bash session in the directory containing that file.
Run the following blocks in the same session.
Check that port 19100 is unused and that temporary storage has room for approximately 100 MB of compressed Collector binaries plus their larger extracted contents.
An existing listener on port 19100 must be resolved before proceeding.

```bash
df -h /tmp
ss -ltn 'sport = :19100'

set -euo pipefail
telemetry_run=$(mktemp -d /tmp/pi-telemetry.XXXXXX)
cp collector-discovery.yaml "$telemetry_run/"
cd "$telemetry_run"

curl -fL --max-time 180 -o node_exporter-1.12.1.linux-arm64.tar.gz \
  https://github.com/prometheus/node_exporter/releases/download/v1.12.1/node_exporter-1.12.1.linux-arm64.tar.gz
curl -fL --max-time 180 -o otelcol-contrib_0.161.0_linux_arm64.tar.gz \
  https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v0.161.0/otelcol-contrib_0.161.0_linux_arm64.tar.gz

sha256sum -c <<'CHECKSUMS'
ad35b605f9954b9f1ffddf5ba054bdc5a98d790b9eae5291e1eeb83f1ecbd0e7  node_exporter-1.12.1.linux-arm64.tar.gz
cd5de93213a0dbb90e4998b3b9e4e15ed691ec635cf7cf4147f95799fb16b676  otelcol-contrib_0.161.0_linux_arm64.tar.gz
CHECKSUMS

tar -xzf node_exporter-1.12.1.linux-arm64.tar.gz
tar -xzf otelcol-contrib_0.161.0_linux_arm64.tar.gz otelcol-contrib
telemetry_serial=$(tr -d '\000\n' < /sys/firmware/devicetree/base/serial-number)
[[ "$telemetry_serial" =~ ^[[:xdigit:]]{16}$ ]] || { printf 'Invalid Pi board serial\n' >&2; exit 1; }
export TELEMETRY_HOST_ID="raspberrypi:$telemetry_serial"
export TELEMETRY_HOST_NAME="$(hostname)"
export TELEMETRY_OUTPUT="$telemetry_run/metrics.jsonl"
./otelcol-contrib validate --config collector-discovery.yaml
```

Use a fresh directory for every run because the file exporter truncates its output when starting with this configuration.

## Capture five minutes

Run this block as one subshell so its exit trap stops only the exporter it starts.
The timeout sends SIGTERM to the Collector after 300 seconds, allowing a graceful flush; exit 124 is the expected scheduled stop.
Other exit statuses are failures and should be investigated in `collector.log`.

```bash
(
set -euo pipefail
./node_exporter-1.12.1.linux-arm64/node_exporter \
  --web.listen-address=127.0.0.1:19100 \
  --collector.disable-defaults --collector.thermal_zone \
  >node-exporter.log 2>&1 &
telemetry_node_pid=$!
trap 'kill -TERM "$telemetry_node_pid" 2>/dev/null || true; wait "$telemetry_node_pid" 2>/dev/null || true' EXIT

for telemetry_attempt in {1..20}; do
  if curl -fsS --max-time 2 http://127.0.0.1:19100/metrics >source-before.txt; then break; fi
  kill -0 "$telemetry_node_pid"
  sleep 0.5
done
grep '^node_thermal_zone_temp{type="cpu-thermal",zone="0"}' source-before.txt

python3 - <<'PY'
import json, time
from pathlib import Path
Path('timing.json').write_text(json.dumps({'start_ns': time.time_ns()}))
PY

telemetry_status=0
timeout --signal=TERM --kill-after=15s 300s \
  ./otelcol-contrib --config collector-discovery.yaml \
  >collector.log 2>&1 || telemetry_status=$?
test "$telemetry_status" -eq 124

python3 - <<'PY'
import json, time
from pathlib import Path
p = Path('timing.json')
timing = json.loads(p.read_text())
timing['stop_ns'] = time.time_ns()
p.write_text(json.dumps(timing))
PY

curl -fsS --max-time 5 http://127.0.0.1:19100/metrics >source-after.txt
cat /sys/class/thermal/thermal_zone0/temp >sysfs-after.txt
)
```

## Verify the actual records

Each line is an OTLP envelope, which can contain multiple metrics and points.
Count the nested points, not the lines.
This verification checks the selected series, source metadata, finite and plausible Celsius values, increasing timestamps, cadence, and startup/shutdown coverage.
The physical temperature range is only a sanity check for this Pi experiment.
The timing limits allow startup alignment and a small amount of scheduling jitter; a failure needs investigation rather than a wider tolerance chosen merely to pass.

```bash
python3 - <<'PY'
import json, math, os
from datetime import datetime, timezone
from pathlib import Path

path = Path('metrics.jsonl')
timing = json.loads(Path('timing.json').read_text())
expected_id = os.environ['TELEMETRY_HOST_ID']
expected_name = os.environ['TELEMETRY_HOST_NAME']
assert expected_id.startswith('raspberrypi:') and expected_name
points = []
for line in path.read_text().splitlines():
    for resource in json.loads(line)['resourceMetrics']:
        attrs = {a['key']: a['value'].get('stringValue')
                 for a in resource['resource']['attributes']}
        assert attrs['service.name'] == 'pi-thermal-discovery', attrs
        assert attrs['service.instance.id'] == '127.0.0.1:19100', attrs
        assert attrs['host.id'] == expected_id, 'Incorrect board identity'
        assert attrs['host.name'] == expected_name, 'Incorrect hostname label'
        for scope in resource['scopeMetrics']:
            for metric in scope['metrics']:
                assert metric['name'] == 'node_thermal_zone_temp', metric
                assert metric['description'] == 'Zone temperature in Celsius', metric
                for point in metric['gauge']['dataPoints']:
                    labels = {a['key']: a['value']['stringValue']
                              for a in point['attributes']}
                    assert labels == {'type': 'cpu-thermal', 'zone': '0'}, labels
                    value = point['asDouble']
                    assert math.isfinite(value) and -40 <= value <= 125, point
                    points.append((int(point['timeUnixNano']), value))

assert 57 <= len(points) <= 61, len(points)
gaps = [(b[0] - a[0]) / 1e9 for a, b in zip(points, points[1:])]
assert all(4.5 <= gap <= 5.5 for gap in gaps), gaps
startup = (points[0][0] - timing['start_ns']) / 1e9
tail = (timing['stop_ns'] - points[-1][0]) / 1e9
assert 0 <= startup <= 15, startup
assert 0 <= tail <= 7, tail
summary = {
    'samples': len(points),
    'first_utc': datetime.fromtimestamp(points[0][0] / 1e9, timezone.utc).isoformat(),
    'last_utc': datetime.fromtimestamp(points[-1][0] / 1e9, timezone.utc).isoformat(),
    'gap_seconds_min_max': [min(gaps), max(gaps)],
    'startup_seconds': startup,
    'tail_seconds': tail,
    'temperature_celsius_min_max': [min(v for _, v in points), max(v for _, v in points)],
    'bytes': path.stat().st_size,
    'bytes_per_sample': path.stat().st_size / len(points),
}
print(json.dumps(summary, indent=2))
Path('verification.json').write_text(json.dumps(summary, indent=2) + '\n')
PY

grep '^node_thermal_zone_temp' source-after.txt
cat sysfs-after.txt
tail -n 8 collector.log
ss -ltn 'sport = :19100'
curl -fsS --max-time 5 'http://127.0.0.1:9100/metrics?collect%5B%5D=thermal_zone' \
  | grep '^node_thermal_zone_temp'
```

The final source and sysfs values are separate measurements and need not be identical.
The sysfs value is millidegrees Celsius; divide by 1000 for comparison.
Confirm the Collector logged a completed shutdown and port 19100 has no listener.
The final port 9100 check applies to this homelab's existing monitoring service, not to a requirement of the standalone experiment.

Keep raw files and binaries in the temporary run directory, outside git.
After inspecting or copying any evidence you want to retain, remove that specific directory; neither process is configured to restart.

## What this establishes

The experiment tests device-local acquisition and the Prometheus-to-OTLP representation.
Uncompressed file size is not S3 object size, queue footprint, or a measurement of SD-card write amplification.
It does not test a week of buffering, S3 acknowledgments, process-failure recovery, or power-loss durability.

The observed source unit is described as Celsius, but the initial OTLP output does not contain an explicit metric `unit` field.
The resource processor adds board identity alongside the receiver's loopback service endpoint.
Explicit metric units still need a decision before S3 ingestion.

## Verified result: 2026-09-18

The experiment ran on swagman-2, confirmed as a Raspberry Pi 4 Model B with Debian 12 and aarch64 architecture.
Both archive checksums passed, and `otelcol-contrib validate --config collector-discovery.yaml` exited successfully.
The verification snippet at commit `d60eb9f` passed on the Pi and again against the copied evidence on the workstation.
This initial run predates the board-identity attributes; its byte measurements exclude their overhead.

| Measurement | Result |
| --- | --- |
| Collected temperature samples | 59 |
| First sample, UTC | 17:49:38.652 |
| Last sample, UTC | 17:54:28.652 |
| Interval range | 4.996 to 5.004 seconds |
| Delay from launch to first sample | 8.749 seconds |
| Delay from last sample to completed capture | 1.383 seconds |
| Temperature range | 51.608 to 55.504 degrees Celsius |
| Uncompressed OTLP JSON bytes | 47,073 |
| Bytes per sample, including envelope overhead | 797.85 |

The launch and shutdown boundaries account for 59 samples rather than 60; there were no missing five-second intervals within the recorded span.
The final source reading and subsequent sysfs reading both corresponded to 55.017 degrees Celsius.
The Collector logged `Shutdown complete.`, port 19100 had no listener afterward, and the original exporter on port 9100 still returned temperature.

Raw evidence is retained outside git at `/tmp/pi-telemetry.gDL6iv` on the Pi and `/private/tmp/pi-telemetry-evidence-20260918` on the workstation.
Both copies of `metrics.jsonl` have SHA-256 `abbfc38060d660f1cb5d834badc95f00777675707ba6d504c7132761587cd047`.
Downloaded binaries and archives were removed from the Pi after verification, leaving approximately 120 KiB of evidence there.
Temporary-directory evidence can expire; the measurements and reproduction procedure are recorded here permanently.

Fresh-context standards and plan-conformance reviews found no issues in the configuration or runbook.
The simplification pass found no additional abstractions to remove.

## Verified board identity: 2026-09-18

The updated configuration validated successfully with the same pinned Collector binary.
Two 20-second captures produced three temperature samples each, preserving the five-second cadence.
The first used the Pi's current hostname; the second set `TELEMETRY_HOST_NAME=identity-test-renamed` and restarted the Collector.
Every resource in both captures had the same `host.id`, checked independently against the board's serial-number file, and the expected distinct `host.name`.
This verifies independence from the hostname label and continuity across Collector restarts; it did not rename the OS or reinstall it.

To repeat this check, follow the capture procedure twice with fresh output paths and a 20-second timeout, changing only `TELEMETRY_HOST_NAME` before the second Collector launch.
Compare the `host.id` and `host.name` resource attributes in both outputs against the board serial and the chosen labels.
The five-minute verifier's count and timing limits apply to the full discovery run, not these short identity checks.

Both temporary processes stopped, the original port 9100 exporter still responded, and the temporary binaries were removed.
Evidence remains at `/tmp/pi-telemetry-identity.gXyjYk` on the Pi, approximately 44 KiB, and `/private/tmp/pi-telemetry-identity-evidence-20260918` on the workstation.
Fresh-context standards and scope reviews found no issues in the identity change.
