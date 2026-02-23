#!/bin/bash
set -euo pipefail

# Bootstrap script for homelab K3s cluster
# This script is run AFTER ansible has brought up k3s
# Prerequisites:
#   - kubectl configured to talk to the cluster
#   - sops and age installed locally
#   - Age key at ~/.config/sops/age/keys.txt
#   - Deploy key added to GitHub repo settings

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
AGE_KEY_FILE="${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}"

echo "=== Homelab Cluster Bootstrap ==="
echo "Repo: $REPO_DIR"
echo ""

# Check prerequisites
echo "Checking prerequisites..."
command -v kubectl >/dev/null 2>&1 || { echo "ERROR: kubectl not found"; exit 1; }
command -v sops >/dev/null 2>&1 || { echo "ERROR: sops not found"; exit 1; }
command -v kustomize >/dev/null 2>&1 || { echo "WARNING: kustomize not found, will use kubectl -k"; }

if [ ! -f "$AGE_KEY_FILE" ]; then
    echo "ERROR: Age key not found at $AGE_KEY_FILE"
    exit 1
fi

echo "Verifying cluster connectivity..."
kubectl get nodes || { echo "ERROR: Cannot connect to cluster"; exit 1; }
echo ""

# Step 1: Deploy MetalLB
echo "=== Step 1: Deploying MetalLB ==="
kubectl apply -k "$REPO_DIR/metallb/"
echo "Waiting for MetalLB to be ready..."
kubectl -n metallb wait --for=condition=ready pod -l app.kubernetes.io/name=metallb --timeout=120s 2>/dev/null || true
sleep 10
echo ""

# Step 2: Deploy Ingress-Nginx
echo "=== Step 2: Deploying Ingress-Nginx ==="
kubectl apply -k "$REPO_DIR/ingress-nginx/"
echo "Waiting for Ingress-Nginx to be ready..."
kubectl -n ingress-nginx wait --for=condition=ready pod -l app.kubernetes.io/name=ingress-nginx --timeout=120s 2>/dev/null || true
echo ""

# Step 3: Deploy Storage
echo "=== Step 3: Deploying Storage PVs ==="
kubectl apply -k "$REPO_DIR/storage/"
echo ""

# Step 4: Deploy ArgoCD
echo "=== Step 4: Deploying ArgoCD ==="

# Create argocd namespace first
kubectl create namespace argocd 2>/dev/null || true

# Deploy the age key secret for SOPS decryption in ArgoCD
echo "Creating SOPS age key secret in argocd namespace..."
kubectl create secret generic sops-age-key \
    --namespace argocd \
    --from-file=keys.txt="$AGE_KEY_FILE" \
    --dry-run=client -o yaml | kubectl apply -f -

# Deploy ArgoCD secrets (decrypted from SOPS)
echo "Deploying ArgoCD secrets..."
sops -d "$REPO_DIR/argo-cd/secret.enc.yaml" | kubectl apply -f -
sops -d "$REPO_DIR/argo-cd/repo-secret.enc.yaml" | kubectl apply -f -

# Deploy ArgoCD itself
kubectl apply -k "$REPO_DIR/argo-cd/"
echo "Waiting for ArgoCD to be ready..."
kubectl -n argocd wait --for=condition=ready pod -l app.kubernetes.io/name=argocd-server --timeout=300s 2>/dev/null || true
echo ""

# Step 5: Deploy ArgoCD Applications
echo "=== Step 5: Deploying ArgoCD Applications ==="
kubectl apply -f "$REPO_DIR/argo-apps/applications.yaml"
echo ""

# Step 6: Deploy secrets for apps that need them before ArgoCD syncs
echo "=== Step 6: Deploying app secrets ==="

# Authentik secrets
kubectl create namespace authentik 2>/dev/null || true
sops -d "$REPO_DIR/authentik/secret.enc.yaml" | kubectl apply -f -
echo "  - Authentik secrets deployed"

# Cloudflared secrets
kubectl create namespace cloudflared 2>/dev/null || true
sops -d "$REPO_DIR/cloudflared/secret.enc.yaml" | kubectl apply -f -
echo "  - Cloudflared secrets deployed"

# Homepage secrets
kubectl create namespace homepage 2>/dev/null || true
sops -d "$REPO_DIR/homepage/secret.enc.yaml" | kubectl apply -f -
echo "  - Homepage secrets deployed"

# Mealie secrets
kubectl create namespace mealie 2>/dev/null || true
sops -d "$REPO_DIR/mealie/secret.enc.yaml" | kubectl apply -f -
echo "  - Mealie secrets deployed"

echo ""
echo "=== Bootstrap Complete ==="
echo ""
echo "Next steps:"
echo "  1. Add the deploy key to GitHub: cat /tmp/homelab-deploy-key.pub"
echo "  2. Check ArgoCD: kubectl -n argocd get pods"
echo "  3. Get ArgoCD admin password: kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d"
echo "  4. Port-forward ArgoCD: kubectl -n argocd port-forward svc/argocd-server 8080:443"
echo "  5. Configure Authentik OIDC providers after Authentik is running"
echo "  6. Update Homepage secrets with real API keys after services are up"
echo ""
echo "IMPORTANT: Back up your age key!"
echo "  cp ~/.config/sops/age/keys.txt <somewhere-safe>"
