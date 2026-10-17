#!/usr/bin/env bash
# Deploy ElectronicAI on the team's Kubernetes cluster via the
# deploy-app-no-registry pattern: public python image + code from a ConfigMap +
# VSS creds from a Secret + Ingress at /app. Run this ON THE CHALLENGE VM.
#
# Usage:  bash k8s/deploy.sh
set -euo pipefail

APP_NAME="electronicai"
APP_PORT=8080
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# --- team config (single /config/*.config on the VM) ---
mapfile -t TEAM_CONFIGS < <(find /config -maxdepth 1 -type f -name '*.config' | sort)
(( ${#TEAM_CONFIGS[@]} == 1 )) || { echo "expected exactly one /config/*.config"; exit 1; }
TEAM_CONFIG="${TEAM_CONFIGS[0]}"
USERNAME=$(grep '^USERNAME=' "$TEAM_CONFIG" | cut -d= -f2-)
PASSWORD=$(grep '^PASSWORD=' "$TEAM_CONFIG" | cut -d= -f2-)
INGRESS_URL=$(grep '^INGRESS_URL=' "$TEAM_CONFIG" | cut -d= -f2-)

NS="$USERNAME"                                  # e.g. team-11
TEAM_N="${USERNAME#team-}"
APP_HOST="video-lab-team-${TEAM_N}.cosmos.vastdata.com"
export KUBECONFIG="/config/${NS}-k8s.yaml"

echo "Deploying $APP_NAME to namespace $NS (host $APP_HOST path /app)"
kubectl cluster-info >/dev/null

# --- 1. ConfigMap: app code (flattened; main.py finds index.html at /code) ---
kubectl -n "$NS" create configmap "${APP_NAME}-code" \
  --from-file=main.py="$APP_DIR/main.py" \
  --from-file=requirements.txt="$APP_DIR/requirements.txt" \
  --from-file=index.html="$APP_DIR/templates/index.html" \
  --dry-run=client -o yaml | kubectl apply -f -

# --- 2. Secret: VSS + W&B credentials (server-side only) ---
# WANDB_* are read from the VM environment if present.
kubectl -n "$NS" create secret generic "${APP_NAME}-secrets" \
  --from-literal=VSS_URL="$INGRESS_URL" \
  --from-literal=VSS_USERNAME="$USERNAME" \
  --from-literal=VSS_PASSWORD="$PASSWORD" \
  --from-literal=WANDB_API_KEY="${WANDB_API_KEY:-}" \
  --from-literal=WANDB_TEAM="${WANDB_TEAM:-}" \
  --from-literal=WANDB_PROJECT="${WANDB_PROJECT:-}" \
  --from-literal=WANDB_MODEL="${WANDB_MODEL:-meta-llama/Llama-3.3-70B-Instruct}" \
  --dry-run=client -o yaml | kubectl apply -f -

# --- 3. Deployment + Service + Ingress ---
sed -e "s|__APP_NAME__|$APP_NAME|g" \
    -e "s|__APP_PORT__|$APP_PORT|g" \
    -e "s|__APP_HOST__|$APP_HOST|g" \
    "$APP_DIR/k8s/manifests.yaml" | kubectl -n "$NS" apply -f -

kubectl -n "$NS" rollout restart deploy/"$APP_NAME" 2>/dev/null || true
kubectl -n "$NS" rollout status deploy/"$APP_NAME" --timeout=180s
kubectl -n "$NS" get pods,svc,ingress -l app="$APP_NAME"

echo
echo "Deployed. Open https://workshop.thecosmoslabs.com and click the App button."
echo "(cluster check: curl http://${APP_HOST}/app/health )"
