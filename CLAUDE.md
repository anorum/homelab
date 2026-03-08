# Homelab Kubernetes Cluster

## Architecture Overview

2-node k3s cluster on Raspberry Pi 5 hardware, managed via GitOps with ArgoCD.

### Nodes
| Node | Role | IP | Notes |
|------|------|----|-------|
| swagman-1 | Master | 192.168.1.101 | Control plane, SSH key `~/.ssh/rpi_key`, requires `sudo kubectl` |
| swagman-2 | Worker | 192.168.1.102 | 12TB HDD at `/mnt/hd` |
| Mac Mini | External | 192.168.1.105 | Runs Ollama (not a k8s node) |

### Networking
- **MetalLB**: L2 mode, Traefik LoadBalancer at 192.168.1.151
- **Traefik**: Gateway API provider. Single Gateway `homelab-gateway` in `traefik` namespace with `sectionName: web`
- **Gateway API**: All services use HTTPRoute (NOT Ingress). Routes reference `parentRefs: [{name: homelab-gateway, namespace: traefik, sectionName: web}]`
- **Cloudflared**: Tunnel for external access via Cloudflare
- **DNS**: AdGuard (192.168.1.150) with `*.home.alexnorum.com` wildcard rewrite to 192.168.1.151
- **Tailscale**: Subnet router on both Pis, advertises 192.168.1.0/24 for remote access
- **External access**: sso.alexnorum.com and argo.alexnorum.com via Cloudflare Tunnel

### Authentication
- **Authentik**: SSO/IdP at sso.alexnorum.com
- **OAuth/OIDC**: Configured for Grafana (`grafana.ini` generic_oauth) and ArgoCD (Dex connector)
- **Forward auth**: Traefik middleware for Prometheus, Alertmanager (defined per-namespace as needed)
- **Blueprints**: Authentik providers defined as ConfigMaps mounted into the Authentik deployment (see `authentik/*-blueprint.yaml`)

### Secret Management
- **SOPS + Age** encryption. Public key in `.sops.yaml`
- **Naming convention**: Encrypted files are `*.enc.yaml` (matched by `.sops.yaml` creation_rules regex)
- **KSOPS generators**: Files named `*-secret-generator.yaml` reference `*.enc.yaml` files for decryption
- **ArgoCD integration**: repo-server has KSOPS + age key via init container (`argo-cd/ksops-patch.yaml`)
- **Kustomize build flags**: `--enable-helm --enable-alpha-plugins --enable-exec` (set in argocd-cm)
- **Bootstrap**: `scripts/bootstrap-cluster.sh` manually decrypts secrets for initial deploy before ArgoCD is running
- **Repo is public** on GitHub — all secrets MUST be SOPS-encrypted

### Storage
| StorageClass | Provisioner | Location | Used By |
|-------------|-------------|----------|---------|
| `local-path` | k3s default | Node-local (SD card) | Prometheus, Grafana, Open WebUI, AdGuard, Authentik |
| `local-hdd-storage` | manual (`no-provisioner`) | `/mnt/hd` on swagman-2 | Mealie, Loki |

- Single 11Ti PV `hdd-pv` with Retain reclaim policy and nodeAffinity to swagman-2
- Defined in `storage/storage.yaml`

### Deployment Model
1. **App-of-apps**: `argo-cd/app-of-apps.yaml` deploys `argo-apps/applications.yaml`
2. Each service is a separate ArgoCD Application pointing to its directory in this repo
3. All apps use automated sync with `prune: true` and `selfHeal: true`
4. Prometheus app has extra syncOptions for CRD handling (`ServerSideApply`, `SkipDryRunOnMissingResource`)
5. Source repo: `git@github.com:anorum/homelab.git` at HEAD

### Active ArgoCD Apps
adguard, authentik, cloudflared, homepage, loki, mealie, metallb, ollama, open-webui, prometheus, traefik, uptime-kuma

### Monitoring Stack
- **Prometheus**: kube-prometheus-stack v82.2.1, 7d retention, 5Gi storage
- **Grafana**: OAuth via Authentik, Loki + Prometheus datasources
- **Loki**: Single-binary mode with Promtail, 14d retention, 20Gi on HDD
- **Alertmanager**: Discord webhook alerts, custom homelab rules in `prometheus/homelab-rules.yaml`
- **Uptime Kuma**: External uptime monitoring

## Directory Conventions

Each service has its own directory at repo root:
```
<service>/
  kustomization.yaml   # Always present, sets namespace
  namespace.yaml       # Namespace definition
  httproute.yaml       # Gateway API HTTPRoute (if web-accessible)
  deployment.yaml      # Deployment/StatefulSet
  service.yaml         # Service
  pv.yaml, pvc.yaml    # If using persistent storage
  values.yaml          # Helm values (if using helmCharts in kustomization)
  *-secret-generator.yaml + *.enc.yaml  # SOPS secrets via KSOPS
  *-blueprint.yaml     # Authentik blueprints (ConfigMaps, authentik/ only)
```

Helm charts are referenced inline in `kustomization.yaml` under `helmCharts:` — not as separate Helm releases.

## Common Operations

### Add a new service
1. Create `<service>/` directory with `kustomization.yaml`, `namespace.yaml`
2. Add deployment, service, and other resources
3. If web-accessible: add `httproute.yaml` referencing `homelab-gateway` in traefik namespace
4. If secrets needed: create `secret.enc.yaml` with `sops -e`, add KSOPS generator yaml
5. Add Application entry to `argo-apps/applications.yaml` (follow existing pattern)
6. Git push — ArgoCD auto-syncs within ~3 minutes

### Encrypt a secret
```bash
# Create plaintext secret yaml, then encrypt
sops -e secret.yaml > secret.enc.yaml
# Or edit encrypted file directly
sops secret.enc.yaml
```

### Expose an external service (not running in k8s)
See `ollama/service.yaml` for the pattern: headless Service + manual EndpointSlice pointing to external IP.

### Bootstrap from scratch
1. Flash Raspberry Pi OS on both Pis, configure IPs
2. `ansible-playbook -i ansible/inventory/hosts.yaml ansible/roles/k3s/tasks/master.yaml` (then workers)
3. `./scripts/bootstrap-cluster.sh` (MetalLB -> Traefik -> Storage -> ArgoCD -> Apps -> Secrets)
4. ArgoCD syncs everything from git automatically

### Access services locally
All at `*.home.alexnorum.com` resolving to 192.168.1.151. Configure via AdGuard DNS or `/etc/hosts`.

## External Services
- **Ollama** on Mac Mini (192.168.1.105:11434) — exposed to cluster via headless Service + EndpointSlice in `ollama/service.yaml`

## Inactive Components
- `not_in_use/` — deprecated configs kept for reference (jellyfin, airflow, plex, pihole, etc.)
- `home-assistant/` — has blueprints/configs but HA not currently deployed in cluster

## Key Files
| File | Purpose |
|------|---------|
| `scripts/bootstrap-cluster.sh` | Full cluster bootstrap after ansible |
| `argo-apps/applications.yaml` | All ArgoCD Application definitions |
| `argo-cd/kustomization.yaml` | ArgoCD config (OIDC, RBAC, KSOPS patch) |
| `.sops.yaml` | SOPS encryption rules (age public key) |
| `storage/storage.yaml` | StorageClass + 11Ti PV definition |
| `prometheus/kustomization.yaml` | Full monitoring stack config (Prometheus, Grafana, Alertmanager, Loki datasource) |
| `traefik/gateway.yaml` | Gateway definition for all HTTPRoutes |
