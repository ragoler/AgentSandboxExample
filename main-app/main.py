import os
import uuid
import time
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

from sandbox_provider import get_client, cleanup_all

# In-Memory State
# sandbox_id -> { "status": "Running" | "Sleeping", "client_instance": ... }
sandboxes: Dict[str, dict] = {}

class MessagePayload(BaseModel):
    message: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Application starting. Clearing all transient sandbox state.")
    sandboxes.clear()
    cleanup_all()
    yield

app = FastAPI(lifespan=lifespan)

@app.post("/api/sandboxes")
async def create_sandbox(background_tasks: BackgroundTasks):
    sandbox_id = f"sb-{uuid.uuid4().hex[:8]}"
    
    client_instance = get_client(sandbox_id)
    
    sandboxes[sandbox_id] = {
        "status": "Provisioning",
        "client_instance": client_instance,
        "created_at": time.time()
    }
    
    def create_and_wait():
        print(f"[{sandbox_id}] Starting async sandbox creation...")
        success = client_instance.create()
        if success:
            sandboxes[sandbox_id]["status"] = "Running"
            sandboxes[sandbox_id]["duration"] = time.time() - sandboxes[sandbox_id]["created_at"]
            print(f"[{sandbox_id}] Sandbox is now Running and healthy. Took {sandboxes[sandbox_id]['duration']:.2f}s")
        else:
            sandboxes[sandbox_id]["status"] = "Error"
            print(f"[{sandbox_id}] Sandbox health check failed.")
            
    background_tasks.add_task(create_and_wait)
    
    return {"sandbox_id": sandbox_id, "status": "Provisioning"}

@app.get("/api/sandboxes")
async def list_sandboxes():
    return [{"sandbox_id": k, "status": v["status"], "duration": v.get("duration")} for k, v in sandboxes.items()]

@app.get("/api/stats")
async def get_stats_endpoint():
    from sandbox_provider import get_stats
    return get_stats(sandboxes)

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
        response = client_instance.request("POST", "message", json={"message": payload.message})
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
        response = client_instance.request("GET", "quote")
        print(f"[{sandbox_id}] Quote retrieved successfully.")
        return response.json()
    except Exception as e:
         raise HTTPException(status_code=500, detail=f"Failed to get quote via client: {str(e)}")

@app.post("/api/sandboxes/{sandbox_id}/sleep")
async def sleep_sandbox(sandbox_id: str):
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    try:
        new_status = sandboxes[sandbox_id]["client_instance"].sleep()
        sandboxes[sandbox_id]["status"] = new_status
        return {"status": new_status}
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))

@app.post("/api/sandboxes/{sandbox_id}/wake")
async def wake_sandbox(sandbox_id: str):
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    try:
        new_status = sandboxes[sandbox_id]["client_instance"].wake()
        sandboxes[sandbox_id]["status"] = new_status
        return {"status": new_status}
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))

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
