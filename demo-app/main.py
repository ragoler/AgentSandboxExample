import os
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
import vertexai
from vertexai.generative_models import GenerativeModel
from dotenv import load_dotenv
import asyncio
import logging

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Initialize Vertex AI
# We assume GOOGLE_CLOUD_PROJECT and REGION are set in the environment or .env file.
project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
region = os.environ.get("REGION")
if project_id:
    vertexai.init(project=project_id, location=region)
else:
    print("Warning: GOOGLE_CLOUD_PROJECT environment variable not set. Vertex AI might fail to initialize.")
    vertexai.init(location=region)

model = GenerativeModel("gemini-2.5-flash")

class MessagePayload(BaseModel):
    message: str

@app.post("/message")
async def reply_message(payload: MessagePayload, x_sandbox_id: str = Header(default="UNKNOWN_SANDBOX")):
    return {"reply": f"[{x_sandbox_id}] {payload.message}"}

@app.get("/quote")
async def get_quote():
    logger.info("Received request for quote")
    try:
        logger.info("Mocking Vertex AI call...")
        await asyncio.sleep(1)
        logger.info("Mock Vertex AI responded successfully")
        return {"quote": "This is a mock quote from the sandbox!"}
    except asyncio.TimeoutError:
        logger.error("Vertex AI request timed out")
        raise HTTPException(status_code=504, detail="Vertex AI request timed out")
    except Exception as e:
        logger.error(f"Error generating quote: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
