import os
from fastapi import FastAPI
from pydantic import BaseModel
import vertexai
from vertexai.generative_models import GenerativeModel
from dotenv import load_dotenv

load_dotenv()

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

sandbox_id = os.environ.get("SANDBOX_ID", "UNKNOWN_SANDBOX")

class MessagePayload(BaseModel):
    message: str

@app.post("/message")
async def reply_message(payload: MessagePayload):
    return {"reply": f"[{sandbox_id}] {payload.message}"}

@app.get("/quote")
async def get_quote():
    try:
        response = model.generate_content("Provide a short, inspiring quote of the day.")
        return {"quote": response.text}
    except Exception as e:
        return {"error": str(e)}, 500

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
