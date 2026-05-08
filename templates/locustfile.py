"""Starter locustfile for Step 2 API baselines.

Edit the @task weights to mirror real traffic. If you don't know the real
distribution, ask the user — do NOT invent one. The wrong mix produces a
correct-looking baseline against the wrong workload, and every later
"speedup" is meaningless.

Run:
    locust -f locustfile.py --headless \\
        --users 50 --spawn-rate 10 --run-time 2m \\
        --host http://localhost:PORT \\
        --csv baseline
"""
from locust import HttpUser, between, task


class WorkloadUser(HttpUser):
    # Time each simulated user waits between tasks. Tune to match real
    # think-time; 0.5–2s is a generic "humans clicking around" default.
    wait_time = between(0.5, 2.0)

    @task(10)  # weight = relative frequency
    def hot_endpoint(self):
        self.client.get("/api/most-called", name="GET /api/most-called")

    @task(3)
    def warm_endpoint(self):
        self.client.post(
            "/api/sometimes-called",
            json={"k": "v"},
            name="POST /api/sometimes-called",
        )

    @task(1)
    def cold_endpoint(self):
        self.client.get("/api/rarely-called", name="GET /api/rarely-called")
