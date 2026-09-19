# Pi Roles Anywhere integration research

Research date: 2026-09-19.
Scope: the approved authentication plan, without S3 permissions or AWS resource creation.
Official source inspection and a local artifact checksum check are complete; Pi execution and real AWS session tests remain deployment acceptance work.

## Pinned helper and verification

The current official release is [v1.8.5](https://github.com/aws/rolesanywhere-credential-helper/releases/tag/v1.8.5), released August 24, 2026.
Pin the [Linux ARM64 binary](https://rolesanywhere.amazonaws.com/releases/1.8.5/Aarch64/Linux/Amzn2023/aws_signing_helper), with SHA256 `3d131aa888cd56da446f9c6bb460b1f0569f6c7edc74eae6193a2fe3928883ba` published in the [AWS helper download table](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/credential-helper.html).
This checksum comes from AWS's HTTPS documentation, not merely from hashing an otherwise unverified download.
The documentation specifically describes signatures for Darwin and Windows releases; do not claim a Linux signature verification from this checksum check.

Downloaded the 11,234,544-byte artifact to `/private/tmp/aws_signing_helper-1.8.5-linux-arm64` and calculated SHA256 with Python `hashlib`; it matches exactly.
Local `file` inspection reports an ARM AArch64 ELF executable using `/lib/ld-linux-aarch64.so.1`.
Binary inspection finds GLIBC symbol-version references through `GLIBC_2.34`.
The Amzn2023 build label is not a Debian compatibility guarantee: verify `version` and `credential-process --help` on the actual Pi before installation.
Recheck the checksum on the Pi after copying, using `sha256sum --check`; install only after verification.

## Trust policy and session limits

Use the following role trust-policy shape, rendering the placeholders from deployment inputs rather than committing concrete account IDs or ARNs.
The issuer CN is the device leaf's immediate issuing intermediate CN, not the root subject CN.
AWS evaluates subject and issuer certificate attributes as principal tags and sets SourceArn/SourceAccount from the selected trust anchor. [AWS trust model](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/trust-model.html)

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "rolesanywhere.amazonaws.com"},
    "Action": ["sts:AssumeRole", "sts:TagSession", "sts:SetSourceIdentity"],
    "Condition": {
      "StringEquals": {
        "aws:SourceAccount": "ACCOUNT_ID",
        "aws:PrincipalTag/x509Subject/CN": "pi-BOARD_SERIAL",
        "aws:PrincipalTag/x509Issuer/CN": "ISSUING_INTERMEDIATE_CN"
      },
      "ArnEquals": {"aws:SourceArn": "TRUST_ANCHOR_ARN"}
    }
  }]
}
```

All conditions must match; use exact equality and no wildcard subject.
Missing certificate tags fail these equality tests.
The profile's default mappings include both subject and issuer RDNs, so no custom mapping resource is needed for CN restrictions; verify those mappings remain present. [Default attribute mappings](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/attribute-mapping.html)
This constrains the issuer name under the pinned trust anchor; it is not a separate intermediate-key fingerprint pin.
Reject a same-CA certificate with a different CN as the required negative test.

Set the dedicated profile's `durationSeconds` to `900` and its role list to only the device role. [CreateProfile API](https://docs.aws.amazon.com/rolesanywhere/latest/APIReference/API_CreateProfile.html)
Also pass `--session-duration 900` to the helper.
AWS uses the smaller of profile and request duration; omitting the request uses the profile duration. [CreateSession expiration](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/authentication-create-session.html#credentials-object)
Leave IAM role `max_session_duration` at `3600`, its minimum legal value; setting the role itself to `900` is invalid. [CreateRole API](https://docs.aws.amazon.com/IAM/latest/APIReference/API_CreateRole.html)
No role permission policy is required for the initial identity test: STS GetCallerIdentity requires no permission grant. [GetCallerIdentity API](https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html)

## Credential process and intermediate chain

Render one dedicated shared-config profile with absolute paths and literal deployed ARNs.
The following is an illustrative configuration shape; `ACCOUNT_ID`, resource IDs, and filenames must be resolved before use.

```ini
[profile telemetry]
region = us-west-2
credential_process = /usr/local/bin/aws_signing_helper credential-process --certificate /var/lib/telemetry/identity/device.crt --private-key /var/lib/telemetry/identity/device.key --intermediates /etc/telemetry/intermediate_ca.crt --trust-anchor-arn TRUST_ANCHOR_ARN --profile-arn PROFILE_ARN --role-arn ROLE_ARN --region us-west-2 --session-duration 900
```

The helper accepts an explicit intermediate bundle and emits the standard version-1 credential JSON with expiration. [Helper options and output](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/credential-helper.html)
The v1.8.5 filesystem signer reads the leaf and intermediate bundle separately and rereads files during signing; passing the full chain only as `--certificate` does not replace `--intermediates`. [Pinned filesystem signer](https://github.com/aws/rolesanywhere-credential-helper/blob/v1.8.5/aws_signing_helper/file_system_signer.go)
Each credential-process invocation creates a signer and requests fresh credentials. [Pinned command](https://github.com/aws/rolesanywhere-credential-helper/blob/v1.8.5/cmd/credential_process.go)
Inference: the existing same-key atomic leaf replacement can be adopted by the next invocation without restarting a daemon; verify this with the renewed certificate during live acceptance.

Set `AWS_CONFIG_FILE` to the dedicated configuration and `AWS_PROFILE=telemetry` for the runtime account.
Exclude inherited static credentials, web-identity configuration, and unrelated shared credentials from the verification environment, since the SDK chain may select them before the intended process provider. [Go SDK configuration](https://docs.aws.amazon.com/sdk-for-go/v2/developer-guide/configure-gosdk.html)
Run the helper under the actual consumer account to prove access to the 0700 identity directory and 0600 private key.

## Real Go SDK refresh test

Collector 0.161.0's S3 exporter calls `config.LoadDefaultConfig`, so a small Go SDK probe can verify authentication without granting S3 access.
Keep the exporter's optional role ARN unset when eventually integrating it, because that option introduces an additional AssumeRole call. [Pinned exporter implementation](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.161.0/exporter/awss3exporter/s3_writer.go)

Match the exporter's [pinned dependency manifest](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.161.0/exporter/awss3exporter/go.mod): AWS SDK core `v1.46.0`, config `v1.33.3`, credentials `v1.20.3`, and STS `v1.49.0`.
Its Go directive is `1.26.0`.
Cross-compile the disposable verification binary with `CGO_ENABLED=0 GOOS=linux GOARCH=arm64` to avoid adding a Go toolchain to the Pi.
Keep these probe-only dependencies separate from permanent service dependencies.

The [pinned config resolver](https://github.com/aws/aws-sdk-go-v2/blob/config/v1.33.3/config/resolve_credentials.go) selects process credentials and wraps them in a credentials cache.
The [process provider](https://github.com/aws/aws-sdk-go-v2/blob/credentials/v1.20.3/credentials/processcreds/provider.go) marks credentials expiring when the JSON includes `Expiration`.
The [pinned cache](https://github.com/aws/aws-sdk-go-v2/blob/v1.46.0/aws/credential_cache.go) refreshes on retrieval when credentials expire; its default expiry window is zero, so do not describe this configuration as a proactive background refresh timer.

Recommended acceptance procedure:

1. Start one Go process on the Pi with `config.LoadDefaultConfig` and one STS client; retain them throughout the test.
2. Retrieve credentials, assert the process-provider source, `CanExpire`, nonempty session token, and approximately 900 seconds remaining; call GetCallerIdentity and compare account/role to expected values in memory.
3. Record only boolean identity match, provider name, expiration timestamps, and operation success, never the credential values or returned account/ARN.
4. Keep making STS calls through the original client at a bounded interval through the first expiration plus a margin, without cache invalidation or reloading configuration.
5. Verify the access key changed in memory and the new expiration advanced while all identity checks still match; log only `credentials_changed=true` and timestamps.
6. Repeat after supervised certificate renewal, checking the leaf serial changed and that a subsequent helper invocation succeeds; preserve the same-key and stable-intermediate assumptions.

Repeated CLI launches or forced cache invalidation are useful smoke tests but do not demonstrate automatic expiration-driven SDK refresh.
Do not log unfiltered provider errors in the probe: its JSON parse-error path can include process stdout, which could contain credentials.
Report a sanitized error class and exit unsuccessfully instead. [Provider error implementation](https://github.com/aws/aws-sdk-go-v2/blob/credentials/v1.20.3/credentials/processcreds/provider.go)

## Remaining decisions and boundaries

No researched requirement conflicts with the approved architecture, and no additional permanent dependency is needed.
Root public certificate versus intermediate public certificate is not explicit in the AWS plan's generic CA wording; using the existing public root as trust anchor plus exact intermediate CN is consistent with the prior rotation research and leaves root-key custody unchanged.
Name that choice in the concrete AWS resource plan.
Actual issuer CN, device CN, runtime user, resource ARNs, and final live filenames are deployment facts to inspect, not reasons to invent a new interface.
The plan already requires choosing consumer identity-file access explicitly during integration.
S3 policy, bucket choice, telemetry queue, and permanent monitoring resources remain outside this authentication unit.
