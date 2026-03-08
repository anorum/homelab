# Disaster Recovery

## What's Protected by GitOps (No Backup Needed)

Everything in this git repo auto-recovers via ArgoCD:
- All Kubernetes manifests, Kustomizations, Helm values
- SOPS-encrypted secrets (`.enc.yaml` files)
- ArgoCD Application definitions
- Alerting rules, HTTPRoutes, blueprints

**You just need the git repo + the age decryption key to rebuild the entire cluster.**

## Critical Items to Back Up Offsite

These are NOT in git and would be lost if your local machine dies:

| Item | Location | How to Back Up |
|------|----------|---------------|
| Age decryption key | `~/.config/sops/age/keys.txt` | Copy to password manager or secure cloud storage |
| SSH key for Pis | `~/.ssh/rpi_key` | Copy to password manager |
| GitHub deploy key | Generated per-repo | Re-generate if lost (update repo settings) |
| Tailscale auth key | Tailscale admin console | Can re-generate |

**Without the age key, you cannot decrypt any secrets.** This is the single most critical item to back up.

## Stateful Data (Needs Backup)

| Service | Data Location | Storage | Priority | Notes |
|---------|--------------|---------|----------|-------|
| Mealie | `/mnt/hd/mealie` on swagman-2 | local-hdd-storage | High | Recipes, user data |
| Authentik | PostgreSQL PVC on swagman-? | local-path | High | Identity provider, SSO config, all OAuth providers |
| Grafana | PVC on local-path | local-path | Medium | Custom dashboards (default ones regenerate from helm) |
| AdGuard | PVC on local-path | local-path | Medium | DNS config, rewrites (can rebuild from configmap) |
| Open WebUI | PVC on local-path | local-path | Medium | Chat history, user preferences — backed up daily to S3 |
| Loki | `/mnt/hd/loki` on swagman-2 | local-hdd-storage | Low | Logs are ephemeral (14d retention) |
| Prometheus | PVC on local-path | local-path | Low | Metrics repopulate (7d retention) |

## Recovery Scenarios

### Scenario A: swagman-1 (master) dies

The master node runs the control plane. Worker data on swagman-2 is intact.

1. Get a new Pi, flash Raspberry Pi OS
2. Set hostname to `swagman-1`, static IP `192.168.1.101`
3. Run ansible master role:
   ```bash
   ansible-playbook -i ansible/inventory/hosts.yaml ansible/roles/k3s/tasks/master.yaml
   ```
4. Run bootstrap script:
   ```bash
   ./scripts/bootstrap-cluster.sh
   ```
5. ArgoCD auto-syncs all apps from git
6. swagman-2 may need to be re-joined (new join token from master):
   ```bash
   # On swagman-1, get the new token
   sudo cat /var/lib/rancher/k3s/server/node-token
   # On swagman-2, update and restart k3s agent
   ```

**Recovery time**: ~30 minutes (mostly waiting for pods to start on ARM)

### Scenario B: swagman-2 (worker) dies, HDD survives

swagman-2 has the 12TB HDD with Mealie and Loki data.

1. New Pi, flash OS, set hostname `swagman-2`, IP `192.168.1.102`
2. Mount the HDD at `/mnt/hd` (same as before)
3. Run ansible worker role to join cluster:
   ```bash
   ansible-playbook -i ansible/inventory/hosts.yaml ansible/roles/k3s/tasks/workers.yaml
   ```
4. PVs with nodeAffinity to swagman-2 will rebind automatically
5. Pods using `local-path` storage that were on swagman-2 will get new empty PVCs

**Recovery time**: ~20 minutes

### Scenario C: swagman-2 dies AND HDD fails

Worst case for data — all HDD data is lost.

