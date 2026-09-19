# Certificate issuer and automatic renewal

Status: issuer placement and root-key custody accepted; renewal client verified with disposable keys.
Bootstrap keys and the local-copy check are complete; off-device root-key backup remains unverified.
The [issuer manifests](../../step-ca/README.md) are prepared, with secret rendering, structural validation, and disposable policy/database-recovery checks completed; live deployment acceptance remains outstanding.
The [client runbook](../../telemetry/certificates.md) records eight passing Pi integration tests and the remaining deployment checks.
This narrows the larger [Roles Anywhere plan](2026-09-18-pi-roles-anywhere.md) to the certificate lifecycle needed before AWS authentication.
The [compatibility research](../research/step-ca-roles-anywhere.md) records source-backed findings and tests still needed against pinned releases.

## Design

Run open-source `step-ca` as a private homelab service, with `step` and a systemd renewal timer on the Pi.
The Pi reads sensors and manages its local credentials as host processes; Kubernetes hosts the separate issuer only.
Keep the root key in an encrypted file on Alex's Mac, backed up in Alex's password manager, and use an online intermediate for issuance.
Keep the root private key outside the cluster, repository, and infrastructure state; use the existing SOPS/KSOPS pattern for the online issuer's encrypted secret manifest.
This keeps the root key off the issuer but is not offline storage.
Use a separate randomly generated password for the intermediate; the root password stays outside the issuer, repository, and infrastructure state.
Store bootstrap material under `~/.local/share/homelab-telemetry-ca` with owner-only permissions.
Verify that a downloaded password-manager backup of the encrypted root key decrypts and matches the root certificate before deployment.

The issuer should use a dedicated private MetalLB HTTPS endpoint instead of the current HTTP-only Traefik gateway.
Add a specific local DNS entry for `ca.home.alexnorum.com` once the service's address is allocated and verified.
TLS terminates at `step-ca` so device-certificate authentication reaches the issuer directly.
The Pi pins the CA root using its certificate/fingerprint at enrollment.

## Evidence and tradeoffs

Read-only inspection found an existing MetalLB pool and two allocated service addresses, for AdGuard and Traefik.
The existing gateway exposes HTTP only; it is not currently configured for TLS passthrough.
The repository has SOPS/KSOPS and a per-service ArgoCD layout but no certificate issuer configuration.
Existing backup jobs cover selected applications, not arbitrary new persistent volumes; CA state recovery must be addressed explicitly.

An issuer outage blocks enrollment and renewal, but an unexpired device certificate remains usable with AWS Roles Anywhere while its chain, AWS trust, and permissions remain valid.
Start with one issuer replica and persistent state rather than introducing a highly available database for one device.
Document an encrypted state backup and restore procedure, including preservation of revocation/enrollment state; do not treat a PVC alone as a backup.

## Interfaces and files

- `step-ca/`: standard homelab namespace, Kustomize, deployment, service, PVC, CA configuration, and encrypted secret integration.
- `argo-apps/applications.yaml`: register the new issuer application.
- `adguard/configmap.yaml`: add the specific issuer DNS record without changing existing wildcard behavior.
- `telemetry/renew-certificate.sh`: small integration script invoking `step`, validating the result, and atomically installing the renewed leaf certificate; no custom certificate protocol or signing implementation.
- `telemetry/systemd/`: a bounded oneshot renewal service and persistent timer, using explicit paths to the device certificate, private key, and trusted root.
- `telemetry/certificates.md`: enrollment, key custody, expiry monitoring, verification, recovery, and issuer rotation procedure.

The initial device subject is `pi-<board-serial>` and telemetry identity remains `raspberrypi:<board-serial>`.
Enrollment uses a short-lived, device-bound authorization token issued by the operator; its signing authority stays off the device.
Renewal authenticates using the existing device certificate and private key and preserves the subject.
The new dependencies are `step-ca` 0.30.2 and `step` 0.30.6, with checksum-verified ARM64 release binaries.
The renewal wrapper uses the Pi's existing Bash, OpenSSL, coreutils, and flock; integration tests use its existing Python standard library.

## Renewal contract

Use a 90-day leaf certificate and start renewing with at least 30 days remaining.
Check hourly with jitter, retry transient failures on subsequent timer runs, and check again after device boot.
The current certificate stays in use until a replacement has passed chain, subject, public-key match, usage, and validity checks.
Stage the replacement on the same filesystem and publish it with an atomic rename.
Source inspection found that the renewal client's own file write is not atomic, which is why this small publication step is necessary.
Normal renewal retains the existing private key; key rotation is a separate lifecycle operation, not a side effect assumed from renewal.
Keep the intermediate stable during this unit and validate it on renewal; the later AWS helper configuration must explicitly pass its intermediate bundle.
Track remaining lifetime and renewal success for monitoring; agree the existing monitoring integration before adding its resources.
An expired certificate requires explicit re-enrollment rather than automatic acceptance of an expired identity.

## Verification

1. Render and validate Kubernetes resources; verify the dedicated HTTPS endpoint with the pinned root and reject an untrusted root.
2. Enroll the authorized device and reject an invalid or wrongly bound enrollment token.
3. Use an isolated test provisioner with short-lived certificates to prove unattended renewal changes certificate serial/expiry while preserving subject and public key.
4. Interrupt renewal before publication and verify the existing certificate remains usable; then verify recovery after restarting the timer.
5. Temporarily make only the test issuer path unavailable, observe failure/expiry signals, restore access, and verify automatic recovery.
6. Verify the expired-certificate recovery boundary and remove the test provisioner and test credentials after testing.
7. Exercise state backup/restore in isolation and document the issuer/root rotation sequence and trust overlap.
8. Run simplification and fresh-context review before deployment is presented as complete.

## Scope boundary

This unit does not create AWS Roles Anywhere resources, grant S3 permissions, change the Collector's output destination, or establish a week-long telemetry queue guarantee.
The following unit integrates the renewable device certificate with AWS's credential helper and verifies SDK credential refresh and helper adoption of a renewed certificate.
Long-term unattended authentication is complete only after both units pass verification.
