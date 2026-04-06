#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Load environment variables from .env if it exists
if [ -f .env ]; then
  export $(cat .env | grep -v '^#' | xargs)
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


echo "Creating GKE Standard cluster: $CLUSTER_NAME in $REGION..."
gcloud beta container clusters create "$CLUSTER_NAME" \
    --region="$REGION" \
    --cluster-version="$CLUSTER_VERSION"

echo "Creating node pool with gVisor enabled: $NODE_POOL_NAME..."
gcloud container node-pools create "$NODE_POOL_NAME" \
    --cluster="$CLUSTER_NAME" \
    --machine-type="$MACHINE_TYPE" \
    --region="$REGION" \
    --image-type=cos_containerd \
    --sandbox=type=gvisor

echo "Enabling Agent Sandbox feature on cluster..."
gcloud beta container clusters update "$CLUSTER_NAME" \
    --region="$REGION" \
    --enable-agent-sandbox

echo "Getting cluster credentials..."
gcloud container clusters get-credentials "$CLUSTER_NAME" --region "$REGION"

echo "Applying Kubernetes manifests..."
envsubst < infra/sandbox-template.yaml | kubectl apply -f -
kubectl apply -f infra/sandbox-warmpool.yaml
kubectl apply -f infra/gateway.yaml

echo "Infrastructure build complete!"
