import os
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, List
from contextlib import asynccontextmanager
from kubernetes import client, config
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

MODE = os.environ.get("MODE", "MOCK").upper()
GATEWAY_NAME = os.environ.get("GATEWAY_NAME", "external-http-gateway")

if MODE == "REAL":
    from k8s_agent_sandbox import SandboxClient
    from k8s_agent_sandbox.models import SandboxGatewayConnectionConfig

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
async def create_sandbox():
    sandbox_id = f"sb-{uuid.uuid4().hex[:8]}"
    
    if MODE == "MOCK":
        sandboxes[sandbox_id] = {
            "status": "Running",
            "pod_ip": "127.0.0.1"
        }
        return {"sandbox_id": sandbox_id, "status": "Running"}
        
    elif MODE == "REAL":
        try:
            client_instance = SandboxClient(
                connection_config=SandboxGatewayConnectionConfig(
                    gateway_name=GATEWAY_NAME,
                )
            )
            # Create sandbox using client
            # We assume the template exists as per infra manifests
            sandbox = client_instance.create_sandbox(template="agent-sandbox-template", namespace="default")
            
            sandboxes[sandbox_id] = {
                "status": "Provisioning",
                "client_sandbox": sandbox
            }
            
            return {"sandbox_id": sandbox_id, "status": "Provisioning"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to create Sandbox via client: {str(e)}")

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
    
    if MODE == "MOCK":
        # Simulate demo-app behavior (reply with sandbox ID)
        return {"reply": f"[{sandbox_id}] {payload.message}"}
        
    elif MODE == "REAL":
        client_sandbox = sandbox.get("client_sandbox")
        if not client_sandbox:
             raise HTTPException(status_code=500, detail="Client sandbox instance not found")
             
        # Run curl command inside sandbox to call the Demo App
        import json
        cmd = f"curl -s -X POST http://localhost:8000/message -H 'Content-Type: application/json' -d '{{\"message\": \"{payload.message}\"}}'"
        try:
            result = client_sandbox.commands.run(cmd)
            reply_data = json.loads(result.stdout)
            return reply_data
        except Exception as e:
             raise HTTPException(status_code=500, detail=f"Failed to run command in sandbox: {str(e)}")

@app.get("/api/sandboxes/{sandbox_id}/quote")
async def get_quote(sandbox_id: str):
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    if MODE == "MOCK":
        # Simulate demo-app behavior
        return {"quote": f"[{sandbox_id}] Simulated quote: The only way to do great work is to love what you do."}
        
    elif MODE == "REAL":
        client_sandbox = sandboxes[sandbox_id].get("client_sandbox")
        if not client_sandbox:
             raise HTTPException(status_code=500, detail="Client sandbox instance not found")
             
        # Run curl command inside sandbox to call the Demo App
        import json
        cmd = "curl -s http://localhost:8000/quote"
        try:
            result = client_sandbox.commands.run(cmd)
            reply_data = json.loads(result.stdout)
            return reply_data
        except Exception as e:
             raise HTTPException(status_code=500, detail=f"Failed to run command in sandbox: {str(e)}")

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

# Mount Static Files for Frontend
current_dir = Path(__file__).parent
frontend_dir = current_dir.parent / "frontend"

app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
