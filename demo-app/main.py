import os
import time
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from google import genai
from dotenv import load_dotenv
import asyncio
import logging

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Initialize Gemini Client.
# Supports two authentication modes:
#   1. Workload Identity (recommended): Set GOOGLE_GENAI_USE_VERTEXAI=TRUE.
#      Authenticates automatically via the GKE metadata server — no API keys needed.
#   2. API Key (fallback): Set GEMINI_API_KEY and GOOGLE_GENAI_USE_VERTEXAI=FALSE.
USE_VERTEXAI = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "FALSE").upper() == "TRUE"
if USE_VERTEXAI:
    client = genai.Client(
        vertexai=True,
        project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        location=os.environ.get("REGION", "us-central1"),
    )
    logger.info("Gemini client initialized with Vertex AI (Workload Identity)")
else:
    client = genai.Client()
    logger.info("Gemini client initialized with API key")

class MessagePayload(BaseModel):
    message: str

@app.post("/message")
async def reply_message(payload: MessagePayload, x_sandbox_id: str = Header(default="UNKNOWN_SANDBOX")):
    logger.info(f"Received message request for sandbox {x_sandbox_id}")
    return {"reply": f"[{x_sandbox_id}] {payload.message}"}

@app.get("/quote")
async def get_quote():
    logger.info("Received request for quote")
    try:
        logger.info("Calling Gemini generate_content...")
        start_time = time.time()
        loop = asyncio.get_running_loop()
        def call_gemini():
            return client.models.generate_content(
                model='gemini-2.5-flash',
                contents="Provide a short, inspiring quote of the day."
            )
        response = await asyncio.wait_for(
            loop.run_in_executor(None, call_gemini),
            timeout=30.0
        )
        logger.info(f"Gemini responded successfully. Took {time.time() - start_time:.2f}s")
        return {"quote": response.text}
    except asyncio.TimeoutError:
        logger.error(f"Vertex AI request timed out after {time.time() - start_time:.2f}s")
        raise HTTPException(status_code=504, detail="Vertex AI request timed out")
    except Exception as e:
        logger.error(f"Error generating quote after {time.time() - start_time:.2f}s: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
