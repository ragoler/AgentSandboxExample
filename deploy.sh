#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Load environment variables from .env if it exists
if [ -f .env ]; then
  export $(cat .env | grep -v '^#' | xargs)
fi

# Use PROJECT_NAME from env as PROJECT_ID if set
PROJECT_ID=${PROJECT_NAME:-$(gcloud config get-value project)}
REGION=${REGION:-"us-west1"}
REPO_NAME="agent-sandbox-repo"

REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}"

echo "Creating Artifact Registry repository if it doesn't exist..."
gcloud artifacts repositories create "$REPO_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --description="Repository for Agent Sandbox demo app" || echo "Repository might already exist or failed to create, continuing..."

echo "Authenticating Docker to Artifact Registry..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo "Building Demo Application image..."
docker build -t "${REGISTRY}/demo-app:latest" ./demo-app

echo "Pushing Demo Application image..."
docker push "${REGISTRY}/demo-app:latest"

echo "Building Main Application image..."
docker build -t "${REGISTRY}/main-app:latest" ./main-app

echo "Pushing Main Application image..."
docker push "${REGISTRY}/main-app:latest"

echo "Deployment images pushed successfully to ${REGISTRY}"
echo "NOTE: Remember to update the image in infra/sandbox-template.yaml to use ${REGISTRY}/demo-app:latest"