1. New Pi + new HDD, mount at `/mnt/hd`
2. Join cluster (same as Scenario B)
3. ArgoCD syncs all apps (they'll start with empty data)
4. Restore from backup:
   - Mealie: `aws s3 sync s3://anorum-homelab/backups/mealie/ /mnt/hd/mealie/`
   - Loki: starts fresh (acceptable — logs are ephemeral)
5. Authentik may need reconfiguration if its PVC was also on swagman-2

**Recovery time**: ~1 hour including data restoration

### Scenario D: Both nodes die, HDD intact

Full rebuild.

1. Ensure you have: age key, SSH key, access to GitHub repo
2. Flash both Pis, set hostnames and IPs
3. Mount HDD on new swagman-2 at `/mnt/hd`
4. Run full ansible playbook:
   ```bash
   ansible-playbook -i ansible/inventory/hosts.yaml ansible/roles/k3s/tasks/all.yaml
   ```
5. Run bootstrap:
   ```bash
   ./scripts/bootstrap-cluster.sh
   ```
6. ArgoCD syncs everything. HDD data is preserved.

**Recovery time**: ~45 minutes

### Scenario E: Complete loss (both nodes + HDD)

1. New hardware, fresh OS, same IPs and hostnames
2. New HDD mounted at `/mnt/hd`
3. Clone repo: `git clone git@github.com:anorum/homelab.git`
4. Restore age key from password manager to `~/.config/sops/age/keys.txt`
5. Run ansible + bootstrap (same as Scenario D)
6. Restore data from S3: `aws s3 sync s3://anorum-homelab/backups/ /tmp/restore/`
7. Reconfigure Authentik (create admin user, re-apply blueprints)
8. Update Cloudflare Tunnel config if IPs changed

**Recovery time**: ~2 hours

## Backup Strategy

### Automated: S3 daily backup (k8s CronJob)

A k8s CronJob (`homelab-backup` in `backup` namespace) runs daily at 3 AM, managed by ArgoCD.

**What gets backed up:**
- Mealie data (`aws s3 sync` from hostPath `/mnt/hd/mealie` on swagman-2)
- Authentik PostgreSQL dump (`pg_dump` via `kubectl exec`, uploaded to S3)
- Open WebUI SQLite DB (`kubectl cp` from pod, uploaded to S3)

**S3 bucket:** `s3://anorum-homelab/backups/`
- `backups/mealie/` — full sync of Mealie data
- `backups/authentik/YYYY-MM-DD.sql` — daily pg dumps
- `backups/open-webui/YYYY-MM-DD.db` — daily SQLite snapshots

**Retention:** Mealie is a live sync. Authentik and Open WebUI keep 7 daily backups.

**AWS credentials:** IAM user `homelab-backup` managed by Terragrunt/OpenTofu in `terraform/homelab/`. Credentials stored as a SOPS-encrypted k8s Secret.

**Manual trigger:**
```bash
kubectl create job --from=cronjob/homelab-backup -n backup manual-backup-$(date +%s)
```

**Check backup logs:**
```bash
kubectl logs -n backup -l job-name --tail=100
```

**Check S3 contents:**
```bash
aws s3 ls s3://anorum-homelab/backups/mealie/ --summarize
aws s3 ls s3://anorum-homelab/backups/authentik/
aws s3 ls s3://anorum-homelab/backups/open-webui/
```

### Restoring from S3 Backup

**Mealie:**
```bash
# Sync data back from S3 to swagman-2
aws s3 sync s3://anorum-homelab/backups/mealie/ /mnt/hd/mealie/
# Or from a remote machine:
ssh -i ~/.ssh/rpi_key anorum@192.168.1.102 "aws s3 sync s3://anorum-homelab/backups/mealie/ /mnt/hd/mealie/"
```

**Authentik PostgreSQL:**
```bash
# Download the latest dump
aws s3 cp s3://anorum-homelab/backups/authentik/YYYY-MM-DD.sql /tmp/authentik-restore.sql

# Restore into the pod
cat /tmp/authentik-restore.sql | \
  kubectl exec -i -n authentik authentik-postgresql-0 -- \
  bash -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -U authentik authentik'
```

**Open WebUI:**
```bash
# Download the latest SQLite backup
aws s3 cp s3://anorum-homelab/backups/open-webui/YYYY-MM-DD.db /tmp/webui.db

# Copy into the pod and restart
OW_POD=$(kubectl get pod -n open-webui -l app=open-webui -o jsonpath='{.items[0].metadata.name}')
kubectl cp /tmp/webui.db "open-webui/$OW_POD:/app/backend/data/webui.db"
kubectl rollout restart deployment/open-webui -n open-webui
```

## Testing Recovery

Periodically verify:
1. Age key can decrypt secrets: `sops -d authentik/secret.enc.yaml`
2. SSH key works: `ssh -i ~/.ssh/rpi_key anorum@192.168.1.101`
3. Bootstrap script is up to date with current apps
4. S3 backups are recent: `aws s3 ls s3://anorum-homelab/backups/authentik/`
5. CronJob is running: `kubectl get cronjobs -n backup`
