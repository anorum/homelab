# Collector S3 buffering research

Research date: 2026-09-19.
Scope: the repository's pinned `otelcol-contrib` v0.161.0, one Pi temperature reading every five seconds, individual readings retained in S3, and seven days without network connectivity while local hardware remains healthy.
This is source research, not an approved implementation plan or evidence of a tested S3 pipeline.
No infrastructure, credentials, running services, or Collector configuration were changed.

## Finding

The existing Collector has the components needed to investigate this requirement without a custom uploader: `awss3`, its `sending_queue`, and `file_storage`.
The S3 metrics exporter wires in exporterhelper queue, retry, and timeout support; the exporter remains alpha.
Its module pins exporterhelper v0.161.0 and AWS Go SDK v2, including transfermanager v0.4.3.
[Factory](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.161.0/exporter/awss3exporter/factory.go), [stability](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.161.0/exporter/awss3exporter/README.md), [dependencies](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.161.0/exporter/awss3exporter/go.mod).

Inference: with sufficient queue and disk capacity, unlimited outer retries, and healthy local storage, this is a plausible fit for network outages and at-least-once delivery.
It is not an unconditional rule that local data is deleted only after an S3 acknowledgment: the queue also discards data after terminal processing errors, and storage corruption or failures have loss paths.
Those distinctions need to remain explicit in the eventual acceptance criteria.
[Persistent queue](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.161.0/exporter/exporterhelper/internal/queue/persistent_queue.go), [retry loop](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.161.0/exporter/exporterhelper/internal/retry_sender.go).

## Data format and batching

`marshaler: otlp_json` is the factory default and uses the native `pmetric.JSONMarshaler`; `otlp_proto` also supports metrics.
`sumo_ic` is explicitly rejected for metrics, while `body` initializes a logs marshaler only and should not be used for this metrics pipeline.
Compression accepts `gzip`, `zstd`, or no compression.
[Marshaler](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.161.0/exporter/awss3exporter/marshaler.go), [configuration](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.161.0/exporter/awss3exporter/config.go).

Each exporter call marshals its metrics request and uploads that envelope as one object.
There is no time-window accumulator inside `awss3` itself.
Compressed JSON gets `.json.gz` or `.json.zst` and the corresponding `Content-Encoding`; the upload body is compressed before the SDK receives it.
Do not assume JSONL object contents or infer on-disk queue compression from S3 compression.
[Export path](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.161.0/exporter/awss3exporter/exporter.go), [upload writer](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.161.0/exporter/awss3exporter/internal/upload/writer.go), [filenames](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.161.0/exporter/awss3exporter/internal/upload/partition.go).

`sending_queue.batch` can merge requests after persistence, governed by `flush_timeout`, `min_size`, and `max_size`.
The metrics implementation appends resource metrics and moves individual data points when splitting; it does not calculate averages or replace readings with a rollup.
The batch retains completion callbacks and invokes them after downstream processing returns.
This makes queue batching worth evaluating before adding an upstream batch processor with another volatile buffer.
[Queue wiring](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.161.0/exporter/exporterhelper/internal/queuebatch/queue_batch.go), [metric merging](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.161.0/exporter/exporterhelper/internal/queuebatch/metrics_batch.go), [completion callbacks](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.161.0/exporter/exporterhelper/internal/queuebatch/partition_batcher.go).

## Retries and acknowledgment

There are two retry layers.
The AWS client defaults to standard retries, three attempts, and a 20-second maximum backoff.
The Collector separately defaults to enabled retries with a five-minute elapsed limit; `retry_on_failure.max_elapsed_time: 0` removes that elapsed limit.
A week of retention cannot rely on the defaults.
The Collector's timeout is per outer export attempt and defaults to five seconds, so it can also cut short the SDK's attempts within that call.
[AWS client construction](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.161.0/exporter/awss3exporter/s3_writer.go), [helper configuration](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.161.0/exporter/exporterhelper/README.md).

The S3 exporter returns the transfer manager's upload error unchanged.
The outer retry loop retries ordinary errors, including AWS errors that the SDK itself declines to retry; it stops immediately for Collector permanent-error wrappers and also stops on cancellation or shutdown.
Consequently an authorization problem can occupy consumers indefinitely with unlimited retries, eventually filling the queue unless corrected.
[Exporter return path](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.161.0/exporter/awss3exporter/exporter.go), [retry implementation](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.161.0/exporter/exporterhelper/internal/retry_sender.go).

