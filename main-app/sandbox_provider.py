import os
from dotenv import load_dotenv

load_dotenv(override=True)
MODE = os.environ.get("MODE", "MOCK").upper()
GATEWAY_NAME = os.environ.get("GATEWAY_NAME", "external-http-gateway")

if MODE == "REAL":
    from k8s_agent_sandbox import SandboxClient
    from kubernetes import client, config
    
    class RealSandboxWrapper:
        def __init__(self, sandbox_id):
            self.sandbox_id = sandbox_id
            self.client = SandboxClient(
                template_name="agent-sandbox-template",
                gateway_name=GATEWAY_NAME,
                namespace="default",
                server_port=8888
            )
            
        def create(self):
            self.client._create_claim()
            self.client._wait_for_sandbox_ready()
            self.client._wait_for_gateway_ip()
            
            # Health check (Require 3 consecutive successes to ensure stability)
            import time
            health_ok = False
            consecutive_successes = 0
            time.sleep(1.0)
            for _ in range(600):
                try:
                    response = self.client._request("GET", "healthz")
                    if response.status_code == 200:
                        health_ok = True
                        break
                except Exception:
                    pass
                time.sleep(0.2)
            return health_ok

        def request(self, method, path, json=None):
             import time
             for _ in range(30):
                 try:
                     resp = self.client._request(method, path, json=json)
                     if resp.status_code != 502:
                         return resp
                     print(f"Got 502 from gateway, retrying in 1s...")
                 except Exception as e:
                      print(f"Request error: {e}, retrying in 1s...")
                 time.sleep(1.0)
             return self.client._request(method, path, json=json)
             
        def terminate(self):
             try:
                 with open("debug.txt", "a") as f:
                     f.write(f"base_url: {self.client.base_url}\n")
                     
                 config.load_kube_config()
                 api = client.CustomObjectsApi()
                 api.delete_namespaced_custom_object(
                     group="extensions.agents.x-k8s.io",
                     version="v1alpha1",
                     namespace="default",
                     plural="sandboxclaims",
                     name=self.client.claim_name
                 )
                 print(f"Deleted SandboxClaim {self.client.claim_name}")
             except Exception as e:
                 print(f"Failed to delete SandboxClaim {self.client.claim_name}: {e}")

        def sleep(self):
             try:
                 config.load_kube_config()
                 api = client.CustomObjectsApi()
                 body = {
                     "metadata": {
                         "labels": {
                             "extensions.agents.x-k8s.io/state": "sleeping"
                         }
                     }
                 }
                 api.patch_namespaced_custom_object(
                     group="extensions.agents.x-k8s.io",
                     version="v1alpha1",
                     namespace="default",
                     plural="sandboxclaims",
                     name=self.client.claim_name,
                     body=body
                 )
                 return "Sleeping"
             except Exception as e:
                 print(f"Failed to sleep sandbox {self.sandbox_id}: {e}")
                 raise e

        def wake(self):
             try:
                 config.load_kube_config()
                 api = client.CustomObjectsApi()
                 body = {
                     "metadata": {
                         "labels": {
                             "extensions.agents.x-k8s.io/state": "running"
                         }
                     }
                 }
                 api.patch_namespaced_custom_object(
                     group="extensions.agents.x-k8s.io",
                     version="v1alpha1",
                     namespace="default",
                     plural="sandboxclaims",
                     name=self.client.claim_name,
                     body=body
                 )
                 return "Running"
             except Exception as e:
                 print(f"Failed to wake sandbox {self.sandbox_id}: {e}")
                 raise e

    def get_client(sandbox_id):
        return RealSandboxWrapper(sandbox_id)
        
    def cleanup_all():
        print("Cleaning up SandboxClaims in Kubernetes...")
        try:
            config.load_kube_config()
            api = client.CustomObjectsApi()
            claims = api.list_namespaced_custom_object(
                group="extensions.agents.x-k8s.io",
                version="v1alpha1",
                namespace="default",
                plural="sandboxclaims"
            )
            for claim in claims.get('items', []):
                name = claim['metadata']['name']
                print(f"Deleting SandboxClaim: {name}")
                try:
                    api.delete_namespaced_custom_object(
                        group="extensions.agents.x-k8s.io",
                        version="v1alpha1",
                        namespace="default",
                        plural="sandboxclaims",
                        name=name
                    )
                except Exception as e:
                    print(f"Failed to delete {name}: {e}")
            print("Cleanup of SandboxClaims complete.")
        except Exception as e:
            print(f"Failed to list SandboxClaims for cleanup: {e}")

    def get_stats(sandboxes_dict=None):
        try:
            config.load_kube_config()
            api = client.CustomObjectsApi()
            claims = api.list_namespaced_custom_object(
                group="extensions.agents.x-k8s.io",
                version="v1alpha1",
                namespace="default",
                plural="sandboxclaims"
            )
            items = claims.get('items', [])
            total = len(items)
            running = 0
            provisioning = 0
            sleeping = 0
            error = 0
            
            for claim in items:
                metadata = claim.get('metadata', {})
                labels = metadata.get('labels', {})
                if labels.get('extensions.agents.x-k8s.io/state') == 'sleeping':
                    sleeping += 1
                    continue
                    
                status = claim.get('status', {})
                conditions = status.get('conditions', [])
                is_ready = False
                is_error = False
                for c in conditions:
                    if c.get('type') == 'Ready' and c.get('status') == 'True':
                        is_ready = True
                        break
                    if c.get('status') == 'False' and c.get('reason') in ['Failed', 'Error']:
                        is_error = True
                        
                if is_ready:
                    running += 1
                elif is_error:
                    error += 1
                else:
                    provisioning += 1
                    
            return {
                "total": total,
                "running": running,
                "provisioning": provisioning,
                "sleeping": sleeping,
                "error": error
            }
        except Exception as e:
            print(f"Failed to get stats from K8s: {e}")
            return {"total": 0, "running": 0, "provisioning": 0, "sleeping": 0, "error": 0, "error_msg": str(e)}

elif MODE == "MOCK":
    from mock_sandbox import MockSandboxClient
    
    class MockSandboxWrapper:
        def __init__(self, sandbox_id):
            self.sandbox_id = sandbox_id
            self.client = MockSandboxClient(sandbox_id)
            
        def create(self):
            self.client._create_claim()
            self.client._wait_for_sandbox_ready()
            self.client._wait_for_gateway_ip()
            return True
            
        def request(self, method, path, json=None):
            return self.client._request(method, path, json=json)
            
        def terminate(self):
            self.client.terminate()

        def sleep(self):
            return "Sleeping"

        def wake(self):
            return "Running"

    def get_client(sandbox_id):
        return MockSandboxWrapper(sandbox_id)
        
    def cleanup_all():
        print("Mock cleanup: nothing to do.")
        pass

    def get_stats(sandboxes_dict=None):
        if sandboxes_dict is None:
            return {"total": 0, "running": 0, "provisioning": 0, "sleeping": 0, "error": 0}
        
        stats = {"total": len(sandboxes_dict), "running": 0, "sleeping": 0, "provisioning": 0, "error": 0}
        for v in sandboxes_dict.values():
            status = v.get('status', '').lower()
            if status in stats:
                stats[status] += 1
        return stats
