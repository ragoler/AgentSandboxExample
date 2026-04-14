import os
import uuid
import time
import threading
import logging
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
    logger.info(f"[{sandbox_id}] Received request to create sandbox")
    
    client_instance = get_client(sandbox_id)
    
    sandboxes[sandbox_id] = {
        "status": "Provisioning",
        "client_instance": client_instance,
        "created_at": time.time()
    }
    
    def create_and_wait():
        logger.info(f"[{sandbox_id}] Starting async sandbox creation...")
        start_time = time.time()
        success = client_instance.create()
        duration = time.time() - start_time
        if success:
            sandboxes[sandbox_id]["status"] = "Running"
            sandboxes[sandbox_id]["duration"] = duration
            logger.info(f"[{sandbox_id}] Sandbox is now Running and healthy. Took {duration:.2f}s")
        else:
            sandboxes[sandbox_id]["status"] = "Error"
            logger.info(f"[{sandbox_id}] Sandbox health check failed or creation timed out. Took {duration:.2f}s")
            
    background_tasks.add_task(create_and_wait)
    
    return {"sandbox_id": sandbox_id, "status": "Provisioning"}

@app.get("/api/sandboxes")
async def list_sandboxes():
    logger.info("Listing sandboxes")
    return [{"sandbox_id": k, "status": v["status"], "duration": v.get("duration")} for k, v in sandboxes.items()]

@app.get("/api/stats")
def get_stats_endpoint():
    logger.info("Getting stats")
    from sandbox_provider import get_stats
    return get_stats(sandboxes)

@app.post("/api/sandboxes/{sandbox_id}/message")
def send_message(sandbox_id: str, payload: MessagePayload):
    logger.info(f"[{sandbox_id}] Received message request")
    if sandbox_id not in sandboxes:
        logger.warning(f"[{sandbox_id}] Sandbox not found for message request")
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    sandbox = sandboxes[sandbox_id]
    
    if sandbox["status"] == "Sleeping":
        logger.warning(f"[{sandbox_id}] Sandbox is sleeping, rejecting message request")
        raise HTTPException(status_code=400, detail="Sandbox is sleeping. Please wake it up first.")
    
    client_instance = sandbox.get("client_instance")
    if not client_instance:
         logger.error(f"[{sandbox_id}] Client instance not found in state")
         raise HTTPException(status_code=500, detail="Client instance not found")
         
    try:
        logger.info(f"[{sandbox_id}] Routing message to client...")
        start_time = time.time()
        response = client_instance.request("POST", "message", json={"message": payload.message})
        logger.info(f"[{sandbox_id}] Message routed successfully. Took {time.time() - start_time:.2f}s")
        return response.json()
    except Exception as e:
         logger.error(f"[{sandbox_id}] Failed to route message: {str(e)}")
         raise HTTPException(status_code=500, detail=f"Failed to route message via client: {str(e)}")

@app.get("/api/sandboxes/{sandbox_id}/quote")
def get_quote(sandbox_id: str):
    logger.info(f"[{sandbox_id}] Received quote request")
    if sandbox_id not in sandboxes:
        logger.warning(f"[{sandbox_id}] Sandbox not found for quote request")
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    sandbox = sandboxes[sandbox_id]
    
    if sandbox["status"] == "Sleeping":
        logger.warning(f"[{sandbox_id}] Sandbox is sleeping, rejecting quote request")
        raise HTTPException(status_code=400, detail="Sandbox is sleeping. Please wake it up first.")
    
    client_instance = sandbox.get("client_instance")
    if not client_instance:
         logger.error(f"[{sandbox_id}] Client instance not found in state")
         raise HTTPException(status_code=500, detail="Client instance not found")
         
    try:
        logger.info(f"[{sandbox_id}] Getting quote from client...")
        start_time = time.time()
        response = client_instance.request("GET", "quote")
        logger.info(f"[{sandbox_id}] Quote retrieved successfully. Took {time.time() - start_time:.2f}s")
        return response.json()
    except Exception as e:
         logger.error(f"[{sandbox_id}] Failed to get quote: {str(e)}")
         raise HTTPException(status_code=500, detail=f"Failed to get quote via client: {str(e)}")

@app.post("/api/sandboxes/{sandbox_id}/sleep")
def sleep_sandbox(sandbox_id: str):
    logger.info(f"[{sandbox_id}] Received sleep request")
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    try:
        start_time = time.time()
        new_status = sandboxes[sandbox_id]["client_instance"].sleep()
        logger.info(f"[{sandbox_id}] Sleep completed. Status: {new_status}. Took {time.time() - start_time:.2f}s")
        sandboxes[sandbox_id]["status"] = new_status
        return {"status": new_status}
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))

@app.post("/api/sandboxes/{sandbox_id}/wake")
def wake_sandbox(sandbox_id: str):
    logger.info(f"[{sandbox_id}] Received wake request")
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    try:
        start_time = time.time()
        new_status = sandboxes[sandbox_id]["client_instance"].wake()
        logger.info(f"[{sandbox_id}] Wake completed. Status: {new_status}. Took {time.time() - start_time:.2f}s")
        sandboxes[sandbox_id]["status"] = new_status
        return {"status": new_status}
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))

@app.delete("/api/sandboxes/{sandbox_id}")
async def delete_sandbox(sandbox_id: str):
    logger.info(f"[{sandbox_id}] Received delete request")
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    sandbox = sandboxes[sandbox_id]
    client_instance = sandbox.get("client_instance")
    
    if client_instance:
        try:
            logger.info(f"[{sandbox_id}] Terminating sandbox...")
            start_time = time.time()
            client_instance.terminate()
            logger.info(f"[{sandbox_id}] Terminated successfully. Took {time.time() - start_time:.2f}s")
        except Exception as e:
             logger.error(f"[{sandbox_id}] Error terminating sandbox: {e}")
             
    del sandboxes[sandbox_id]
    return {"status": "Deleted"}

# Mount Static Files for Frontend
current_dir = Path(__file__).parent
frontend_dir = current_dir.parent / "frontend"

app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
