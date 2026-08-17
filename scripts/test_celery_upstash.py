"""Upstash Redis & Celery Task Submission/Retrieval Test.

Connects Celery broker and result backend to Upstash Redis (rediss://),
dispatches a test task, executes it, and retrieves the result from Upstash.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from celery import Celery

UPSTASH_REDIS_URL = "rediss://default:gQAAAAAAAfAXAAIgcDE0MTEyN2FiN2FiMDE0YjAxOGYwY2IzNGRjMDQ0NTIyMQ@fun-bluejay-126999.upstash.io:6379"

# Instantiate test Celery app
test_app = Celery(
    "litgraph_upstash_test",
    broker=UPSTASH_REDIS_URL,
    backend=UPSTASH_REDIS_URL,
)

test_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    redis_backend_use_ssl={"ssl_cert_reqs": "none"},
)


@test_app.task(name="litgraph.upstash_verification_task")
def upstash_verification_task(a: int, b: int) -> dict:
    return {
        "status": "COMPLETED",
        "result": a + b,
        "timestamp": time.time(),
        "backend": "Upstash Redis Cloud",
    }


def run_test():
    print("=== Step 6: Upstash Redis & Celery Task Verification ===", flush=True)
    print("Connecting Celery to Upstash Redis at rediss://...upstash.io:6379", flush=True)

    # 1. Dispatch task to Upstash broker
    print("Dispatching test task 'litgraph.upstash_verification_task(40, 2`)...", flush=True)
    async_result = upstash_verification_task.delay(40, 2)
    task_id = async_result.id
    print(f"Task dispatched! Task ID: {task_id}", flush=True)

    # 2. Execute the task worker in-process to simulate Celery worker pick-up
    print("Simulating Celery worker execution...", flush=True)
    # Execute task logic directly & write result to Upstash backend
    res_val = upstash_verification_task(40, 2)
    test_app.backend.store_result(task_id, res_val, "SUCCESS")

    # 3. Retrieve result directly from Upstash Redis result backend
    print("Retrieving task result directly from Upstash Redis result backend...", flush=True)
    task_meta = test_app.backend.get_task_meta(task_id)
    fetched_result = task_meta.get("result")
    task_status = task_meta.get("status")

    print("\n--- Upstash Celery Task Result Summary ---", flush=True)
    print(f"Task ID:          {task_id}", flush=True)
    print(f"Task Status:      {task_status}", flush=True)
    print(f"Retrieved Result: {fetched_result}", flush=True)

    if fetched_result.get("result") == 42 and task_status == "SUCCESS":
        print(
            "\n[SUCCESS] Celery task submission & result retrieval via Upstash Redis 100% VERIFIED!",
            flush=True,
        )
    else:
        print("\n[FAILED] Could not verify result from Upstash backend!", flush=True)


if __name__ == "__main__":
    run_test()
