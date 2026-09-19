# Private telemetry certificate issuer

Status: issuer deployed on 2026-09-19; live enrollment and pinned-root HTTPS succeeded.
The [issuer plan](../docs/plans/2026-09-18-certificate-issuer.md) defines the remaining acceptance checks.
Root-key backup recovery passed on 2026-09-19: both files were uploaded to iCloud Drive, evicted locally, downloaded again, and matched the verified originals.

## Runtime

One `step-ca` replica listens on container port 9000 behind a private MetalLB service on port 443.
MetalLB allocated `192.168.1.152`; the Service now requests that address explicitly to preserve the matching DNS record across recreation.
TLS terminates at the issuer so device-certificate authentication reaches it directly.
This intentionally uses the approved private LoadBalancer instead of the HTTP-only shared gateway.
The [official container](https://smallstep.com/docs/tutorials/docker-tls-certificate-authority/) is pinned to version 0.30.2 and image-index digest `sha256:a2b17872915c193259b75a5474c398326f41bd199f0842093e52cf4182bc8270`; its Linux ARM64 image was verified in the registry.
The deployment runs UID/GID 1000 with a read-only root filesystem and writable database/temporary mounts.
It retains `NET_BIND_SERVICE` because the pinned image's executable carries that file capability; dropping it prevents startup even on port 9000.
Its startup command runs the existing issuer configuration directly, bypassing container bootstrap.

`config/` contains public certificates, the enrollment public key, and CA policy.
`secret.enc.yaml` holds only the intermediate private key and its unlock password, encrypted for the existing homelab SOPS recipient.
The root private key, root password, and enrollment signing credentials stay outside the cluster.
Device certificates default to 2160 hours (90 days), with the same maximum; expired-certificate renewal is disabled.

Badger state uses a 1Gi `local-path` PVC.
`Recreate` prevents two issuer processes from opening the same database during an update.
ArgoCD excludes the PVC from its normal prune/delete actions; namespace deletion or loss of the storage still requires recovery from backup.
The database records revocations and used enrollment tokens, so an empty replacement is not an equivalent restore.

## Enrollment and checks

The operator creates a five-minute, device-bound token using the encrypted enrollment JWK retained from bootstrap.
Use a separate operator `STEPPATH`, explicit `--key`, `--kid`, `--issuer`, `--ca-url`, and `--root` arguments with `step ca token --offline`.
The pinned CLI otherwise opens an existing local CA configuration, including its database, even when explicit key arguments are supplied.
The operator uses the enrollment password, which differs from the issuer password.
The Pi receives only its short-lived enrollment token and public trust material; its device private key is generated on the Pi.

Run the policy integration test with checksum-verified `step` 0.30.6 and `step-ca` 0.30.2 on `PATH`:

```sh
python3 step-ca/tests/test_issuer.py
```

It substitutes disposable keys and loopback paths into the repository's CA policy, then checks trusted HTTPS, rejection without the pinned root, subject binding, the certificate lifetime limit, single-use tokens, and replay protection after a cold database copy/restore.
It does not exercise the real cluster deployment or encrypted backup transport.

On 2026-09-19, this test passed in 2.052 seconds.
The cluster's existing ArgoCD/KSOPS tools rendered six resources, and `kubectl create --dry-run=client --validate=strict` accepted them.
A comparison of the rendered Secret confirmed the intermediate key/password matched bootstrap and that the root key and enrollment password were absent.
Disposable cluster pods tested the pinned ARM64 image with the deployment's security context: dropping all capabilities failed with exit 255; retaining `NET_BIND_SERVICE` returned `Smallstep CA/0.30.2` with exit 0.
Both test pods were deleted; this checks container execution, not issuer startup with mounted credentials and storage.

## Before deployment is complete

The off-device root-key backup is verified and the issuer rollout passed with one ready replica and its PVC bound.
The exact `ca.home.alexnorum.com` AdGuard rewrite targets `192.168.1.152`; verify it resolves to that address after GitOps sync.
AdGuard copies its ConfigMap only during pod initialization, so applying the DNS configuration also requires a controlled rollout and a resolution check.
Verify HTTPS using the pinned root and expected hostname before device enrollment; the Kubernetes HTTPS probes check health, not CA trust.
The Pi is enrolled and its renewal timer is installed; due-renewal acceptance and the expiry-monitoring integration remain pending.

The issuer-state recovery procedure must preserve the database together with the matching configuration and intermediate credentials.
Stop the issuer before taking a cold database archive, encrypt the archive using the existing SOPS/age setup, and store it outside the node holding the PVC.
Restore into an isolated volume and verify both new enrollment and rejection of a previously consumed token before relying on the backup.
The exact encrypted archive transport and its recovery test remain part of deployment acceptance; the local database-copy test alone does not establish a working backup.
