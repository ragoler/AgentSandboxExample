import os
import uuid
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, List
from contextlib import asynccontextmanager
from kubernetes import client, config
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

import sys
sys.path.append(str(Path(__file__).parent))

MODE = os.environ.get("MODE", "MOCK").upper()
GATEWAY_NAME = os.environ.get("GATEWAY_NAME", "external-http-gateway")

if MODE == "REAL":
    from k8s_agent_sandbox import SandboxClient
elif MODE == "MOCK":
    from mock_sandbox import MockSandboxClient

# In-Memory State
# sandbox_id -> { "status": "Running" | "Sleeping", "pod_ip": "..." }
sandboxes: Dict[str, dict] = {}

class MessagePayload(BaseModel):
    message: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Application starting. Clearing all transient sandbox state.")
    # In a real K8s environment, we might want to delete pods with a certain label here.
    # For now, we just clear the in-memory dictionary.
    sandboxes.clear()
    # TODO: Add logic to delete actual K8s pods if needed.
    yield

app = FastAPI(lifespan=lifespan)

@app.post("/api/sandboxes")
async def create_sandbox(background_tasks: BackgroundTasks):
    sandbox_id = f"sb-{uuid.uuid4().hex[:8]}"
    
    if MODE == "MOCK":
        client_instance = MockSandboxClient(sandbox_id)
        sandboxes[sandbox_id] = {
            "status": "Running",
            "client_instance": client_instance
        }
        return {"sandbox_id": sandbox_id, "status": "Running"}
        
    elif MODE == "REAL":
        try:
            client_instance = SandboxClient(
                template_name="agent-sandbox-template",
                gateway_name=GATEWAY_NAME,
                namespace="default",
                server_port=8888
            )
            
            sandboxes[sandbox_id] = {
                "status": "Provisioning",
                "client_instance": client_instance
            }
            
            def create_and_wait():
                print(f"[{sandbox_id}] Starting async sandbox creation...")
                try:
                    print(f"[{sandbox_id}] Creating SandboxClaim...")
                    client_instance._create_claim()
                    print(f"[{sandbox_id}] Waiting for Sandbox to be ready...")
                    client_instance._wait_for_sandbox_ready()
                    print(f"[{sandbox_id}] Waiting for Gateway IP...")
                    client_instance._wait_for_gateway_ip()
                    
                    sandboxes[sandbox_id]["status"] = "Running"
                    print(f"[{sandbox_id}] Sandbox is now Running.")
                except Exception as e:
                    sandboxes[sandbox_id]["status"] = "Error"
                    print(f"[{sandbox_id}] Error in background creation: {e}")
            
            background_tasks.add_task(create_and_wait)
            
            return {"sandbox_id": sandbox_id, "status": "Provisioning"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to initiate Sandbox creation: {str(e)}")

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
    
    client_instance = sandbox.get("client_instance")
    if not client_instance:
         raise HTTPException(status_code=500, detail="Client instance not found")
         
    try:
        print(f"[{sandbox_id}] Routing message to client...")
        response = client_instance._request("POST", "message", json={"message": payload.message})
        print(f"[{sandbox_id}] Message routed successfully.")
        return response.json()
    except Exception as e:
         raise HTTPException(status_code=500, detail=f"Failed to route message via client: {str(e)}")

@app.get("/api/sandboxes/{sandbox_id}/quote")
async def get_quote(sandbox_id: str):
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    sandbox = sandboxes[sandbox_id]
    
    if sandbox["status"] == "Sleeping":
        print(f"Sandbox {sandbox_id} is sleeping. Waking up first.")
        await wake_sandbox(sandbox_id)
        sandbox["status"] = "Running"
    
    client_instance = sandbox.get("client_instance")
    if not client_instance:
         raise HTTPException(status_code=500, detail="Client instance not found")
         
    try:
        print(f"[{sandbox_id}] Getting quote from client...")
        response = client_instance._request("GET", "quote")
        print(f"[{sandbox_id}] Quote retrieved successfully.")
        return response.json()
    except Exception as e:
         raise HTTPException(status_code=500, detail=f"Failed to get quote via client: {str(e)}")

@app.post("/api/sandboxes/{sandbox_id}/sleep")
async def sleep_sandbox(sandbox_id: str):
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    if MODE == "MOCK":
        sandboxes[sandbox_id]["status"] = "Sleeping"
        return {"status": "Sleeping"}
        
    elif MODE == "REAL":
        # TODO: Implement documented sleep mechanism using client if available, or delete claim.
        # README doesn't show sleep/wake explicitly.
        raise HTTPException(status_code=501, detail="Sleep not implemented for Real mode yet")

@app.post("/api/sandboxes/{sandbox_id}/wake")
async def wake_sandbox(sandbox_id: str):
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    if MODE == "MOCK":
        sandboxes[sandbox_id]["status"] = "Running"
        return {"status": "Running"}
        
    elif MODE == "REAL":
        # TODO: Implement documented wake mechanism using client.
        raise HTTPException(status_code=501, detail="Wake not implemented for Real mode yet")

@app.delete("/api/sandboxes/{sandbox_id}")
async def delete_sandbox(sandbox_id: str):
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    sandbox = sandboxes[sandbox_id]
    client_instance = sandbox.get("client_instance")
    
    if client_instance:
        try:
            client_instance.terminate()
        except Exception as e:
             print(f"Error terminating sandbox: {e}")
             
    del sandboxes[sandbox_id]
    return {"status": "Deleted"}

# Mount Static Files for Frontend
current_dir = Path(__file__).parent
frontend_dir = current_dir.parent / "frontend"

app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
