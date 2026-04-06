import os
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, List

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
    
    # TODO: Implement actual GKE Agent Sandbox creation based on documentation.
    # Since we are blocked on documentation, we will simulate it in memory.
    
    sandboxes[sandbox_id] = {
        "status": "Running",
        "pod_ip": "10.0.0.1" # Placeholder
    }
    
    return {"sandbox_id": sandbox_id, "status": "Running"}

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
        # TODO: Implement documented wake-up mechanism.
        sandbox["status"] = "Running"
    
    # TODO: Route message to the Demo App in the sandbox.
    # This requires actual Pod IP and network access.
    
    return {"reply": f"Routed message to {sandbox_id} (Simulated)"}

@app.get("/api/sandboxes/{sandbox_id}/quote")
async def get_quote(sandbox_id: str):
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    # TODO: Route request to Demo App in the sandbox.
    return {"quote": f"Simulated quote from sandbox {sandbox_id}."}

@app.post("/api/sandboxes/{sandbox_id}/sleep")
async def sleep_sandbox(sandbox_id: str):
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    # TODO: Implement documented sleep mechanism.
    sandboxes[sandbox_id]["status"] = "Sleeping"
    return {"status": "Sleeping"}

@app.post("/api/sandboxes/{sandbox_id}/wake")
async def wake_sandbox(sandbox_id: str):
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    # TODO: Implement documented wake mechanism.
    sandboxes[sandbox_id]["status"] = "Running"
    return {"status": "Running"}
