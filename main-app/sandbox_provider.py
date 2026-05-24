import os
from dotenv import load_dotenv
import logging

load_dotenv(override=True)
MODE = os.environ.get("MODE", "MOCK").upper()
GATEWAY_NAME = os.environ.get("GATEWAY_NAME", "external-http-gateway")

logger = logging.getLogger(__name__)

if MODE == "REAL":
    from k8s_agent_sandbox import SandboxClient
    from kubernetes import client, config, watch
    import time
    import requests
    import logging
    
    # Monkeypatch SandboxClient._wait_for_sandbox_ready to watch SandboxClaims instead of Sandboxes
    # This ensures compatibility between k8s-agent-sandbox 0.2.1 and SandboxWarmPool adoption logic.
    def patched_wait_for_sandbox_ready(self):
        if not self.claim_name:
            raise RuntimeError("Cannot wait for sandbox; a sandboxclaim has not been created.")
        w = watch.Watch()
        logger.info(f"Watching for SandboxClaim {self.claim_name} to become ready...")
        for event in w.stream(
            func=self.custom_objects_api.list_namespaced_custom_object,
            namespace=self.namespace,
            group="extensions.agents.x-k8s.io",
            version="v1alpha1",
            plural="sandboxclaims",
            field_selector=f"metadata.name={self.claim_name}",
            timeout_seconds=self.sandbox_ready_timeout
        ):
            if event["type"] in ["ADDED", "MODIFIED"]:
                claim_object = event['object']
                status = claim_object.get('status', {})
                conditions = status.get('conditions', [])
                is_ready = False
                for cond in conditions:
                    if cond.get('type') == 'Ready' and cond.get('status') == 'True':
                        is_ready = True
                        break
                if is_ready:
                    sandbox_ref = status.get('sandbox', {})
                    self.sandbox_name = sandbox_ref.get('Name') or sandbox_ref.get('name')
                    if not self.sandbox_name:
                        self.sandbox_name = self.claim_name
                    logger.info(f"SandboxClaim {self.claim_name} is ready. Bound to sandbox {self.sandbox_name}.")
                    self.annotations = claim_object.get('metadata', {}).get('annotations', {})
                    pod_name = self.annotations.get("sandboxtemplate.extensions.agents.x-k8s.io/pod-name")
                    if pod_name:
                        self.pod_name = pod_name
                    else:
                        self.pod_name = self.sandbox_name
                    w.stop()
                    return
        self.__exit__(None, None, None)
        raise TimeoutError(f"SandboxClaim did not become ready within {self.sandbox_ready_timeout} seconds.")

    def patched_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        if not self.is_ready():
            raise RuntimeError("Sandbox is not ready for communication.")

        if self.port_forward_process and self.port_forward_process.poll() is not None:
            _, stderr = self.port_forward_process.communicate()
            raise RuntimeError(f"Kubectl Port-Forward crashed BEFORE request!\nStderr: {stderr.decode(errors='ignore')}")

        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"

        headers = kwargs.get("headers", {})
        headers["X-Sandbox-ID"] = getattr(self, 'sandbox_name', None) or self.claim_name
        headers["X-Sandbox-Namespace"] = self.namespace
        headers["X-Sandbox-Port"] = str(self.server_port)
        kwargs["headers"] = headers

        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            if self.port_forward_process and self.port_forward_process.poll() is not None:
                _, stderr = self.port_forward_process.communicate()
                raise RuntimeError(f"Kubectl Port-Forward crashed DURING request!\nStderr: {stderr.decode(errors='ignore')}") from e

            logging.error(f"Request to gateway router failed: {e}")
            raise RuntimeError(f"Failed to communicate with the sandbox via the gateway at {url}.") from e

    SandboxClient._wait_for_sandbox_ready = patched_wait_for_sandbox_ready
    SandboxClient._request = patched_request

    def load_k8s_config():
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
            
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
            logger.info(f"[{self.sandbox_id}] Creating claim...")
            import time
            start_time = time.time()
            self.client._create_claim()
            logger.info(f"[{self.sandbox_id}] Claim created. Waiting for ready...")
            self.client._wait_for_sandbox_ready()
            logger.info(f"[{self.sandbox_id}] Sandbox ready. Waiting for gateway IP...")
            self.client._wait_for_gateway_ip()
            logger.info(f"[{self.sandbox_id}] Gateway IP acquired. Starting health check...")
            
            # Health check (Require 3 consecutive successes to ensure stability)
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
            logger.info(f"[{self.sandbox_id}] Health check result: {health_ok}. Took {time.time() - start_time:.2f}s")
            return health_ok

        def request(self, method, path, json=None):
             import time
             start_time = time.time()
             for i in range(30):
                 try:
                     resp = self.client._request(method, path, json=json)
                     if resp.status_code != 502:
                         logger.info(f"[{self.sandbox_id}] Request {method} {path} succeeded on attempt {i+1}. Took {time.time() - start_time:.2f}s")
                         return resp
                     logger.warning(f"[{self.sandbox_id}] Got 502 from gateway, retrying in 1s... (Attempt {i+1})")
                 except Exception as e:
                      logger.warning(f"[{self.sandbox_id}] Request error: {e}, retrying in 1s... (Attempt {i+1})")
                 time.sleep(1.0)
             logger.error(f"[{self.sandbox_id}] Request {method} {path} failed after 30 attempts.")
             return self.client._request(method, path, json=json)
             
        def terminate(self):
             try:
                 load_k8s_config()
                 api = client.CustomObjectsApi()
                 api.delete_namespaced_custom_object(
                     group="extensions.agents.x-k8s.io",
                     version="v1alpha1",
                     namespace="default",
                     plural="sandboxclaims",
                     name=self.client.claim_name
                 )
                 logger.info(f"Deleted SandboxClaim {self.client.claim_name}")
             except Exception as e:
                 logger.error(f"Failed to delete SandboxClaim {self.client.claim_name}: {e}")
 
        def sleep(self):
             try:
                 load_k8s_config()
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
                 logger.error(f"Failed to sleep sandbox {self.sandbox_id}: {e}")
                 raise e
 
        def wake(self):
             try:
                 load_k8s_config()
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
                 logger.error(f"Failed to wake sandbox {self.sandbox_id}: {e}")
                 raise e

    def get_client(sandbox_id):
        return RealSandboxWrapper(sandbox_id)
        
    def cleanup_all():
        print("Cleaning up SandboxClaims in Kubernetes...")
        try:
            load_k8s_config()
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
            load_k8s_config()
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
