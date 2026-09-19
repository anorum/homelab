# Pi AWS certificate authentication

The Pi uses AWS's official `aws_signing_helper` through `credential_process` as the dedicated `telemetry` OS account.
The private key stays in `/var/lib/telemetry/identity`; AWS receives a signed request and the public certificate chain.
The deployed role has no attached or inline permission policies, so this establishes authentication without granting S3 access.

## Managed resources and state

[The OpenTofu module](deploy/roles-anywhere/main.tf) owns exactly one trust anchor, device IAM role, and Roles Anywhere profile in `us-west-2`.
The trust anchor uses the public root from `step-ca/config/root_ca.crt`.
The role requires the exact source account, trust-anchor ARN, enrolled device CN, and `Homelab Telemetry Intermediate CA` issuer CN.
The profile permits only that role and limits sessions to 900 seconds; the helper requests the same duration.
IAM's role maximum-session-duration remains its minimum legal 3600 seconds.
Default profile attribute mappings use `*` for subject and issuer fields, which includes the CN attributes used by the trust policy.

State uses `s3://anorum-homelab/terraform/telemetry/roles-anywhere.tfstate`, encryption, and native S3 locking.
The existing backup-user state and permissions are separate.
Keep deployment inputs, plans, outputs, logs, and concrete resource ARNs outside git in the owner-only `~/.local/share/homelab-telemetry-ca/aws/` directory.
`inputs.json` contains `expected_account_id` and `device_cn`; obtain the latter from the Pi's board serial and confirm it matches the enrolled certificate.
Confirm the AWS caller's account matches the intended homelab account and run `aws s3api head-bucket --bucket anorum-homelab --expected-bucket-owner ACCOUNT_ID` before initialization.
Initialize with `-backend-config='allowed_account_ids=["ACCOUNT_ID"]'` as an additional backend guard.
The provider independently enforces the expected account.

