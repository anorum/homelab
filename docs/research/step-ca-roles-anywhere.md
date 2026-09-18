# step-ca renewal with IAM Roles Anywhere

Research date: 2026-09-18.
Scope: open-source step-ca, step CLI, and file-based aws_signing_helper credential-process on a Raspberry Pi.
Evidence is official documentation and source inspection, not an executed interoperability test.
Source links to branch heads are mutable; pin actual release versions and recheck their source before implementation.

## Conclusion

Yes, the components support automated same-key renewal, subject to safe file publication and a tested end-to-end credential refresh.
Do not point the renewal command directly at the live certificate: its write path is not atomic.
The smallest proposed implementation is a systemd oneshot timer that renews into a staging file, validates the result, and atomically replaces the live certificate while retaining the existing private key and intermediate.
Issuer hosting and key custody remain a separate plan; no CA, AWS resource, key, or host was provisioned during this research.
The proposed 90-day certificate and renewal beginning 30 days before expiry accommodate the stated week-long offline period; they are a project choice, not a production standard.

## Verified lifecycle mechanics

`step ca renew` retains the existing key; `step ca rekey` is the separate key-changing operation.
The CA copies RawSubject, key usage, EKU, and SAN attributes from the old certificate, preserving the subject CN while issuing a new certificate with a shifted validity window.
The CA computes renewal lifetime from the old certificate's validity minus configured backdate, so changing an issuance template or default duration should not be assumed to retrofit existing certificates through renewal.
These behaviors are visible in [Authority.RenewContext and renewContext](https://github.com/smallstep/certificates/blob/master/authority/tls.go#L319).

The CLI writes the returned certificate chain to the output file and leaves the key file untouched.
Daemon startup loads the key/certificate once and calculates the next attempt from certificate expiry; an overdue renewal schedules immediately.
The default threshold is approximately one third of lifetime remaining, with earlier jitter.
On renewal failure the daemon retries after one minute, without exponential backoff.
SIGTERM/SIGINT stop it; SIGHUP requests renewal.
Successful renewal updates its in-memory certificate and runs an optional hook; hook failure is logged but does not cause immediate renewal retry.
These details follow [renew.go](https://github.com/smallstep/cli/blob/master/command/ca/renew.go#L288).
Use systemd to restart a crashed daemon if choosing daemon mode; the documentation instead prefers periodic systemd oneshot timers and also documents the retry behavior. [Renewal operations](https://smallstep.com/docs/step-ca/renewal/)

For the proposed timer, `--expires-in 720h` expresses 30 days because the CLI accepts hours, not a `d` suffix.
One-shot renewal skips with success when too early; the wrapper must distinguish a skipped command from a newly produced staging file.
`--out` selects a separate output path, and `--force` makes overwrites noninteractive. [Renew command reference](https://smallstep.com/docs/step-cli/reference/ca/renew/)
Recommendation: create a fresh staging location per attempt and only publish an output that exists and validates; never reuse stale staged output.

## Atomic publication and helper reload

`fileutil.WriteFile` delegates to `os.WriteFile`, including when force is enabled. [Smallstep write implementation](https://github.com/smallstep/cli-utils/blob/main/fileutil/write.go#L36)
That is a truncate-and-write path, not a temporary-file-and-rename operation; a reader or crash can observe an empty or partial certificate.
Recommendation: renew with `--out` into a private staging path on the same filesystem, validate parsing, expected CN, public-key match, validity, clientAuth EKU, digitalSignature usage, and expected issuer chain, then use same-filesystem atomic rename.
The existing live certificate remains usable after failed renewal or validation.
Set ownership and modes before publication, serialize renewal attempts, and apply a finite service timeout.
If power-loss durability is a requirement, flush the staged file and parent directory appropriately; atomic visibility alone is not a durability guarantee.

`credential-process` creates a signer and obtains credentials on each invocation. [Credential process source](https://github.com/aws/rolesanywhere-credential-helper/blob/main/cmd/credential_process.go)
The filesystem signer rereads certificate/key/bundle files during its operations, rather than requiring a service reload. [Filesystem signer](https://github.com/aws/rolesanywhere-credential-helper/blob/main/aws_signing_helper/file_system_signer.go)
Inference: same-key renewal under an unchanged intermediate permits an invocation to see either old or new valid leaf without a key mismatch.
This inference still requires a concurrent helper-invocation test with the pinned release.
Do not generalize it to rekeying or issuer rotation, where independently replaced files can describe different generations.

## AWS certificate and chain requirements

Roles Anywhere requires an X.509v3 end entity with digitalSignature usage, CA=false if that basic constraint is present, and SHA256-or-stronger certificate signing.
The official constraint list does not require a particular EKU; clientAuth is needed for the proposed step-ca mTLS renewal path.
Use a nonempty, stable device CN and restrict the role trust policy to that CN and the selected trust-anchor ARN.
AWS derives identity attributes from the certificate subject, so preserved CN keeps the intended identity stable across renewal. [AWS trust model](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/trust-model.html)

`--intermediates` explicitly supplies the helper's intermediate PEM bundle. [Credential helper reference](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/credential-helper.html)
Do not assume passing a step full-chain file only as `--certificate` transmits its intermediates: the helper reads the leaf separately and obtains the chain from its bundle path. [Filesystem signer](https://github.com/aws/rolesanywhere-credential-helper/blob/main/aws_signing_helper/file_system_signer.go)
The certificate parser decodes the first certificate, while the bundle reader parses the certificate sequence. [Helper parsers](https://github.com/aws/rolesanywhere-credential-helper/blob/main/aws_signing_helper/signer.go#L629)
For the first unit, keep the intermediate stable and pass its explicit bundle; reject a renewed certificate from an unexpected issuer until a planned rotation updates the helper inputs consistently.

## Expiry and transport boundaries

The CA normally rejects renewal after expiry; its authorization check also rejects not-yet-valid certificates and disabled renewal.
The default check compares current time truncated to seconds against NotAfter using `After`, but transport verification and client timing differ, so do not depend on equality at the expiry instant. [Renew authorization source](https://github.com/smallstep/certificates/blob/master/authority/provisioner/controller.go#L162)
The CLI switches to certificate-signed token renewal when the certificate has expired. [RenewWithToken source](https://github.com/smallstep/cli/blob/master/command/ca/renew.go#L450)
That does not bypass CA policy: renewal-after-expiry requires explicit provisioner enablement and is disabled by default. [Renewal operations](https://smallstep.com/docs/step-ca/renewal/)
Recommendation: leave that exception disabled initially, alert well before expiry, and document operator-assisted reenrollment for outages exceeding the remaining certificate lifetime.

Default renewal uses mTLS and needs a clientAuth-capable leaf and a TLS connection that reaches step-ca.
A Kubernetes L4 endpoint or TLS passthrough preserves this; ordinary L7 TLS termination does not.
`--mtls=false` provides a supported signed-token alternative, with trusted HTTPS and CA/proxy DNS audience alignment still required. [Renew reference](https://smallstep.com/docs/step-cli/reference/ca/renew/), [Proxy guidance](https://smallstep.com/docs/step-ca/certificate-authority-server-production/#proxying-step-ca-traffic)

## Root and intermediate rotation

The root private key is not needed for daily CA operation and can remain offline, outside both Pi and cluster.
Step bundles the issuing intermediate with each leaf and replaces the chain during renewal; changing an intermediate therefore can change the renewal output even when the leaf key stays constant.
Root replacement requires an overlap period with both trust roots accepted. [Smallstep production guidance](https://smallstep.com/docs/step-ca/certificate-authority-server-production/#rotating-ca-certificates)
Plan rotations explicitly: coordinate Pi CA trust, helper intermediate bundle, AWS trust-anchor contents, and any issuer-based authorization conditions before switching issuance.
A root trust anchor can accommodate a new intermediate chaining to that root; an intermediate trust anchor requires its own coordinated AWS change.
This last point follows the AWS chain-to-trust-anchor validation model, but exact rotation sequencing remains an integration test. [AWS trust model](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/trust-model.html)
Do not infer that leaf renewal rotates roots or maintains the AWS trust anchor automatically.

## Minimal acceptance tests, still unexecuted

Use an isolated test issuer with an explicitly permitted 10-minute leaf lifetime, a 4-minute renewal threshold, and a short timer interval; configure any CA minimum duration and clock backdate deliberately.
1. Obtain real Roles Anywhere credentials, renew twice, and obtain credentials again; inspect unchanged CN/public key/EKU, changed serial/expiry, and successful intended AWS operation through the actual SDK credential_process path.
2. Invoke the helper repeatedly across publication and verify no PEM failures, key mismatch, or malformed credential JSON; ensure secrets never enter test logs.
3. Make the issuer unavailable before threshold, restore it before expiry, and verify scheduled recovery, retained live certificate, and successful new AWS credentials without manual restart.
4. Restart the host-side renewal service after threshold, test failed writes and malformed staging output, and confirm old live material remains usable with visible nonzero failure status.
5. Leave the issuer unavailable past expiry, verify failure is visible and default renewal stays denied, then exercise the documented operator recovery path.
6. Verify direct/L4 mTLS renewal and confirm an L7 deployment only succeeds with the explicitly selected token flow and correct hostname/trust settings.
Issuer/root rotation and rekeying require separate tests before enabling those operations; they are outside the initial same-key renewal unit.
