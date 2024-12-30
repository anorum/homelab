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
- **External-DNS**: Automatic DNS management

### Applications
- **Argo CD**: GitOps continuous delivery tool
- **Prometheus**: Metrics collection and monitoring
- **Uptime Kuma**: Uptime monitoring
- **AdGuard**: Network-wide ad blocking and DNS filtering

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
├── ansible/            # Ansible playbooks and roles
├── argo-cd/           # Argo CD configuration
├── cert-manager/      # Certificate management
├── cloudflared/       # Cloudflare tunnel setup
├── external-dns/      # External DNS configuration
├── metallb/           # MetalLB configuration
├── nginx-ingress/     # Nginx ingress controller
├── prometheus/        # Monitoring setup
└── uptime-kuma/       # Uptime monitoring
```

## Notes to Self

### Common Tasks
- Cluster access: The kubeconfig is stored in the default location after k3s installation
- ArgoCD UI is accessible through the configured ingress
- Uptime Kuma dashboard provides monitoring status
- AdGuard admin interface is available through ingress

### Maintenance
- Certificates are automatically renewed by cert-manager
- DNS records are managed by external-dns
- Monitor Prometheus alerts for cluster health
- Check Uptime Kuma for service availability

### Troubleshooting
1. Check pod status: `kubectl get pods -A`
2. View logs: `kubectl logs -n <namespace> <pod-name>`
3. Verify ingress: `kubectl get ingress -A`
4. Check node status: `kubectl get nodes`

### Future Improvements
- [ ] Implement backup solution
- [ ] Add monitoring dashboards
- [ ] Configure alerting
- [ ] Document disaster recovery procedures

## Not Currently Used
Some components are kept for reference but not actively used:
- Kubernetes Dashboard
- CoreDNS custom configuration
- PiHole (replaced by AdGuard)

## Security Notes
- Cluster is accessible via Cloudflare Tunnel only
- No direct external ports exposed
- SSL certificates managed automatically
- Network policies should be reviewed periodically
