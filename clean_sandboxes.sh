#!/bin/bash
echo "Deleting all SandboxClaims..."
kubectl delete sandboxclaim --all

echo "Waiting for all SandboxClaims to be deleted..."
while true; do
    OUTPUT=$(kubectl get sandboxclaim --no-headers 2>/dev/null)
    if [ -z "$OUTPUT" ]; then
        echo "All SandboxClaims deleted."
        break
    fi
    COUNT=$(echo "$OUTPUT" | wc -l | tr -d ' ')
    echo "Still waiting for $COUNT SandboxClaims to be deleted..."
    sleep 2
done

echo "Deleting warm pool pods..."
kubectl delete pods -l app=demo-agent --ignore-not-found

# Load environment variables from .env if present (for PROJECT_NAME / bucket name).
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi
PROJECT_ID=${PROJECT_NAME:-$(gcloud config get-value project 2>/dev/null)}
SNAPSHOT_BUCKET_NAME=${SNAPSHOT_BUCKET_NAME:-"${PROJECT_ID}-sandbox-snapshots"}

echo "Deleting all PodSnapshots (controller will garbage-collect their bucket data)..."
kubectl delete podsnapshots.podsnapshot.gke.io --all --ignore-not-found
kubectl delete podsnapshotmanualtriggers.podsnapshot.gke.io --all --ignore-not-found

echo "Clearing any leftover snapshot objects in gs://${SNAPSHOT_BUCKET_NAME}/sandbox-checkpoints/ ..."
if gcloud storage ls "gs://${SNAPSHOT_BUCKET_NAME}/sandbox-checkpoints/" >/dev/null 2>&1; then
  gcloud storage rm --recursive "gs://${SNAPSHOT_BUCKET_NAME}/sandbox-checkpoints/**" 2>/dev/null \
    && echo "Snapshot bucket cleared." \
    || echo "Snapshot bucket already empty (or nothing to remove)."
else
  echo "No snapshot checkpoints found in bucket."
fi

echo "Restarting main application deployment to synchronize in-memory state..."
kubectl rollout restart deployment main-app-deployment -n main-app-ns
kubectl rollout status deployment main-app-deployment -n main-app-ns

echo "Cleanup complete."
