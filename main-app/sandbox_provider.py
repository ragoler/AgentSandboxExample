import os
from dotenv import load_dotenv
import logging

load_dotenv(override=True)
MODE = os.environ.get("MODE", "MOCK").upper()
GATEWAY_NAME = os.environ.get("GATEWAY_NAME", "external-http-gateway")

logger = logging.getLogger(__name__)

if MODE == "REAL":
    import time
    from kubernetes import client, config

    # k8s-agent-sandbox 0.4.6 ships the GKE Pod Snapshot extension, which lets us
    # *actually* suspend (snapshot + scale Sandbox to 0 replicas) and resume
    # (scale back to 1 + restore from snapshot) instead of just toggling a label.
    from k8s_agent_sandbox.gke_extensions.snapshots.podsnapshot_client import (
        PodSnapshotSandboxClient,
    )
    from k8s_agent_sandbox.models import SandboxGatewayConnectionConfig

    TEMPLATE_NAME = "agent-sandbox-template"
    NAMESPACE = "default"
    SERVER_PORT = 8888

    def load_k8s_config():
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

    # PodSnapshot API coordinates (GKE Pod Snapshots).
    _PS_GROUP = "podsnapshot.gke.io"
    _PS_VERSION = "v1"
    _PS_PLURAL = "podsnapshots"
    _PS_ORIGIN_POD_ANNOTATION = "podsnapshot.gke.io/origin-pod"

    def _delete_snapshots_for_pod(pod_name):
        """Delete every PodSnapshot whose origin pod is pod_name, returning the
        list of deleted snapshot names. Deleting the PodSnapshot CR makes the GKE
        controller garbage-collect the backing checkpoint files in the bucket."""
        deleted = []
        if not pod_name:
            return deleted
        try:
            load_k8s_config()
            api = client.CustomObjectsApi()
            snaps = api.list_namespaced_custom_object(
                group=_PS_GROUP, version=_PS_VERSION, namespace=NAMESPACE, plural=_PS_PLURAL
            )
            for snap in snaps.get("items", []):
                md = snap.get("metadata", {})
                origin = (md.get("annotations") or {}).get(_PS_ORIGIN_POD_ANNOTATION)
                if origin == pod_name:
                    name = md.get("name")
                    try:
                        api.delete_namespaced_custom_object(
                            group=_PS_GROUP, version=_PS_VERSION, namespace=NAMESPACE,
                            plural=_PS_PLURAL, name=name
                        )
                        deleted.append(name)
                    except Exception as e:
                        logger.warning(f"Failed to delete PodSnapshot {name}: {e}")
        except Exception as e:
            logger.error(f"Failed to list/delete PodSnapshots for pod {pod_name}: {e}")
        return deleted

    # A single shared client. 0.4.6 resolves warm-pool adoption natively
    # (SandboxClaim.status.sandbox.name), so the 0.2.1 monkeypatches are gone.
    # The gateway connection strategy routes requests through the sandbox-router
    # via the external Gateway, injecting the X-Sandbox-* headers automatically.
    _shared_client = None

    def _client():
        global _shared_client
        if _shared_client is None:
            _shared_client = PodSnapshotSandboxClient(
                connection_config=SandboxGatewayConnectionConfig(
                    gateway_name=GATEWAY_NAME,
                    gateway_namespace=NAMESPACE,
                    server_port=SERVER_PORT,
                )
            )
        return _shared_client

    class RealSandboxWrapper:
        def __init__(self, sandbox_id):
            # sandbox_id is the main-app's local id (e.g. "sb-abcd1234").
            self.sandbox_id = sandbox_id
            self.sandbox = None  # SandboxWithSnapshotSupport handle (set on create)

        @property
        def claim_name(self):
            return self.sandbox.claim_name if self.sandbox else None

        def create(self):
            logger.info(f"[{self.sandbox_id}] Creating sandbox via PodSnapshotSandboxClient...")
            start_time = time.time()
            # create_sandbox blocks until the claim is bound to a (warm-pool) Sandbox
            # and that Sandbox reports Ready.
            self.sandbox = _client().create_sandbox(
                template=TEMPLATE_NAME,
                namespace=NAMESPACE,
                sandbox_ready_timeout=180,
            )
            logger.info(
                f"[{self.sandbox_id}] Bound to Sandbox '{self.sandbox.sandbox_id}' "
                f"(claim '{self.sandbox.claim_name}'). Health-checking via gateway..."
            )

            # Require the demo-app to answer /healthz through the gateway before we
            # report Running (the L7 LB / router can lag behind pod readiness).
            health_ok = False
            time.sleep(1.0)
            for _ in range(600):
                try:
                    response = self.sandbox.connector.send_request("GET", "healthz")
                    if response.status_code == 200:
                        health_ok = True
                        break
                except Exception:
                    pass
                time.sleep(0.2)
            logger.info(
                f"[{self.sandbox_id}] Health check result: {health_ok}. "
                f"Took {time.time() - start_time:.2f}s"
            )
            return health_ok

        def request(self, method, path, json=None):
            if not self.sandbox:
                raise RuntimeError("Sandbox has not been created yet.")
            start_time = time.time()
            for i in range(30):
                try:
                    resp = self.sandbox.connector.send_request(method, path, json=json)
                    if resp.status_code != 502:
                        logger.info(
                            f"[{self.sandbox_id}] Request {method} {path} succeeded on "
                            f"attempt {i+1}. Took {time.time() - start_time:.2f}s"
                        )
                        return resp
                    logger.warning(
                        f"[{self.sandbox_id}] Got 502 from gateway, retrying in 1s... (Attempt {i+1})"
                    )
                except Exception as e:
                    logger.warning(
                        f"[{self.sandbox_id}] Request error: {e}, retrying in 1s... (Attempt {i+1})"
                    )
                time.sleep(1.0)
            logger.error(f"[{self.sandbox_id}] Request {method} {path} failed after 30 attempts.")
            return self.sandbox.connector.send_request(method, path, json=json)

        def terminate(self):
            if not self.sandbox:
                return
            try:
                _client().delete_sandbox(self.sandbox.claim_name, NAMESPACE)
                logger.info(f"[{self.sandbox_id}] Deleted SandboxClaim {self.sandbox.claim_name}")
            except Exception as e:
                logger.error(f"[{self.sandbox_id}] Failed to delete sandbox: {e}")

        def sleep(self):
            # Real suspend: snapshot the running pod (GKE Pod Snapshots), then scale
            # the Sandbox CR to 0 replicas so the pod is terminated and stops billing.
            if not self.sandbox:
                raise RuntimeError("Sandbox has not been created yet.")
            start_time = time.time()
            resp = self.sandbox.suspend(snapshot_before_suspend=True)
            if not resp.success:
                logger.error(f"[{self.sandbox_id}] Suspend failed: {resp.error_reason}")
                raise RuntimeError(f"Failed to suspend sandbox: {resp.error_reason}")
            logger.info(
                f"[{self.sandbox_id}] Suspended (snapshot taken, scaled to 0). "
                f"Took {time.time() - start_time:.2f}s"
            )
            return "Sleeping"

        def wake(self):
            # Real resume: scale the Sandbox CR back to 1 replica; the controller
            # restores the pod from the latest snapshot.
            if not self.sandbox:
                raise RuntimeError("Sandbox has not been created yet.")
            start_time = time.time()

            # The pod name we restore from (Sandbox name == warm-pool pod name here)
            # is the origin pod recorded on the PodSnapshot we'll delete afterwards.
            origin_pod = self.sandbox.get_pod_name() or self.sandbox.sandbox_id

            resp = self.sandbox.resume()
            if not resp.success:
                logger.error(f"[{self.sandbox_id}] Resume failed: {resp.error_reason}")
                raise RuntimeError(f"Failed to resume sandbox: {resp.error_reason}")
            logger.info(
                f"[{self.sandbox_id}] Resumed (restored_from_snapshot="
                f"{resp.restored_from_snapshot}). Took {time.time() - start_time:.2f}s"
            )

            # Delete the snapshot(s) the restore happened from so they don't pile up
            # across sleep/wake cycles. The SDK's label-based lookup doesn't match how
            # the GKE controller labels PodSnapshots, so we match on the
            # podsnapshot.gke.io/origin-pod annotation directly. Deleting the
            # PodSnapshot triggers the controller to GC its bucket checkpoint files.
            deleted = _delete_snapshots_for_pod(origin_pod)
            if deleted:
                logger.info(
                    f"[{self.sandbox_id}] Deleted {len(deleted)} restored-from "
                    f"snapshot(s) for pod {origin_pod}: {deleted}"
                )
            else:
                logger.warning(
                    f"[{self.sandbox_id}] No snapshots found to delete for pod {origin_pod}."
                )

            return "Running"

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
                namespace=NAMESPACE,
                plural="sandboxclaims"
            )
            for claim in claims.get('items', []):
                name = claim['metadata']['name']
                print(f"Deleting SandboxClaim: {name}")
                try:
                    api.delete_namespaced_custom_object(
                        group="extensions.agents.x-k8s.io",
                        version="v1alpha1",
                        namespace=NAMESPACE,
                        plural="sandboxclaims",
                        name=name
                    )
                except Exception as e:
                    print(f"Failed to delete {name}: {e}")
            print("Cleanup of SandboxClaims complete.")
        except Exception as e:
            print(f"Failed to list SandboxClaims for cleanup: {e}")

    def get_stats(sandboxes_dict=None):
        # main-app is the source of truth for per-sandbox status (it drives the
        # Provisioning -> Running -> Sleeping/Error transitions and clears state on
        # restart), so derive counts from the in-memory dict.
        if not sandboxes_dict:
            return {"total": 0, "running": 0, "provisioning": 0, "sleeping": 0, "error": 0}
        stats = {"total": len(sandboxes_dict), "running": 0, "provisioning": 0, "sleeping": 0, "error": 0}
        for v in sandboxes_dict.values():
            status = v.get('status', '').lower()
            if status in stats:
                stats[status] += 1
        return stats

    # Snapshot bucket object counter. Every suspend writes a Pod Snapshot to this
    # GCS bucket, so the count visibly grows each time someone sleeps a sandbox.
    SNAPSHOT_BUCKET_NAME = os.environ.get("SNAPSHOT_BUCKET_NAME") or (
        f"{os.environ.get('PROJECT_NAME', '')}-sandbox-snapshots"
    )
    _snapshot_count_cache = {"value": 0, "ts": 0.0}

    def get_snapshot_count():
        # Each Pod Snapshot is stored as a folder of ~4 files under
        # sandbox-checkpoints/<snapshot-id>/ (checkpoint.img, metadata, pages.img,
        # pages_meta.img). Count distinct snapshot folders so the number reflects
        # how many snapshots exist (one per suspend), not raw object count.
        # Cache briefly so the 5s UI poll doesn't list the bucket on every request.
        now = time.time()
        if now - _snapshot_count_cache["ts"] < 3.0:
            return _snapshot_count_cache["value"]
        try:
            from google.cloud import storage
            storage_client = storage.Client()
            snapshot_ids = set()
            for b in storage_client.list_blobs(SNAPSHOT_BUCKET_NAME):
                if b.name.endswith("/"):
                    continue
                parts = b.name.split("/")
                # The immediate parent "folder" of each object is one snapshot.
                if len(parts) >= 2 and parts[-2]:
                    snapshot_ids.add(parts[-2])
            count = len(snapshot_ids)
            _snapshot_count_cache["value"] = count
            _snapshot_count_cache["ts"] = now
            return count
        except Exception as e:
            logger.error(f"Failed to count snapshots in bucket: {e}")
            # Return last known value rather than failing the whole stats poll.
            return _snapshot_count_cache["value"]

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

    def get_snapshot_count():
        # No real bucket in mock mode.
        return 0
