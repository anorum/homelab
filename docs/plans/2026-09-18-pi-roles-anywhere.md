# Pi certificate authentication plan

Status: private issuer and device Roles Anywhere resources deployed; real-expiration SDK refresh, renewed-certificate adoption, and wrong-device rejection verified on 2026-09-19.
Alex approved existing Prometheus certificate alerts on 2026-09-19; see [the monitoring plan](2026-09-19-certificate-alerts.md).
S3 ingestion is a separate unit.
The [authentication runbook](../../telemetry/roles-anywhere.md) records installation, tests, and emergency access removal.
Read-only AWS discovery completed after Alex renewed the workstation's default CLI session.

## Outcome

The Pi obtains short-lived AWS credentials using its own certificate and private key, independently of Kubernetes.
Authentication must include automatic device-certificate renewal and AWS credential refresh, with no recurring operator login.
Separate the issuer deployment from device enrollment and verification if the revised scope exceeds one implementation unit.
S3 destination and upload permissions follow the authentication work.

## Existing solutions and evidence

Use AWS's `aws_signing_helper` through its supported `credential_process` integration rather than building a credential broker.
The helper has an official Linux Aarch64 release, and the Collector's S3 exporter uses the AWS Go SDK credential chain.
The installed OpenTofu and Terragrunt tools can manage AWS resources; the homelab already uses the HashiCorp AWS provider and region `us-west-2`.
The existing Kubernetes IRSA setup remains separate from this device authentication path.
Read-only AWS discovery on 2026-09-18 found no Roles Anywhere trust anchors, profiles, or AWS Private CAs in `us-west-2`.
The existing `anorum-homelab` state bucket is accessible and its ownership matches the authenticated account, verified with `HeadBucket` and `ExpectedBucketOwner`.
Repository inspection found no CA configuration; this does not rule out an external CA managed elsewhere.

Manual certificate renewal is no longer an acceptable proposed endpoint.
Use the existing open-source `step-ca` service and `step` renewal client, with the verified shell wrapper limited to validation and atomic certificate publication.
The issuer runs in k3s, and the supervised renewal client runs directly on the Pi.
The root key stays encrypted on Alex's Mac with a verified iCloud Drive backup and its password in Apple Passwords; a separately protected intermediate signs certificates on the issuer.
The Mac root is outside the running issuer, not offline storage.

## Interfaces and identity

- Device identity remains `host.id=raspberrypi:<board-serial>` in telemetry.
- The device certificate uses subject CN `pi-<board-serial>`, independent of hostname and compatible with AWS source-identity naming rules.
- Generate the device private key on the Pi; enrollment and renewal send signed requests to the selected issuer without transferring that private key.
- Register the CA's public certificate as an IAM Roles Anywhere trust anchor in `us-west-2`.
- Create one IAM role and one Roles Anywhere profile for this device.
- Restrict the role trust policy to the exact trust anchor, account, CA issuer, and device certificate subject.
- Configure a dedicated AWS shared-config file with `credential_process` invoking the official helper with certificate/key paths and generated resource ARNs.
- Request 15-minute sessions; consume the helper's credential JSON without printing credential values or persisting them in git.

The certificate proves possession of its private key, not hardware attestation of the serial number.
The board serial is bound into the certificate during enrollment over the existing trusted SSH connection.
This unit adds no S3 permissions to the role; it must not borrow the existing backup user's broader permissions.

## Ownership, files, and dependencies

