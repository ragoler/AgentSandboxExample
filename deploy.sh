#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Define variables with defaults
PROJECT_ID=$(gcloud config get-value project)
REGION=${REGION:-"us-central1"}
REPO_NAME="agent-sandbox-repo"

REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}"

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
