import asyncio
import httpx
import time

BASE_URL = "http://127.0.0.1:8000"
NUM_SANDBOXES = 5

async def create_and_test_sandbox(client, index):
    print(f"[{index}] Creating sandbox...")
    start_time = time.time()
    try:
        resp = await client.post(f"{BASE_URL}/api/sandboxes")
        assert resp.status_code == 200
        data = resp.json()
        sb_id = data["sandbox_id"]
        print(f"[{index}] Created sandbox {sb_id}")
    except Exception as e:
        print(f"[{index}] Failed to create sandbox: {e}")
        return False

    # Wait for ready
    ready = False
    for _ in range(120):  # 120 seconds timeout
        try:
            resp = await client.get(f"{BASE_URL}/api/sandboxes")
            assert resp.status_code == 200
            sandboxes = resp.json()
            matched = [s for s in sandboxes if s['sandbox_id'] == sb_id]
            if matched:
                status = matched[0]['status']
                if status == "Running":
                    ready = True
                    duration = time.time() - start_time
                    print(f"[{index}] Sandbox {sb_id} is ready in {duration:.2f}s")
                    break
                elif status == "Error":
                    print(f"[{index}] Sandbox {sb_id} went into Error state")
                    return False
        except Exception as e:
            print(f"[{index}] Error polling status: {e}")
            
        await asyncio.sleep(1)

    if not ready:
        print(f"[{index}] Sandbox {sb_id} timed out waiting for ready")
        return False

    # Send messages
    for i in range(3):
        msg = f"Message {i} from test {index}"
        print(f"[{index}] Sending message to {sb_id}: {msg}")
        try:
            resp = await client.post(f"{BASE_URL}/api/sandboxes/{sb_id}/message", json={"message": msg}, timeout=30.0)
            if resp.status_code != 200:
                 print(f"[{index}] Failed to send message to {sb_id}: {resp.status_code}")
                 return False
            print(f"[{index}] Reply from {sb_id}: {resp.json()['reply']}")
        except Exception as e:
            print(f"[{index}] Error sending message: {e}")
            return False
        await asyncio.sleep(0.5)

    # Delete
    print(f"[{index}] Deleting sandbox {sb_id}...")
    try:
        resp = await client.delete(f"{BASE_URL}/api/sandboxes/{sb_id}")
        assert resp.status_code == 200
        print(f"[{index}] Deleted sandbox {sb_id}")
    except Exception as e:
        print(f"[{index}] Failed to delete sandbox: {e}")
        return False
        
    return True

async def main():
    async with httpx.AsyncClient(timeout=60.0) as client:
        tasks = [create_and_test_sandbox(client, i) for i in range(NUM_SANDBOXES)]
        results = await asyncio.gather(*tasks)
        
        success_count = sum(1 for r in results if r)
        print(f"\nTest finished. Success: {success_count}/{NUM_SANDBOXES}")

if __name__ == "__main__":
    asyncio.run(main())
