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
      --no-enable-master-authorized-networks \
      --workload-pool="${PROJECT_ID}.svc.id.goog"
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

echo "Configuring authentication for sandbox pods..."
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")

if [ "${GOOGLE_GENAI_USE_VERTEXAI:-FALSE}" = "TRUE" ]; then
  echo "Setting up Workload Identity Federation (WIF) for Vertex AI..."
  # The GKE metadata server IS accessible from gVisor sandbox pods when the
  # node pool uses --workload-metadata=GKE_METADATA (the default for gVisor pools).
  # This means WIF works without any proxy or workaround.

  # Create a dedicated KSA for sandbox pods
  kubectl create serviceaccount sandbox-ai-sa -n default --dry-run=client -o yaml | kubectl apply -f -

  # Grant Vertex AI access via direct principal binding (recommended over legacy GSA binding)
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --role="roles/aiplatform.user" \
      --member="principal://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${PROJECT_ID}.svc.id.goog/subject/ns/default/sa/sandbox-ai-sa" \
      --condition=None

  echo "WIF configured. Sandbox pods will authenticate to Vertex AI automatically."
else
  echo "Using Gemini API key authentication (GOOGLE_GENAI_USE_VERTEXAI != TRUE)."
  if [ -z "$GEMINI_API_KEY" ]; then
    echo "Warning: GEMINI_API_KEY is not set in .env. Sandbox pods will fail to authenticate."
  fi
  kubectl create secret generic gemini-api-key --from-literal=GEMINI_API_KEY="$GEMINI_API_KEY" --dry-run=client -o yaml | kubectl apply -f -
fi

echo "Applying Kubernetes manifests..."
export PROJECT_NAME
export REGION
export GOOGLE_GENAI_USE_VERTEXAI

# Set the KSA for sandbox pods based on auth mode
if [ "${GOOGLE_GENAI_USE_VERTEXAI:-FALSE}" = "TRUE" ]; then
  export SANDBOX_KSA="sandbox-ai-sa"
else
  export SANDBOX_KSA="default"
fi
python3 -c "import os, sys; print(os.path.expandvars(sys.stdin.read()))" < infra/sandbox-template.yaml | kubectl apply -f -
python3 -c "import os, sys; print(os.path.expandvars(sys.stdin.read()))" < infra/sandbox-router.yaml | kubectl apply -f -
kubectl apply -f infra/sandbox-warmpool.yaml
kubectl apply -f infra/gateway.yaml
kubectl apply -f infra/http-route.yaml
kubectl apply -f infra/health-check-policy.yaml

echo "Applying Main Application manifests..."
python3 -c "import os, sys; print(os.path.expandvars(sys.stdin.read()))" < infra/main-app.yaml | kubectl apply -f -

echo "Infrastructure build complete!"
