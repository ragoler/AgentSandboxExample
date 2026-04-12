import os
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

# Initialize Gemini Client
# It will automatically use GEMINI_API_KEY from the environment.
client = genai.Client()

class MessagePayload(BaseModel):
    message: str

@app.post("/message")
async def reply_message(payload: MessagePayload, x_sandbox_id: str = Header(default="UNKNOWN_SANDBOX")):
    return {"reply": f"[{x_sandbox_id}] {payload.message}"}

@app.get("/quote")
async def get_quote():
    logger.info("Received request for quote")
    try:
        logger.info("Calling Gemini generate_content...")
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
        logger.info("Gemini responded successfully")
        return {"quote": response.text}
    except asyncio.TimeoutError:
        logger.error("Vertex AI request timed out")
        raise HTTPException(status_code=504, detail="Vertex AI request timed out")
    except Exception as e:
        logger.error(f"Error generating quote: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
