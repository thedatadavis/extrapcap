import os
import time
import uuid
import httpx


class CloudflareAPIClient:
    """HTTP client used by Modal functions to interact with Cloudflare D1 via Pages API."""

    def __init__(self):
        self.base_url = os.environ.get("CF_APP_URL", "https://extrapcap.pages.dev").rstrip("/")
        self.token = os.environ.get("CF_API_TOKEN", "")
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.client = httpx.Client(base_url=self.base_url, headers=self.headers, timeout=30.0)

    def register_run(self, workflow: str) -> str:
        run_id = f"modal-{uuid.uuid4().hex[:12]}"
        try:
            self.client.post("/api/runs", json={
                "run_id": run_id,
                "workflow": workflow,
                "status": "running",
            })
        except Exception as e:
            print(f"Warning: Failed to register run {run_id}: {e}")
        return run_id

    def complete_run(self, run_id: str, summary: dict, start_time: float = None):
        duration_s = time.time() - start_time if start_time else None
        try:
            self.client.patch("/api/runs", json={
                "run_id": run_id,
                "status": "completed",
                "summary": summary,
                "duration_s": duration_s,
            })
        except Exception as e:
            print(f"Warning: Failed to complete run {run_id}: {e}")

    def fail_run(self, run_id: str, error: str, start_time: float = None):
        duration_s = time.time() - start_time if start_time else None
        try:
            self.client.patch("/api/runs", json={
                "run_id": run_id,
                "status": "failed",
                "error": error,
                "duration_s": duration_s,
            })
        except Exception as e:
            print(f"Warning: Failed to fail run {run_id}: {e}")

    def append_events(self, events: list[dict], run_id: str = None):
        if not events:
            return
        payload = [{"run_id": run_id, **evt} if run_id else evt for evt in events]
        try:
            self.client.post("/api/events", json=payload)
        except Exception as e:
            print(f"Warning: Failed to append events: {e}")

    def get_active_positions(self) -> list[dict]:
        try:
            res = self.client.get("/api/positions?active=true")
            return res.json() if res.status_code == 200 else []
        except Exception as e:
            print(f"Warning: Failed to fetch active positions: {e}")
            return []

    def close_position(self, pos_id: int, reason: str, run_id: str = None):
        try:
            self.client.patch("/api/positions", json={
                "id": pos_id,
                "run_id": run_id,
                "is_active": False,
                "close_reason": reason,
                "closed_at": time.strftime("%Y-%m-%d"),
            })
        except Exception as e:
            print(f"Warning: Failed to close position {pos_id}: {e}")

    def get_bars(self, symbol: str = None, limit: int = 5000) -> list[dict]:
        try:
            url = f"/api/bars?symbol={symbol}&limit={limit}" if symbol else f"/api/bars?limit={limit}"
            res = self.client.get(url)
            return res.json() if res.status_code == 200 else []
        except Exception as e:
            print(f"Warning: Failed to fetch bars: {e}")
            return []

    def upsert_bars(self, bars: list[dict]):
        if not bars:
            return
        try:
            self.client.post("/api/bars", json=bars)
        except Exception as e:
            print(f"Warning: Failed to upsert bars: {e}")

    def get_universe(self, symbol: str = None, sector: str = None) -> list[dict]:
        try:
            params = []
            if symbol:
                params.append(f"symbol={symbol}")
            if sector:
                params.append(f"sector={sector}")
            url = f"/api/universe?{'&'.join(params)}" if params else "/api/universe"
            res = self.client.get(url)
            return res.json() if res.status_code == 200 else []
        except Exception as e:
            print(f"Warning: Failed to fetch universe: {e}")
            return []

    def store_universe(self, rows: list[dict]):
        if not rows:
            return
        try:
            self.client.post("/api/universe", json=rows)
        except Exception as e:
            print(f"Warning: Failed to store universe: {e}")

    def get_risk_events(self, symbol: str = None, event_type: str = None) -> list[dict]:
        try:
            params = []
            if symbol:
                params.append(f"symbol={symbol}")
            if event_type:
                params.append(f"type={event_type}")
            url = f"/api/risk_events?{'&'.join(params)}" if params else "/api/risk_events"
            res = self.client.get(url)
            return res.json() if res.status_code == 200 else []
        except Exception as e:
            print(f"Warning: Failed to fetch risk events: {e}")
            return []

    def store_risk_events(self, events: list[dict]):
        if not events:
            return
        try:
            self.client.post("/api/risk_events", json=events)
        except Exception as e:
            print(f"Warning: Failed to store risk events: {e}")

    def store_basket(self, as_of: str, rows: list[dict], run_id: str = None):
        try:
            self.client.post("/api/basket", json={"as_of": as_of, "run_id": run_id, "rows": rows})
        except Exception as e:
            print(f"Warning: Failed to store basket: {e}")

    def get_basket(self, as_of: str = None, run_id: str = None) -> list[dict]:
        try:
            params = []
            if as_of:
                params.append(f"as_of={as_of}")
            if run_id:
                params.append(f"run_id={run_id}")
            url = f"/api/basket?{'&'.join(params)}" if params else "/api/basket"
            res = self.client.get(url)
            return res.json() if res.status_code == 200 else []
        except Exception as e:
            print(f"Warning: Failed to fetch basket from D1: {e}")
            return []

    def record_account(self, snapshot: dict, run_id: str = None):
        try:
            payload = {"run_id": run_id, **snapshot} if run_id else snapshot
            self.client.post("/api/account", json=payload)
        except Exception as e:
            print(f"Warning: Failed to record account snapshot: {e}")
