import os
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, List
from kubernetes import client, config

app = FastAPI()

# In-Memory State
# sandbox_id -> { "status": "Running" | "Sleeping", "pod_ip": "..." }
sandboxes: Dict[str, dict] = {}

class MessagePayload(BaseModel):
    message: str

@app.on_event("startup")
async def startup_event():
    print("Application starting. Clearing all transient sandbox state.")
    # In a real K8s environment, we might want to delete pods with a certain label here.
    # For now, we just clear the in-memory dictionary.
    sandboxes.clear()
    # TODO: Add logic to delete actual K8s pods if needed.

@app.post("/api/sandboxes")
async def create_sandbox():
    sandbox_id = f"sb-{uuid.uuid4().hex[:8]}"
    
    # Initialize K8s client
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    
    api = client.CustomObjectsApi()
    
    claim = {
        "apiVersion": "extensions.agents.x-k8s.io/v1alpha1",
        "kind": "SandboxClaim",
        "metadata": {
            "name": sandbox_id,
            "namespace": "default"
        },
        "spec": {
            "sandboxTemplateRef": {
                "name": "agent-sandbox-template"
            }
        }
    }
    
    try:
        api.create_namespaced_custom_object(
            group="extensions.agents.x-k8s.io",
            version="v1alpha1",
            namespace="default",
            plural="sandboxclaims",
            body=claim
        )
        
        sandboxes[sandbox_id] = {
            "status": "Provisioning",
            "pod_ip": None
        }
        
        return {"sandbox_id": sandbox_id, "status": "Provisioning"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create SandboxClaim: {str(e)}")

@app.get("/api/sandboxes")
async def list_sandboxes():
    return [{"sandbox_id": k, "status": v["status"]} for k, v in sandboxes.items()]

@app.post("/api/sandboxes/{sandbox_id}/message")
async def send_message(sandbox_id: str, payload: MessagePayload):
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    sandbox = sandboxes[sandbox_id]
    
    if sandbox["status"] == "Sleeping":
        print(f"Sandbox {sandbox_id} is sleeping. Waking up first.")
        await wake_sandbox(sandbox_id)
        sandbox["status"] = "Running"
    
    # Get Pod IP from SandboxClaim status
    # This is a placeholder logic as schema is not fully known
    pod_ip = "10.0.0.1" # Placeholder
    
    # TODO: Route message to Demo App using pod_ip
    # import httpx
    # async with httpx.AsyncClient() as client:
    #     response = await client.post(f"http://{pod_ip}:8000/message", json={"message": payload.message})
    #     return response.json()
    
    return {"reply": f"[{sandbox_id}] Hello (Simulated routing to {pod_ip})"}

@app.get("/api/sandboxes/{sandbox_id}/quote")
async def get_quote(sandbox_id: str):
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    # Simulate quote routing
    return {"quote": f"Simulated quote from sandbox {sandbox_id}."}

@app.post("/api/sandboxes/{sandbox_id}/sleep")
async def sleep_sandbox(sandbox_id: str):
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    # Simulate sleep by deleting SandboxClaim
    try:
        api = client.CustomObjectsApi()
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
            
        api.delete_namespaced_custom_object(
            group="extensions.agents.x-k8s.io",
            version="v1alpha1",
            namespace="default",
            plural="sandboxclaims",
            name=sandbox_id
        )
        sandboxes[sandbox_id]["status"] = "Sleeping"
        return {"status": "Sleeping"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sleep sandbox: {str(e)}")

@app.post("/api/sandboxes/{sandbox_id}/wake")
async def wake_sandbox(sandbox_id: str):
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    # Simulate wake by recreating SandboxClaim
    try:
        api = client.CustomObjectsApi()
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
            
        claim = {
            "apiVersion": "extensions.agents.x-k8s.io/v1alpha1",
            "kind": "SandboxClaim",
            "metadata": {
                "name": sandbox_id,
                "namespace": "default"
            },
            "spec": {
                "sandboxTemplateRef": {
                    "name": "agent-sandbox-template"
                }
            }
        }
        
        api.create_namespaced_custom_object(
            group="extensions.agents.x-k8s.io",
            version="v1alpha1",
            namespace="default",
            plural="sandboxclaims",
            body=claim
        )
        sandboxes[sandbox_id]["status"] = "Running"
        return {"status": "Running"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to wake sandbox: {str(e)}")