For a small object, transfermanager returns success after `PutObject` succeeds; a multipart upload completes only after `CompleteMultipartUpload` succeeds.
The exporter waits for that result before returning success.
AWS documents that a successful PUT means the entire object was added, and S3 Standard stores objects across at least three Availability Zones.
This is an S3 storage acknowledgment, not acknowledgment by a later rollup job.
[Pinned transfer manager](https://github.com/aws/aws-sdk-go-v2/blob/feature/s3/transfermanager/v0.4.3/feature/s3/transfermanager/api_op_UploadObject.go), [PUT contract](https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html), [S3 durability](https://docs.aws.amazon.com/AmazonS3/latest/userguide/DataDurability.html).

Persistent queue entries remain stored while dispatched and are deleted when processing finishes, including exhausted retries or permanent errors.
Shutdown errors preserve dispatched entries for restart.
Startup requeues previously dispatched entries, but its recovery procedure deletes their old keys before rewriting them, leaving a crash/storage-error window during recovery.
This fits an explicitly bounded tolerance for application/crash loss better than a claim of strict losslessness.
Deletion frees database entries; it does not immediately shrink the database file.
[Queue implementation](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.161.0/exporter/exporterhelper/internal/queue/persistent_queue.go), [storage compaction](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.161.0/extension/storage/filestorage/README.md).

## Object keys and duplicate readings

The key is the configured base/prefix, a partition formatted from upload time, and `<file_prefix>metrics_<unique>.json[.gz|.zst]`.
The default unique suffix is a random nine-digit integer; `unique_key_func_name: uuidv7` is available and is the stronger candidate for avoiding collisions during backlog replay.
Neither option provides stable content-based idempotency.
Every outer upload retry generates a new key, so a completed upload with a lost response, or restart after upload but before local deletion, can produce duplicate objects.
SDK retries within one upload call use that call's key.
[Key builder](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.161.0/exporter/awss3exporter/internal/upload/partition.go), [upload invocation](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.161.0/exporter/awss3exporter/internal/upload/writer.go).

Inference: downstream rollup must use original point timestamps and an agreed deduplication identity, rather than object key or upload partition as the measurement identity/time.
Backlogged readings upload into recovery-time partitions.
The exact deduplication identity and raw/rollup interfaces remain design decisions.

## Capacity and supported limits

Seven days at one point per five seconds is **120,960 points**, before headroom for an existing backlog or delayed recovery.
With one request per scrape, that is also 120,960 incoming requests; grouping persisted requests into objects does not reduce the queue's incoming-request requirement.
The helper's standard capacity of 1,000 requests represents only about 83 minutes at that rate.
The queue supports sizing in requests, metric points (`items`), or serialized bytes and includes dispatched requests in its capacity accounting.
[Sizing implementation](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.161.0/exporter/exporterhelper/internal/queue/persistent_queue.go), [metric size/encoding](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.161.0/exporter/exporterhelper/internal/queuebatch/metrics.go).

- `sending_queue.storage: file_storage/<name>` enables persistence; that exact extension must also be enabled under `service.extensions`.
- `wait_for_result: true` is unsupported with persistent storage.
- Queue batches support `items` or `bytes`, not `requests`; explicitly set the batch sizer if choosing a request-sized queue.
- A byte-sized batch limit smaller than an individual point can discard that point during splitting.
- A full queue or failed storage write rejects new data before export retries apply; blocking cannot recover temperature samples that were never acquired.

[Queue validation](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.161.0/exporter/exporterhelper/internal/queuebatch/config.go), [split failure](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.161.0/exporter/exporterhelper/internal/queuebatch/metrics_batch.go), [enqueue failures](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.161.0/exporter/exporterhelper/README.md).

`file_storage.max_size` caps each bbolt database file, separately from the queue's logical size.
Its `fsync` option trades synchronous disk writes for crash durability; compaction can reclaim previously allocated space and needs temporary space.
Disk capacity, filesystem overhead, SD-card write volume, and compaction headroom must be measured on the Pi.
The discovery run's uncompressed JSON bytes per sample are not a queue footprint measurement.
[Storage options](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.161.0/extension/storage/filestorage/README.md), [local discovery evidence](../../telemetry/README.md).

## Existing alternatives and authentication

| Option | Assessment for this requirement |
| --- | --- |
| Existing Prometheus receiver and filters, plus `awss3` persistent queue | Candidate with the fewest new components; preserves the tested acquisition path and native OTLP data. |
| File exporter, rotated files, and replay/upload tooling | Useful for inspectable archives, but its age/count rotation is not S3-acknowledged deletion; additional lifecycle coordination is required. |
| A separate custom spool/uploader | Consider only if testing reveals a missing requirement, such as deterministic immutable keys or stronger deletion semantics. |

The file exporter documents local rotation and OTLP JSON replay, not an S3 acknowledgment-coupled spool protocol.
[File exporter](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.161.0/exporter/fileexporter/README.md).

The pinned exporter calls AWS Go v2 `config.LoadDefaultConfig`, so the existing Roles Anywhere `credential_process` approach is compatible in principle.
Use the existing dedicated-account profile/environment contract and keep raw credential stdout out of the journal.
Helper stderr can become SDK error text, and exporterhelper logs retry errors, so failed-refresh journal behavior belongs in acceptance testing.
Persistent queue limitations on inbound authentication context do not remove the exporter's independent AWS credential provider.
[Client initialization](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.161.0/exporter/awss3exporter/s3_writer.go), [AWS process provider](https://docs.aws.amazon.com/sdkref/latest/guide/feature-process-credentials.html), [local authentication contract](../../telemetry/roles-anywhere.md).

## Proposed verification before adoption

These are follow-up checks, not completed tests or permission to change infrastructure.

1. Validate an explicit queue/storage/batch configuration using the pinned ARM64 binary; settle capacity, upload latency, storage directory, and crash-loss tolerance first.
2. Upload known timestamped readings and compare every decoded S3 point, including metadata, with the inputs; check compression and object naming.
3. Block network access while collecting, verify that persistence grows beyond the normal five-minute retry window, then restore access and reconcile all points.
4. Queue at least 120,960 representative points to measure capacity and disk growth; verify new live samples continue while the backlog drains.
5. Restart and kill the Collector during queuing, batching, and replay; reconcile losses/duplicates against the agreed tolerance.
6. Simulate a lost successful-upload response and confirm downstream deduplication; test queue/disk-full and authorization failures in isolation.
7. Confirm actual S3 success precedes queue removal, distinguish logical draining from physical compaction, and test credential expiration/recovery without secrets in the journal.

Queue-capacity loading is not by itself a seven-day endurance test.
Retain monitoring for queue occupancy, enqueue failures, retry failures, free disk, and sampling gaps in the eventual plan; the current discovery config disables the Collector metrics listener.
