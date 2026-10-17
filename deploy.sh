#!/usr/bin/env bash
# Deploy app/ to the team namespace at Ingress path /app (no registry).
set -euo pipefail

mapfile -t TEAM_CONFIGS < <(find /config -maxdepth 1 -type f -name '*.config' | sort)
(( ${#TEAM_CONFIGS[@]} == 1 )) || { echo "expected exactly one /config/*.config"; exit 1; }
TEAM_CONFIG="${TEAM_CONFIGS[0]}"
# Parse without sourcing (USERNAME reserved in some shells)
get() { grep -E "^$1=" "$TEAM_CONFIG" | head -1 | cut -d= -f2-; }
USERNAME="$(get USERNAME)"
INGRESS_URL="$(get INGRESS_URL)"
PASSWORD="$(get PASSWORD)"
# Prefer process env (already set on workshop VM), else team config — never echo values
GPU_BEARER_TOKEN="${GPU_BEARER_TOKEN:-$(get GPU_BEARER_TOKEN)}"
WANDB_API_KEY="${WANDB_API_KEY:-$(get WANDB_API_KEY || true)}"
WANDB_TEAM="${WANDB_TEAM:-$(get WANDB_TEAM || true)}"
WANDB_PROJECT="${WANDB_PROJECT:-$(get WANDB_PROJECT || true)}"
for v in S3_ENDPOINT ACCESS_KEY SECRET_KEY S3_CHUNKS_BUCKET VDB_ENDPOINT VASTDB_BUCKET VDB_SCHEMA; do
  printf -v "$v" '%s' "${!v:-$(get "$v" || true)}"
done
NS="$USERNAME"
TEAM_N="${USERNAME#team-}"
APP_HOST="video-lab-team-${TEAM_N}.cosmos.vastdata.com"
APP_NAME="hackathon-app"
APP_PORT=8080
ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$ROOT/app"
export KUBECONFIG="/config/${NS}-k8s.yaml"

GPU_HOST=166.19.38.112
COSMOS3_REASON_URL="http://${GPU_HOST}:8001"
YOLO_URL="http://${GPU_HOST}:8002"
COSMOS_EMBED1_URL="http://${GPU_HOST}:8003"
CANARY_1B_URL="http://${GPU_HOST}:8004"

echo "NS=$NS APP_HOST=$APP_HOST"

# Pack app/ + frontend/ (ConfigMap keys cannot contain '/'; use tarball)
TMP=$(mktemp -d)
# drop bulky demo assets from the bundle if present
rm -f "$APP_DIR/static/demo_breadboard.mp4" || true
tar czf "$TMP/app.tgz" -C "$ROOT" app frontend
SIZE=$(wc -c < "$TMP/app.tgz")
echo "bundle_bytes=$SIZE"
if (( SIZE > 1000000 )); then
  echo "ERROR: bundle exceeds ~1MiB ConfigMap soft limit" >&2
  exit 1
fi

# Reachability probe from a one-off curl pod (no secret values printed)
echo "Checking GPU reachability from cluster..."
kubectl -n "$NS" delete pod gpu-reach-probe --ignore-not-found >/dev/null 2>&1 || true
kubectl -n "$NS" run gpu-reach-probe --restart=Never --image=curlimages/curl:8.5.0 --command -- \
  sh -c "echo cosmos; curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 http://${GPU_HOST}:8001/v1/health/ready; echo; echo yolo; curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 http://${GPU_HOST}:8002/healthz; echo; echo embed; curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 http://${GPU_HOST}:8003/v1/health/ready; echo; echo canary; curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 http://${GPU_HOST}:8004/v1/health/ready; echo"
kubectl -n "$NS" wait --for=jsonpath='{.status.phase}'=Succeeded pod/gpu-reach-probe --timeout=90s || \
kubectl -n "$NS" wait --for=jsonpath='{.status.phase}'=Failed pod/gpu-reach-probe --timeout=90s || true
REACH_LOG=$(kubectl -n "$NS" logs gpu-reach-probe 2>/dev/null || true)
echo "$REACH_LOG"
kubectl -n "$NS" delete pod gpu-reach-probe --ignore-not-found >/dev/null 2>&1 || true
# If all curl codes are 000 / empty, stop
if echo "$REACH_LOG" | grep -qE '000|^$'; then
  # soft check: if no 200 at all, warn and stop
  if ! echo "$REACH_LOG" | grep -q '200'; then
    echo "GPU host/ports not reachable from cluster pods. Stopping before deploy." >&2
    exit 2
  fi
fi

kubectl -n "$NS" create configmap "${APP_NAME}-code" \
  --from-file=app.tgz="$TMP/app.tgz" \
  --dry-run=client -o yaml | kubectl apply -f -

# Secret: VSS + GPU + W&B (do not echo values)
# Prefer in-cluster backend Service (Ingress hostname often does not resolve from pods)
VSS_INTERNAL="http://video-backend-service.${NS}.svc.cluster.local:8000"
kubectl -n "$NS" create secret generic "${APP_NAME}-vss-creds" \
  --from-literal=VSS_URL="$VSS_INTERNAL" \
  --from-literal=VSS_USERNAME="$USERNAME" \
  --from-literal=VSS_PASSWORD="$PASSWORD" \
  --from-literal=GPU_BEARER_TOKEN="$GPU_BEARER_TOKEN" \
  --from-literal=COSMOS3_REASON_URL="$COSMOS3_REASON_URL" \
  --from-literal=YOLO_URL="$YOLO_URL" \
  --from-literal=COSMOS_EMBED1_URL="$COSMOS_EMBED1_URL" \
  --from-literal=CANARY_1B_URL="$CANARY_1B_URL" \
  --from-literal=WANDB_API_KEY="${WANDB_API_KEY:-}" \
  --from-literal=WANDB_TEAM="${WANDB_TEAM:-}" \
  --from-literal=WANDB_PROJECT="${WANDB_PROJECT:-}" \
  --from-literal=S3_ENDPOINT="${S3_ENDPOINT:-}" \
  --from-literal=ACCESS_KEY="${ACCESS_KEY:-}" \
  --from-literal=SECRET_KEY="${SECRET_KEY:-}" \
  --from-literal=S3_CHUNKS_BUCKET="${S3_CHUNKS_BUCKET:-}" \
  --from-literal=VDB_ENDPOINT="${VDB_ENDPOINT:-}" \
  --from-literal=VASTDB_BUCKET="${VASTDB_BUCKET:-}" \
  --from-literal=VDB_SCHEMA="${VDB_SCHEMA:-}" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n "$NS" apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${APP_NAME}
  labels:
    app: ${APP_NAME}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ${APP_NAME}
  template:
    metadata:
      labels:
        app: ${APP_NAME}
    spec:
      containers:
      - name: app
        image: python:3.12-slim
        imagePullPolicy: IfNotPresent
        ports:
        - containerPort: ${APP_PORT}
        env:
        - name: PORT
          value: "${APP_PORT}"
        - name: VSS_URL
          valueFrom: { secretKeyRef: { name: ${APP_NAME}-vss-creds, key: VSS_URL } }
        - name: VSS_USERNAME
          valueFrom: { secretKeyRef: { name: ${APP_NAME}-vss-creds, key: VSS_USERNAME } }
        - name: VSS_PASSWORD
          valueFrom: { secretKeyRef: { name: ${APP_NAME}-vss-creds, key: VSS_PASSWORD } }
        - name: GPU_BEARER_TOKEN
          valueFrom: { secretKeyRef: { name: ${APP_NAME}-vss-creds, key: GPU_BEARER_TOKEN } }
        - name: COSMOS3_REASON_URL
          valueFrom: { secretKeyRef: { name: ${APP_NAME}-vss-creds, key: COSMOS3_REASON_URL } }
        - name: YOLO_URL
          valueFrom: { secretKeyRef: { name: ${APP_NAME}-vss-creds, key: YOLO_URL } }
        - name: COSMOS_EMBED1_URL
          valueFrom: { secretKeyRef: { name: ${APP_NAME}-vss-creds, key: COSMOS_EMBED1_URL } }
        - name: CANARY_1B_URL
          valueFrom: { secretKeyRef: { name: ${APP_NAME}-vss-creds, key: CANARY_1B_URL } }
        - name: WANDB_API_KEY
          valueFrom: { secretKeyRef: { name: ${APP_NAME}-vss-creds, key: WANDB_API_KEY } }
        - name: WANDB_TEAM
          valueFrom: { secretKeyRef: { name: ${APP_NAME}-vss-creds, key: WANDB_TEAM } }
        - name: WANDB_PROJECT
          valueFrom: { secretKeyRef: { name: ${APP_NAME}-vss-creds, key: WANDB_PROJECT } }
        - name: S3_ENDPOINT
          valueFrom: { secretKeyRef: { name: ${APP_NAME}-vss-creds, key: S3_ENDPOINT, optional: true } }
        - name: ACCESS_KEY
          valueFrom: { secretKeyRef: { name: ${APP_NAME}-vss-creds, key: ACCESS_KEY, optional: true } }
        - name: SECRET_KEY
          valueFrom: { secretKeyRef: { name: ${APP_NAME}-vss-creds, key: SECRET_KEY, optional: true } }
        - name: S3_CHUNKS_BUCKET
          valueFrom: { secretKeyRef: { name: ${APP_NAME}-vss-creds, key: S3_CHUNKS_BUCKET, optional: true } }
        - name: VDB_ENDPOINT
          valueFrom: { secretKeyRef: { name: ${APP_NAME}-vss-creds, key: VDB_ENDPOINT, optional: true } }
        - name: VASTDB_BUCKET
          valueFrom: { secretKeyRef: { name: ${APP_NAME}-vss-creds, key: VASTDB_BUCKET, optional: true } }
        - name: VDB_SCHEMA
          valueFrom: { secretKeyRef: { name: ${APP_NAME}-vss-creds, key: VDB_SCHEMA, optional: true } }
        volumeMounts:
        - name: code
          mountPath: /code
        workingDir: /work/app
        command: ["bash", "-c"]
        args:
        - |
          set -euo pipefail
          mkdir -p /work
          tar xzf /code/app.tgz -C /work
          pip install --no-cache-dir -q -r requirements.txt
          exec python main.py
        readinessProbe:
          httpGet:
            path: /health
            port: ${APP_PORT}
          initialDelaySeconds: 20
          periodSeconds: 10
          failureThreshold: 12
        livenessProbe:
          httpGet:
            path: /health
            port: ${APP_PORT}
          initialDelaySeconds: 40
          periodSeconds: 20
      volumes:
      - name: code
        configMap:
          name: ${APP_NAME}-code
---
apiVersion: v1
kind: Service
metadata:
  name: ${APP_NAME}
  labels:
    app: ${APP_NAME}
spec:
  selector:
    app: ${APP_NAME}
  ports:
  - name: http
    port: 80
    targetPort: ${APP_PORT}
  type: ClusterIP
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: ${APP_NAME}
  labels:
    app: ${APP_NAME}
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /\$2
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
spec:
  ingressClassName: nginx
  rules:
  - host: ${APP_HOST}
    http:
      paths:
      - path: /app(/|\$)(.*)
        pathType: ImplementationSpecific
        backend:
          service:
            name: ${APP_NAME}
            port:
              number: 80
EOF

kubectl -n "$NS" rollout restart deploy/"$APP_NAME"
kubectl -n "$NS" rollout status deploy/"$APP_NAME" --timeout=300s
kubectl -n "$NS" get pods,svc,ingress -l app="$APP_NAME"
echo "health:" 
curl -sS "http://${APP_HOST}/app/health" || true
echo
echo "Open https://workshop.thecosmoslabs.com and click App"
rm -rf "$TMP"
