import httpx
import time
import pytest
import subprocess

BASE_URL = "http://127.0.0.1:8000"

@pytest.fixture(autouse=True, scope="module")
def cleanup_sandboxes():
    print("\n[Setup] Cleaning up sandboxes before test...")
    subprocess.run(["./clean_sandboxes.sh"], check=True)
    yield
    print("\n[Teardown] Cleaning up sandboxes after test...")
    subprocess.run(["./clean_sandboxes.sh"], check=True)

def test_e2e_gke():
    # 1. Create Sandbox
    resp = httpx.post(f"{BASE_URL}/api/sandboxes", timeout=120.0)
    assert resp.status_code == 200
    data = resp.json()
    sb_id = data["sandbox_id"]
    print(f"Created sandbox {sb_id}, status: {data['status']}")
    
    # 2. Wait for it to be ready (max 5 minutes)
    timeout = 300
    start_time = time.time()
    ready = False
    
    while time.time() - start_time < timeout:
        resp = httpx.get(f"{BASE_URL}/api/sandboxes", timeout=10.0)
        assert resp.status_code == 200
        sandboxes = resp.json()
        
        # Find our sandbox
        matched = [s for s in sandboxes if s['sandbox_id'] == sb_id]
        if matched:
            status = matched[0]['status']
            print(f"Sandbox {sb_id} status: {status}")
            if status == "Running":
                ready = True
                break
            elif status == "Error":
                pytest.fail("Sandbox went into Error state")
        else:
             print(f"Sandbox {sb_id} not found in list yet")
             
        time.sleep(10)
        
    assert ready, "Timed out waiting for sandbox to be ready"
    
    # 3. Send Message
    resp = httpx.post(f"{BASE_URL}/api/sandboxes/{sb_id}/message", json={"message": "Hello from Integration Test"}, timeout=60.0)
    assert resp.status_code == 200
    print(f"Message reply: {resp.json()['reply']}")
    
    # 4. Get Quote
    resp = httpx.get(f"{BASE_URL}/api/sandboxes/{sb_id}/quote", timeout=60.0)
    assert resp.status_code == 200
    print(f"Quote reply: {resp.json()['quote']}")
    
    # 5. Delete Sandbox (Renumbered or just reordered)
    resp = httpx.delete(f"{BASE_URL}/api/sandboxes/{sb_id}", timeout=60.0)
    assert resp.status_code == 200
    print(f"Deleted sandbox {sb_id}")
