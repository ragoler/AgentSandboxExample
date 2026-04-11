import os
import pytest
from fastapi.testclient import TestClient

# Set environment before importing app to ensure Mock mode
os.environ["MODE"] = "MOCK"

# We need to make sure we can import from the parent directory or current directory
# If we run pytest from main-app directory, it should work.
from main import app, sandboxes

client = TestClient(app)

def test_create_sandbox_mock():
    # Clear state
    sandboxes.clear()
    
    response = client.post("/api/sandboxes")
    assert response.status_code == 200
    data = response.json()
    assert "sandbox_id" in data
    assert data["status"] == "Running"
    assert data["sandbox_id"] in sandboxes

def test_send_message_mock():
    sandboxes.clear()
    create_resp = client.post("/api/sandboxes")
    sb_id = create_resp.json()["sandbox_id"]
    
    response = client.post(f"/api/sandboxes/{sb_id}/message", json={"message": "Hello"})
    assert response.status_code == 200
    assert response.json()["reply"] == f"[{sb_id}] Hello"

def test_get_quote_mock():
    sandboxes.clear()
    create_resp = client.post("/api/sandboxes")
    sb_id = create_resp.json()["sandbox_id"]
    
    response = client.get(f"/api/sandboxes/{sb_id}/quote")
    assert response.status_code == 200
    assert "quote" in response.json()
    assert response.json()["quote"].startswith(f"[{sb_id}] Simulated quote:")

def test_sleep_wake_mock():
    sandboxes.clear()
    create_resp = client.post("/api/sandboxes")
    sb_id = create_resp.json()["sandbox_id"]
    
    # Sleep
    response = client.post(f"/api/sandboxes/{sb_id}/sleep")
    assert response.status_code == 200
    assert response.json()["status"] == "Sleeping"
    assert sandboxes[sb_id]["status"] == "Sleeping"
    
    # Message while sleeping should auto-wake
    response = client.post(f"/api/sandboxes/{sb_id}/message", json={"message": "Wake up"})
    assert response.status_code == 200
    assert response.json()["reply"] == f"[{sb_id}] Wake up"
    assert sandboxes[sb_id]["status"] == "Running"

def test_get_quote_while_sleeping_mock():
    sandboxes.clear()
    create_resp = client.post("/api/sandboxes")
    sb_id = create_resp.json()["sandbox_id"]
    
    # Sleep
    client.post(f"/api/sandboxes/{sb_id}/sleep")
    assert sandboxes[sb_id]["status"] == "Sleeping"
    
    # Quote while sleeping should auto-wake
    response = client.get(f"/api/sandboxes/{sb_id}/quote")
    assert response.status_code == 200
    assert "quote" in response.json()
    assert sandboxes[sb_id]["status"] == "Running"