- `telemetry/deploy/roles-anywhere/`: OpenTofu configuration for the trust anchor, profile, and role, using the existing AWS provider family.
- Use a separate state key, `terraform/telemetry/roles-anywhere.tfstate`, in the existing homelab state bucket after confirming its ownership and access; enable S3 state locking for this new state.
- `telemetry/roles-anywhere.md`: enrollment, helper configuration, verification, renewal, and emergency access-removal procedure.
- `telemetry/README.md`: link to the authentication procedure and explain its connection to the Collector.
- Root CA material: keep the encrypted private key on Alex's Mac, off the Pi and outside git and OpenTofu state, with the verified iCloud Drive backup.
- Pi certificate/key: `/var/lib/telemetry/identity`, with directory mode 0700 and private-key mode 0600; public trust files and renewal configuration live under `/etc/telemetry` as described in the issuer runbook.
- Set the AWS credential consumer's runtime account and identity-file access explicitly during its integration.
- Pin and checksum-verify the official helper; verify compatibility on Debian 12 ARM64 before enrollment changes.
- Keep account IDs, concrete role ARNs, private keys, and session credentials out of repository files, following homelab conventions.

Use the selected `step-ca` and `step` dependencies for certificate issuance and renewal.
Keep collection and renewal clients on the Pi independent of Kubernetes; only the issuer is hosted there.
Supervised renewal and safe certificate replacement are part of unattended authentication, not deferred operational instructions.

## Certificate lifecycle

Propose a 90-day device certificate and renewal starting with at least 30 days remaining, leaving substantial margin for the agreed week offline.
Configure bounded retry/backoff and alert on renewal failure and decreasing time to expiry.
The device authenticates a renewal request with its existing certificate and private key, preserving its board-based subject.
Certificate renewal and private-key rotation are distinct operations; define and test the chosen key-rotation policy separately rather than assuming renewal creates a new key.
Validate renewed certificates before installing them atomically, and verify the AWS helper uses the renewed file on a subsequent credential request.
Certificate replacement must survive a restart without leaving a partial file or mismatched certificate/key pair.
If the device stays offline until its certificate expires, use an explicit re-enrollment procedure; do not silently permit expired credentials as a workaround.
Monitor the issuer/root certificate lifetimes and define their rotation and overlapping AWS trust-anchor transition before considering the lifecycle complete.
For this single-device setup, disabling its dedicated profile or removing its role trust stops issuance of new sessions; already-issued sessions can remain usable until expiration unless separately revoked.
Fleet enrollment and CRL distribution remain outside the initial lab scope; automatic device-certificate renewal is required.

## Verification and execution boundary

1. Recheck that the deployment credentials resolve to the discovered homelab account before applying resources; the initial account, state-bucket, and CA inventory checks passed.
2. Validate the helper's pinned checksum and successful execution on the Pi.
3. Prepare the certificate requests, OpenTofu configuration, and a concrete plan showing only this unit's resources before applying changes.
4. Run formatting and configuration validation, then apply the approved unit's reviewed resource plan without modifying shared monitoring or backup resources.
5. Verify the certificate chain, key usage, subject binding, expiry, and file permissions.
6. From the Pi, obtain session credentials with the intended role and profile; report only response validity and expiration metadata.
7. Verify AWS SDK session refresh across expiration using the credential helper, without interactive login or logging credential values.
8. Use a short-lived test certificate signed by the same CA but with a different device subject; verify the upload role rejects it, then remove the test key and certificate.
9. Use shortened certificate lifetimes in a test configuration to verify renewal, safe installation, helper adoption, and restart recovery without waiting months.
10. Make the issuer temporarily unavailable to verify retry and expiry monitoring, then restore it and verify renewal recovery; explicitly test the expired-certificate recovery boundary.
11. Record exact commands, results, and resource ownership; run simplification and fresh-context review before presenting the change.

S3 writes, explicit metric units, and the telemetry persistent queue remain outside the authentication scope.
The approved issuer plan governs bootstrap and deployment; prepare and review the AWS resource plan separately before applying it.

## Primary references

- [Roles Anywhere setup](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/getting-started.html)
- [Role trust, certificate requirements, and revocation](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/trust-model.html)
- [Official credential helper and SDK integration](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/credential-helper.html)
- [Smallstep automatic renewal client](https://smallstep.com/docs/step-cli/reference/ca/renew/)
- [Smallstep renewal operations](https://smallstep.com/docs/step-ca/renewal/)
