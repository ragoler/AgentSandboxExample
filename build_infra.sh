#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Define variables with defaults
PROJECT_ID=$(gcloud config get-value project)
CLUSTER_NAME=${CLUSTER_NAME:-"agent-sandbox-cluster"}
REGION=${REGION:-"us-central1"}
CLUSTER_VERSION=${CLUSTER_VERSION:-"1.35.2-gke.1269000"}
NODE_POOL_NAME=${NODE_POOL_NAME:-"agent-sandbox-pool"}
MACHINE_TYPE=${MACHINE_TYPE:-"e2-standard-2"}

echo "Creating Artifact Registry repository..."
gcloud artifacts repositories create "agent-sandbox-repo" \
    --repository-format=docker \
    --location="$REGION" \
    --description="Repository for Agent Sandbox demo app" || echo "Repository might already exist or failed to create, continuing..."

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
kubectl apply -f infra/sandbox-template.yaml
kubectl apply -f infra/sandbox-warmpool.yaml

echo "Infrastructure build complete!"
