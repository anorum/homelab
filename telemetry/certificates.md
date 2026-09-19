# Device certificate renewal

Status: renewal client verified on `swagman-2` with a disposable issuer on 2026-09-18.
The real issuer, device credentials, timer installation, expiry alerts, and AWS authentication are not deployed.
See the [issuer plan](../docs/plans/2026-09-18-certificate-issuer.md) for those remaining steps.
Root-key custody is settled: an encrypted file on Alex's Mac with a password-manager backup.
Root and intermediate material now exist on the Mac.
The current interactive step checks agent-prepared local copies in Downloads; off-device backup remains unverified.

## Bootstrap custody

Bootstrap material lives outside this repository under `~/.local/share/homelab-telemetry-ca`, with directory mode `0700` and secret-file mode `0600`.
The root key is encrypted with a password entered locally and kept in the password manager.
Its password is used through a temporary owner-only file during bootstrap and removed when the setup exits.
The intermediate and enrollment authority use separate generated passwords; those operational passwords are owner-only files on the Mac during bootstrap.
Only the intermediate key and its unlock password are destined for the cluster's SOPS-encrypted secret manifest.
The root key/password and enrollment password must not be copied to the cluster.
The root certificate is public and can be copied to the issuer, Pi, and AWS trust anchor.

The one-time setup uses Smallstep's [existing-root initialization](https://smallstep.com/docs/step-cli/reference/ca/init/) to keep root and intermediate protection separate.
A disposable-key check with `step` 0.30.6 verified that initialization does not copy the root private key into the issuer directory, and that the intermediate password cannot decrypt the root key.
Back up the encrypted root key and its public certificate as attachments in the password manager, along with the root password.
Download both attachments and verify the key decrypts and matches the certificate before deploying the issuer.
This root backup is separate from the planned backup of issuer configuration, credentials, and database state.

## What runs on the Pi

`systemd timer -> renew-certificate.sh -> step ca renew -> private step-ca endpoint`

The timer checks hourly with up to five minutes of jitter, catches missed calendar runs, and also checks after boot.
The shell wrapper holds a file lock, verifies the existing identity, and gives the Smallstep client 60 seconds to renew into a fresh staging directory beside the live certificate.
It checks the returned certificate's chain, exact device subject, issuer, key, usages, and validity before replacing the live certificate with a same-filesystem rename.
The replacement must expire later than the current certificate.
Readers see the complete old or new file; this does not promise durability after sudden storage or power failure.
The private key remains unchanged.

Renewal starts with 30 days left on a 90-day device certificate.
An unavailable issuer causes a visible service failure and leaves the existing certificate in place; the next scheduled run retries.
An expired certificate requires operator-assisted re-enrollment.
The issuer cannot recover samples that were never collected while the Pi was powered off.

## Runtime contract

The service reads `/etc/telemetry/certificate.env`, which contains paths and public identity settings, never private key contents.
The service currently runs as root, with a read-only filesystem except for `/var/lib/telemetry/identity`.
The credential consumer's runtime account and access must be set explicitly when integrating the AWS helper; do not make the private key world-readable to accommodate it.

```ini
CERTIFICATE=/var/lib/telemetry/identity/device.crt
PRIVATE_KEY=/var/lib/telemetry/identity/device.key
ROOT_CERTIFICATE=/etc/telemetry/root_ca.crt
INTERMEDIATE_CERTIFICATE=/etc/telemetry/intermediate_ca.crt
DEVICE_CN=pi-<board-serial>
CA_URL=https://ca.home.alexnorum.com
RENEW_BEFORE=720h
```

The identity directory and key must be owned by the renewal account with modes `0700` and `0600` respectively.
The wrapper installs certificates with mode `0600` and requires a subject containing only the expected CN.
The root and intermediate certificates are trusted inputs installed during enrollment, not downloaded opportunistically during renewal.
The wrapper requires Linux Bash, OpenSSL, GNU coreutils, and flock, all found on `swagman-2` during discovery.
Install the pinned `step` binary at `/usr/local/bin/step` and the wrapper at `/usr/local/libexec/telemetry/renew-certificate.sh` when the issuer and enrollment procedure are ready.
Service and timer files are in [systemd](systemd/).
Do not enable the timer before enrollment and live endpoint verification.

Output reports `certificate_expires_at_seconds`, plus `renewal=not_due` or `renewal=published` on success.
Failures exit nonzero and retain the live certificate.
These journal messages are diagnostic evidence, not a configured expiry alert.
The monitoring integration remains a design decision before unattended deployment is complete.

The AWS helper must later receive the intermediate explicitly with `--intermediates`.
Normal renewal assumes the same intermediate and private key.
Rekeying, changing issuers, and rotating roots need a coordinated procedure covering the Pi trust files and AWS trust configuration; this script intentionally rejects an unexpected issuer or key.

## Reproduce the isolated test

Use Linux ARM64 `step` 0.30.6 and `step-ca` 0.30.2 from their official [CLI release](https://github.com/smallstep/cli/releases/tag/v0.30.6) and [CA release](https://github.com/smallstep/certificates/releases/tag/v0.30.2).
Verify the archives against each release's `checksums.txt` before extraction.

| Archive | SHA-256 |
|---|---|
| `step_linux_0.30.6_arm64.tar.gz` | `eff511c3e6797039702e74fada62b10b079e413742f925703e5b7d810e611619` |
| `step-ca_linux_0.30.2_arm64.tar.gz` | `43f79d1b0b8cab9895dbadd46b0a014006f682a6b1341e1fadf0be31d4b9f4b4` |

With those binaries on `PATH`, run from the repository root:

```sh
python3 telemetry/tests/test_renewal.py
bash -n telemetry/renew-certificate.sh
```

The tests create temporary CA/device keys, bind the issuer to a free loopback port, exercise renewal and failure cases, and clean up their processes and temporary credentials.
They do not use AWS or the real device identity.
Short test certificates use a proportionally shorter renewal threshold; Smallstep requires that threshold to be shorter than the certificate lifetime.
Smallstep's default leaf omits the optional basicConstraints field; validation accepts that omission and rejects `CA:TRUE`.
Tests cover successful same-key renewal, early checks, issuer outage/recovery, expiry, wrong identity, invalid client output, interruption, and concurrent invocation.
They exercise the wrapper directly; installed systemd scheduling and the real issuer remain separate acceptance checks.

Latest verification: `python3 telemetry/tests/test_renewal.py` passed all eight tests in 39.625 seconds on the Pi.
`bash -n telemetry/renew-certificate.sh` and `git diff --cached --check` passed.
On the Pi, `systemd-analyze verify --man=no` accepted both units after substituting only the temporary test script's path for `ExecStart`; no units were installed or enabled.
The simplification pass and fresh-context standards/spec reviews found no remaining issues in this client slice.
