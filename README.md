# Agent Sandbox Example

This repository contains a demonstration of managing isolated environments (sandboxes) on Google Kubernetes Engine (GKE) using the **GKE Agent Sandbox** feature.

It consists of a Main Application (orchestrator with UI) and a Demo Application designed to run inside the isolated sandboxes.

## Repository Structure

-   `main-app/`: The control plane application (FastAPI) and UI.
-   `demo-app/`: The lightweight application (FastAPI) that runs inside the sandboxes.
-   `infra/`: Kubernetes manifests for `SandboxTemplate`, `SandboxWarmPool`, `Gateway`, `HTTPRoute`, and `HealthCheckPolicy`.
-   `build_infra.sh`: Script to provision the GKE cluster and apply manifests.
-   `deploy.sh`: Script to build and push Docker images to Artifact Registry.

## Prerequisites

-   **Python 3.13** (used for local development and testing)
-   **Docker** (for building images)
-   **Google Cloud SDK (`gcloud`)** authenticated to your Google Cloud project.
-   **`kubectl`** and **`envsubst`** installed locally.

---

## Local Development and Testing

The application supports a **Mock Mode** that allows you to test the UI and API logic without a real GKE cluster.

### 1. Setup Environment

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate

# Install requirements for both apps
pip install --index-url https://pypi.org/simple -r main-app/requirements.txt
pip install --index-url https://pypi.org/simple -r demo-app/requirements.txt
```

### 2. Run Main Application (Mock Mode)

1.  Create a `.env` file in the root directory (based on `.env.example`):
    ```env
    MODE=MOCK
    GATEWAY_NAME=external-http-gateway
    CLUSTER_NAME=YOUR_CLUSTER_NAME
    REGION=YOUR_REGION
    PROJECT_NAME=YOUR_PROJECT_ID
    GEMINI_API_KEY=YOUR_GEMINI_API_KEY
    GOOGLE_GENAI_USE_VERTEXAI=FALSE
    ```
2.  Run the application:
    ```bash
    uvicorn main-app.main:app --reload
    ```
3.  Open `http://127.0.0.1:8000` in your browser to view the UI. You can create, message, and delete mock sandboxes.

### 3. Test Demo Application Locally

You can also run the Demo App directly to verify its endpoints:

```bash
# Set required env vars
export GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
export GOOGLE_GENAI_USE_VERTEXAI="FALSE"

# Run the app on the standard sandbox port
uvicorn demo-app.main:app --host 127.0.0.1 --port 8888 --reload
```

Test with curl:
```bash
curl -X POST http://127.0.0.1:8888/message -H "Content-Type: application/json" -d '{"message": "Hello"}'
curl http://127.0.0.1:8888/quote
```

---

## Deployment to Real GKE

To deploy to a real cluster, we build images first and then provision the infrastructure.

### Step 1: Configuration

Ensure your `.env` file has the correct values:
-   `MODE=REAL`
-   `PROJECT_NAME`: Your real GCP Project ID.
-   `REGION`: The region where you want to deploy (e.g., `us-west1`).
-   `GEMINI_API_KEY`: Your Gemini API Key.
-   `GOOGLE_GENAI_USE_VERTEXAI`: Set to `FALSE` to use Gemini API Key, or `TRUE` to use Vertex AI.

> [!IMPORTANT]
> In a gVisor sandboxed environment on GKE, access to the GKE Metadata Server is blocked by default. This prevents standard Workload Identity from working out-of-the-box without a proxy.
> 
> To bypass this constraint, we use a **Gemini API Key** for authentication within the sandbox.
> The `build_infra.sh` script automatically creates a Kubernetes Secret named `gemini-api-key` from the `GEMINI_API_KEY` variable in your `.env` file, and mounts it into the sandbox pods.
> 
> If you prefer to use Vertex AI (and have configured a metadata proxy or other method), you can set `GOOGLE_GENAI_USE_VERTEXAI=TRUE` in your `.env` file.

### Step 2: Build and Push Images

1.  **Build and Push Application Images**: Run the deployment script to create the Artifact Registry repo and push `demo-app` and `main-app` images:
    ```bash
    ./deploy.sh
    ```

2.  **Build and Push Sandbox Router Image**: Run the helper script to clone the upstream repository (one level above root), build the router image, and push it to your registry:
    ```bash
    ./deploy_sandbox_router.sh
    ```

### Step 3: Provision Infrastructure

Run the infrastructure script. It will create a GKE Standard cluster with a gVisor node pool, enable the Agent Sandbox feature, and apply the templates using `envsubst` to inject your environment variables. Note that `build_infra.sh` has been updated to load environment variables more robustly.

```bash
./build_infra.sh
```

### Step 4: Find Application IP

To access the Main Application UI or interact with the Gateway, you need to find the external IP address:

```bash
# For GKE Gateway
kubectl get gateway external-http-gateway

# For standard Service (if deployed)
kubectl get svc main-app-service
```
Look for the `ADDRESS` or `EXTERNAL-IP` field in the output.

---

## Clean Up

To avoid recurring charges, delete the GKE cluster when you are done:

```bash
gcloud container clusters delete agent-sandbox-cluster --region us-west1 --quiet
```
