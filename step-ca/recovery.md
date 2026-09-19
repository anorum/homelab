# Issuer state recovery

A root-key backup does not preserve the issuer's database.
Badger records revocations and consumed enrollment tokens, so recovery must restore the matching database, CA configuration, intermediate key, and unlock password together.

## Snapshot format and location

Snapshots live outside the cluster in the owner-only Mac directory `~/.local/share/homelab-telemetry-ca/backups/`.
Each `issuer-state-TIMESTAMP.enc.yaml` is a SOPS-encrypted document containing a Kubernetes Secret-shaped envelope with one `data.archive` field.
That field holds a base64-encoded gzip tar archive of `config/`, `secrets/`, and `db/` from `/home/step`.
The envelope is a storage format; do not apply it as a Kubernetes Secret.
The archive includes public root/intermediate certificates and the online intermediate's credentials, but never the root private key or enrollment-signing credentials.

Encrypt with the existing homelab SOPS age recipient from `.sops.yaml`.
When piping the envelope to SOPS, specify `--filename-override step-ca/state.enc.yaml` so the repository's creation rule matches stdin.
Keep all plaintext archive processing in pipes or process memory; store only the encrypted snapshot on the Mac.
The age decryption identity remains with the existing homelab secret-management setup.
A complete cluster-loss recovery also depends on recovering that identity; this exercise verified recovery from issuer-volume loss using the existing cluster identity, not recovery of the age identity itself.

## Cold snapshot procedure

1. Create a uniquely named temporary reader pod using the pinned issuer image, the same ConfigMap and Secret, and the database PVC mounted read-only.
   Give it a different label from `app=step-ca` so it cannot receive issuer traffic.
2. Temporarily annotate only the issuer Application with `argocd.argoproj.io/skip-reconcile=true`, then scale its Deployment to zero and wait for every issuer pod to terminate.
   The [ArgoCD annotation](https://argo-cd.readthedocs.io/en/stable/user-guide/skip_reconcile/) prevents automated self-healing from restarting the database writer during the snapshot.
3. From the reader pod, run `tar czhf - -C /home/step config secrets db` and encrypt the resulting archive in the format above.
   The `h` option dereferences the Kubernetes volume symlinks so the archive contains the actual configuration and secret files.
4. In cleanup that runs even on failure, restore one issuer replica, remove the skip-reconcile annotation, delete the reader pod, and verify rollout and pinned-root HTTPS.
   Confirm temporary pods actually disappear before reusing any names.

This is a tested manual recovery procedure, not a scheduled backup job.
Take a new snapshot after security-state changes such as revocations; an older snapshot loses changes made after it was taken.
Do not leave reconciliation paused or take a live file copy while Badger is writing.

## Isolated restore verification

Decrypt through the existing SOPS identity and extract into an empty volume mounted at `/home/step` in a uniquely named test pod.
The real database PVC must not be mounted in that pod.
When using ArgoCD's KSOPS runtime, copy the repository's existing exec-generator annotations from `step-ca/secret-generator.yaml`; a bare plugin declaration does not select the installed exec plugin.
Keep the restored issuer off the Service selector and expose no additional LoadBalancer.
Start the pinned issuer against the restored paths, then reach its pod port through the trusted control node while preserving the CA hostname and root verification.

Before the snapshot, consume a five-minute enrollment token and retain it only for the recovery check.
After restore, confirm that token is still unexpired and receives HTTP 401, while a fresh operator token can enroll successfully with HTTP 201.
This distinguishes preserved replay state from a rejection caused merely by token expiration.
Remove the test pod, restored plaintext state, temporary CSR/key/token, and KSOPS input directory afterward.

## Verified result

On 2026-09-19, `issuer-state-20260919T184105Z.enc.yaml` was created and restored with this procedure.
The decrypted archive matched the original archive's SHA256, restored HTTPS became healthy, the unexpired consumed token received 401, and a fresh token received 201.
The live issuer was healthy afterward, GitOps reconciliation was restored, and temporary snapshot/restore pods and material were removed.
This verifies the encrypted snapshot and its recovery path; it does not establish automated backup scheduling or an entire-cluster disaster recovery guarantee.
