class MockResponse:
    def __init__(self, data):
        self.data = data
        
    def json(self):
        return self.data

class MockSandboxClient:
    def __init__(self, sandbox_id):
        self.sandbox_id = sandbox_id
        
    def _request(self, method, path, json=None):
        if path == "message":
            return MockResponse({"reply": f"[{self.sandbox_id}] {json['message']}"})
        elif path == "quote":
            return MockResponse({"quote": f"[{self.sandbox_id}] Simulated quote: The only way to do great work is to love what you do."})
        else:
            raise Exception(f"Unknown path {path}")
            
    def _create_claim(self):
        pass
        
    def _wait_for_sandbox_ready(self):
        pass
        
    def _wait_for_gateway_ip(self):
        pass
        
    def terminate(self):
        pass
