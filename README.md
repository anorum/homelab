# Home Lab Kubernetes Cluster

My personal Kubernetes cluster running on Raspberry Pi. This repository contains the configuration and deployment files for various services running in my homelab.

## Overview

This is a k3s-based Kubernetes cluster running on Raspberry Pi hardware. The cluster is managed using GitOps principles with Argo CD, and the initial setup is automated using Ansible.

## Core Components

### Infrastructure
- **k3s**: Lightweight Kubernetes distribution
- **MetalLB**: Load balancer for bare metal Kubernetes
- **Nginx Ingress**: Ingress controller for handling external access
- **Cert-Manager**: Automatic SSL certificate management
- **Cloudflared**: Cloudflare tunnel for secure external access
- **Sealed Secrets**: Secure management of Kubernetes secrets
- **Argo Apps**: Application management with GitOps

### Applications
- **Argo CD**: GitOps continuous delivery tool
- **Prometheus**: Metrics collection and monitoring
- **Uptime Kuma**: Uptime monitoring
- **AdGuard**: Network-wide ad blocking and DNS filtering
- **Home Assistant**: Home automation platform
- **Jellyfin**: Media server with various supporting applications
  - Jellyseerr, Radarr, Sonarr, Readarr, Prowlarr, Qbittorrent, Kavita, Audiobookshelf, Flaresolverr
- **Mealie**: Recipe management and meal planning
- **Authentik**: Identity provider and SSO solution
- **Homepage**: Dashboard for services and applications
- **Ollama**: Self-hosted AI model server
- **Alex-API**: Custom API service
- **Marabot**: Custom bot application
- **Airflow**: Workflow automation and scheduling

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
├── airflow/            # Apache Airflow workflow automation
├── alex-api/           # Custom API service
├── ansible/            # Ansible playbooks and roles
├── argo-apps/          # Argo CD applications
├── argo-cd/            # Argo CD configuration
├── authentik/          # Identity provider and SSO
├── cert-manager/       # Certificate management
├── cloudflared/        # Cloudflare tunnel setup
├── home-assistant/     # Home automation platform
├── homepage/           # Dashboard for services
├── ingress-nginx/      # Nginx ingress controller
├── jellyfin/           # Media server and related apps
├── marabot/            # Custom bot application
├── mealie/             # Recipe management system
├── metallb/            # MetalLB configuration
├── not_in_use/         # Components not currently active
├── ollama/             # Self-hosted AI model server
├── prometheus/         # Monitoring setup
├── sealed-secrets/     # Secure secrets management
├── storage/            # Storage configuration
└── uptime-kuma/        # Uptime monitoring
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
- [ ] Implement backup solution
- [ ] Add monitoring dashboards
- [ ] Configure alerting
- [ ] Document disaster recovery procedures
- [ ] Implement network policies for enhanced security
- [ ] Set up automated updates for applications

## Not Currently Used
Some components are kept for reference but not actively used:
- Kubernetes Dashboard
- CoreDNS custom configuration
- PiHole (replaced by AdGuard)
- External DNS
- External Secrets
- Registry
- Plex (replaced by Jellyfin)

## Security Notes
- Cluster is accessible via Cloudflare Tunnel only
- No direct external ports exposed
- SSL certificates managed automatically
- Network policies should be reviewed periodically
- Secrets are encrypted using Sealed Secrets
- Authentication is centralized with Authentik
