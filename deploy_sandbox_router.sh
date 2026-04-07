#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Load environment variables from .env if it exists
if [ -f .env ]; then
  export $(cat .env | grep -v '^#' | xargs)
fi

# Ensure required variables are set
if [ -z "$PROJECT_NAME" ]; then
  echo "Error: PROJECT_NAME is not set in .env"
  exit 1
fi

if [ -z "$REGION" ]; then
  echo "Error: REGION is not set in .env"
  exit 1
fi

REPO_NAME="agent-sandbox-repo"
IMAGE_NAME="sandbox-router"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_NAME}/${REPO_NAME}/${IMAGE_NAME}:latest"

echo "Navigating one level above root directory to clone repository..."
cd ..

if [ ! -d "agent-sandbox" ]; then
  echo "Cloning upstream agent-sandbox repository..."
  git clone https://github.com/kubernetes-sigs/agent-sandbox.git
else
  echo "Directory 'agent-sandbox' already exists, skipping clone."
fi

cd agent-sandbox/clients/python/agentic-sandbox-client/sandbox-router/

echo "Building Sandbox Router image: ${REGISTRY}..."
docker build -t "$REGISTRY" .

echo "Pushing Sandbox Router image..."
docker push "$REGISTRY"

echo "Sandbox Router image pushed successfully!"
