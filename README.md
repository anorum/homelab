# Home Lab Kubernetes Cluster

My personal Kubernetes cluster running on Raspberry Pi 5. This repository contains the configuration and deployment files for various services running in my homelab.

## Overview

This is a k3s-based Kubernetes cluster running on Raspberry Pi 5 hardware managed via GitOps with Argo CD. Everything is defined as code — push to `main` and ArgoCD syncs the cluster automatically.

See [CLAUDE.md](CLAUDE.md) for detailed architecture documentation.

## Core Components

### Infrastructure
- **k3s**: Lightweight Kubernetes distribution (2 nodes)
- **MetalLB**: L2 load balancer for bare metal Kubernetes
- **Traefik**: Ingress via Gateway API (HTTPRoute)
- **Cloudflared**: Cloudflare tunnel for secure external access
- **SOPS + Age**: Secret encryption with KSOPS generators
- **Argo CD**: GitOps app-of-apps pattern with auto-sync

### Applications
- **Prometheus + Grafana**: Metrics, dashboards, and alerting (Discord)
- **Loki + Promtail**: Log aggregation
- **Alertmanager**: Alert routing to Discord
- **Uptime Kuma**: Uptime monitoring
- **AdGuard**: Network-wide DNS filtering
- **Mealie**: Recipe management and meal planning
- **Authentik**: Identity provider and SSO (OAuth/OIDC for Grafana, ArgoCD)
- **Homepage**: Dashboard for services
- **Ollama**: Self-hosted AI model server (runs on Mac Mini)
- **Open WebUI**: Chat interface for Ollama

## Installation

The cluster is bootstrapped using Ansible playbooks:

1. Initial K3s setup:
```bash
ansible-playbook -i inventory/hosts.yaml playbook/install-k3s.yaml
```

2. Cloudflared deployment:
```bash
ansible-playbook -i inventory/hosts.yaml playbook/deploy-cloudflared.yaml
```

## Directory Structure

```
.
├── adguard/            # AdGuard DNS configuration
├── ansible/            # Ansible playbooks and roles for k3s setup
├── argo-apps/          # ArgoCD Application definitions (app-of-apps)
├── argo-cd/            # ArgoCD configuration, OIDC, KSOPS
├── authentik/          # Identity provider, SSO, OAuth blueprints
├── cloudflared/        # Cloudflare tunnel setup
├── docs/               # Disaster recovery and operational docs
├── homepage/           # Dashboard for services
├── loki/               # Log aggregation (Loki + Promtail)
├── mealie/             # Recipe management system
├── metallb/            # MetalLB L2 load balancer
├── ollama/             # Ollama external service (Mac Mini)
├── open-webui/         # Chat UI for Ollama
├── prometheus/         # Monitoring (Prometheus, Grafana, Alertmanager)
├── scripts/            # Bootstrap and utility scripts
├── storage/            # StorageClass and PV for 12TB HDD
├── traefik/            # Traefik + Gateway API
├── uptime-kuma/        # Uptime monitoring
└── not_in_use/         # Deprecated components (kept for reference)
```

## Notes to Self

### Common Tasks
- Cluster access: The kubeconfig is stored in the default location after k3s installation
- ArgoCD UI is accessible through the configured ingress
- Uptime Kuma dashboard provides monitoring status
- AdGuard admin interface is available through ingress
- Home Assistant provides home automation control
- Jellyfin and related apps manage media content
- Mealie handles recipe management and meal planning
- Authentik manages authentication across services

### Maintenance
- Certificates are automatically renewed by cert-manager
- DNS records are managed by external-dns
- Monitor Prometheus alerts for cluster health
- Check Uptime Kuma for service availability
- Regularly update container images for security patches
- Review Sealed Secrets when configuration changes are needed

### Troubleshooting
1. Check pod status: `kubectl get pods -A`
2. View logs: `kubectl logs -n <namespace> <pod-name>`
3. Verify ingress: `kubectl get ingress -A`
4. Check node status: `kubectl get nodes`
5. Inspect Argo CD application sync status: `kubectl get applications -n argocd`
6. Review events: `kubectl get events -A --sort-by='.lastTimestamp'`

### Future Improvements
- [x] Add monitoring dashboards (Grafana + kube-prometheus-stack)
- [x] Configure alerting (Alertmanager → Discord, custom homelab rules)
- [x] Document disaster recovery procedures ([docs/disaster-recovery.md](docs/disaster-recovery.md))
- [x] Implement automated backup solution (rsync to Mac Mini, daily launchd)
- [ ] Implement network policies for enhanced security
- [x] Set up Tailscale for remote access (subnet router on both Pis)
- [ ] Local AI voice assistant (Home Assistant + Ollama + Wyoming)

## Not Currently Used
Components in `not_in_use/` kept for reference:
- Jellyfin, Plex (media servers)
- Airflow, Home Assistant
- Cert-Manager, External DNS, External Secrets
- Sealed Secrets (replaced by SOPS + Age)
- Kubernetes Dashboard, PiHole, and others

## Security Notes
- Cluster is accessible via Cloudflare Tunnel only
- No direct external ports exposed
- Secrets are encrypted with SOPS + Age (repo is public)
- Authentication centralized with Authentik (SSO/OIDC)
- Forward auth on sensitive services (Prometheus, Alertmanager)
