#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Load environment variables from .env if it exists
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

# Define variables
PROJECT_ID=$(gcloud config get-value project)

# Ensure required variables are set (expected from .env)
if [ -z "$CLUSTER_NAME" ]; then
  echo "Error: CLUSTER_NAME is not set. Please set it in .env or environment."
  exit 1
fi

if [ -z "$REGION" ]; then
  echo "Error: REGION is not set. Please set it in .env or environment."
  exit 1
fi
CLUSTER_VERSION=${CLUSTER_VERSION:-"1.35.2-gke.1269000"}
NODE_POOL_NAME=${NODE_POOL_NAME:-"agent-sandbox-pool"}
MACHINE_TYPE=${MACHINE_TYPE:-"e2-standard-2"}


if gcloud container clusters describe "$CLUSTER_NAME" --region="$REGION" >/dev/null 2>&1; then
  echo "Cluster $CLUSTER_NAME already exists, skipping creation."
else
  echo "Creating GKE Standard cluster: $CLUSTER_NAME in $REGION..."
  gcloud beta container clusters create "$CLUSTER_NAME" \
      --region="$REGION" \
      --cluster-version="$CLUSTER_VERSION" \
      --no-enable-master-authorized-networks
fi

if gcloud container node-pools describe "$NODE_POOL_NAME" --cluster="$CLUSTER_NAME" --region="$REGION" >/dev/null 2>&1; then
  echo "Node pool $NODE_POOL_NAME already exists, skipping creation."
else
  echo "Creating node pool with gVisor enabled: $NODE_POOL_NAME..."
  gcloud container node-pools create "$NODE_POOL_NAME" \
      --cluster="$CLUSTER_NAME" \
      --machine-type="$MACHINE_TYPE" \
      --region="$REGION" \
      --image-type=cos_containerd \
      --sandbox=type=gvisor
fi

if gcloud beta container clusters describe "$CLUSTER_NAME" --region="$REGION" --format="value(addonsConfig.agentSandboxConfig.enabled)" | grep -q "True"; then
  echo "Agent Sandbox feature is already enabled."
else
  echo "Enabling Agent Sandbox feature on cluster..."
  gcloud beta container clusters update "$CLUSTER_NAME" \
      --region="$REGION" \
      --enable-agent-sandbox
fi

if gcloud container clusters describe "$CLUSTER_NAME" --region="$REGION" --format="value(addonsConfig.gatewayApiConfig.channel)" | grep -q "STANDARD"; then
  echo "Gateway API is already enabled."
else
  echo "Enabling Gateway API on cluster (this may take some time)..."
  gcloud container clusters update "$CLUSTER_NAME" \
      --region="$REGION" \
      --gateway-api=standard
fi

echo "Getting cluster credentials..."
gcloud container clusters get-credentials "$CLUSTER_NAME" --region "$REGION"

echo "Granting Vertex AI User role to default Compute Engine service account..."
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/aiplatform.user"

echo "Applying Kubernetes manifests..."
export PROJECT_NAME
export REGION
python3 -c "import os, sys; print(os.path.expandvars(sys.stdin.read()))" < infra/sandbox-template.yaml | kubectl apply -f -
python3 -c "import os, sys; print(os.path.expandvars(sys.stdin.read()))" < infra/sandbox-router.yaml | kubectl apply -f -
kubectl apply -f infra/sandbox-warmpool.yaml
kubectl apply -f infra/gateway.yaml
kubectl apply -f infra/http-route.yaml
kubectl apply -f infra/health-check-policy.yaml

echo "Infrastructure build complete!"