The installed OpenTofu 1.11.5 and pinned provider use older AWS SDKs than the workstation CLI's `aws login` integration.
For deployment, obtain the current session with `aws configure export-credentials --format process`, parse it in memory, and pass its three credential fields only in the OpenTofu child process's environment.
Do not print or save that response, place credentials in backend configuration, or copy the workstation session to the Pi.
[OpenTofu documents native `aws login` support beginning with 1.12](https://opentofu.org/docs/language/settings/backends/s3/).
Run `tofu fmt -check`, `tofu validate`, and save a plan outside git before applying it.
The initial reviewed plan contained exactly three creates, no changes, and no deletes; subsequent plans should be inspected for drift.
The sensitive `credential_process_arns` output supplies the deployed role, profile, and trust-anchor ARNs without embedding account-specific values in this repository.

## Device setup

The [certificate runbook](certificates.md) governs enrollment, key custody, and the hourly renewal timer.
The runtime account is a system user named `telemetry`, with no login shell.
Its identity directory is `0700`, and both device key and leaf certificate are `0600`, owned by `telemetry`.
Public root/intermediate files and configuration under `/etc/telemetry` are root-owned and readable by the runtime account.
The helper is installed root-owned at `/usr/local/bin/aws_signing_helper` with mode `0755`.

Pin helper version `1.8.5` using the [official Linux ARM64 artifact](https://rolesanywhere.amazonaws.com/releases/1.8.5/Aarch64/Linux/Amzn2023/aws_signing_helper).
Verify SHA256 `3d131aa888cd56da446f9c6bb460b1f0569f6c7edc74eae6193a2fe3928883ba` both before transfer and on the Pi before installing it.
This checksum is published in the [AWS helper documentation](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/credential-helper.html).
The verified binary reports `1.8.5` and executes on this Debian 12 ARM64 Pi.

Render `/etc/telemetry/aws-config` with the actual OpenTofu outputs substituted:

```ini
[profile telemetry]
region = us-west-2
credential_process = /usr/local/bin/aws_signing_helper credential-process --certificate /var/lib/telemetry/identity/device.crt --private-key /var/lib/telemetry/identity/device.key --intermediates /etc/telemetry/intermediate_ca.crt --trust-anchor-arn TRUST_ANCHOR_ARN --profile-arn PROFILE_ARN --role-arn ROLE_ARN --region us-west-2 --session-duration 900
```

The future Collector service must run as `telemetry` and set `AWS_CONFIG_FILE=/etc/telemetry/aws-config`, `AWS_PROFILE=telemetry`, and `AWS_EC2_METADATA_DISABLED=true`.
Exclude inherited static credentials, web-identity settings, and unrelated shared credentials so the SDK selects this process provider.
The acceptance probe uses `AWS_SHARED_CREDENTIALS_FILE=/dev/null` explicitly.
The intermediate bundle is passed separately because the helper does not infer that option from a full chain in the leaf file.

AdGuard resolves `ca.home.alexnorum.com` to the issuer's pinned `192.168.1.152` address.
This Pi obtains DNS from the router, which does not forward that local zone to AdGuard, so `/etc/hosts` has one exact issuer entry at the same address.
Its general resolver configuration remains router-managed.
Changing the issuer address requires updating the Service, AdGuard record, and this device entry together.

## Verification

The [acceptance probe](tests/credential-refresh/main.go) uses the Collector 0.161.0 exporter's AWS SDK versions and retains one config, credential cache, and STS client through expiration.
Build it on the workstation with `CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build` from its directory.
Run it as `telemetry` with the environment above and `EXPECTED_AWS_ROLE_ARN` set to the deployed role.
It reports only stage outcomes, provider name, and expiration times; it does not print credentials, returned account IDs, ARNs, or raw provider errors.
The probe requires an expiring process-provider session, checks every STS response against the expected role, and succeeds only when credentials change after the initial expiration.
Its 20-minute timeout bounds the real 15-minute-session test.
These Go dependencies and the probe binary are acceptance tooling, not a permanent Pi daemon or Collector dependency.

Verified on 2026-09-19:

- OpenTofu validation passed with zero errors/warnings, and the saved three-create plan applied successfully.
- Live profile inspection confirmed one permitted role, 900-second duration, and subject/issuer mappings covering CN.
- Live IAM inspection found zero attached policies and zero inline permission policies.
- The helper ran as `telemetry`, returned valid session credentials, and reported 899 seconds remaining without exposing credential values.
- A valid, unexpired five-minute certificate from the same CA with a different CN received `AccessDenied`; its temporary key and certificate were removed.
- The installed renewal service published a new real certificate with the same private key, and a subsequent helper invocation authenticated successfully with it.
- The installed timer automatically triggered renewal under an accelerated test schedule; normal scheduling was restored, and an issuer-path failure/recovery test preserved the working certificate.
- `go vet` and ARM64 cross-compilation passed; a fault-injected helper emitting sentinel values on stdout/stderr produced only sanitized failure JSON, with no sentinels in probe output.
- The real-expiration SDK refresh test is still running; record its final outcome before claiming unattended AWS refresh is verified.

## Recovery and rotation

If the device certificate expires, explicitly re-enroll the same verified board identity; expired-certificate renewal is disabled.
For device-key rotation, generate a new key and CSR on the Pi, obtain a fresh short-lived enrollment token on the Mac, and validate the new chain/subject/key pair before a coordinated cutover while consumers are stopped.
Preserve the old working pair until verification succeeds, then remove superseded key material; normal renewal does not rotate keys.

For urgent access removal, disable this device's dedicated Roles Anywhere profile or remove its IAM role trust.
Already issued sessions can remain usable until expiration, bounded here by 15 minutes unless separately revoked.
Use AWS's IAM session-revocation mechanism when immediate invalidation is necessary, then reconcile any emergency changes into OpenTofu before the next apply.
This lab does not distribute a fleet CRL.

Intermediate rotation requires updated issuer credentials, device trust bundle, helper intermediate bundle, and renewal validation together.
If the intermediate CN changes, adjust the exact IAM issuer condition during the transition; the public root trust anchor remains valid for intermediates it signs.
For root rotation, create a second trust anchor, temporarily permit both explicit anchor ARNs in role trust, deploy overlapping trust bundles, and move helper configuration and device certificates to the new chain before removing the old anchor and trust.
The current single-intermediate renewal wrapper is intentionally strict; implementing overlapping chains requires a separately reviewed change before rotation.
