import os
import time
import uuid
import httpx


class CloudflareAPIClient:
    """HTTP client used by Modal functions to interact with Cloudflare D1 via Pages API."""

    def __init__(self):
        self.base_url = os.environ.get("CF_APP_URL", "https://extrapcap.pages.dev").rstrip("/")
        self.token = os.environ.get("CF_API_TOKEN", "")
        self.headers = {
            "User-Agent": "Mozilla/5.0 (compatible; ExtrapcapModal/1.0)",
            "Origin": self.base_url,
        }
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"
        self.client = httpx.Client(base_url=self.base_url, headers=self.headers, timeout=30.0)

    @staticmethod
    def _require_success(response, operation: str):
        status = getattr(response, "status_code", 500)
        if 200 <= status < 300:
            return response
        detail = getattr(response, "text", "")
        raise RuntimeError(f"Cloudflare {operation} failed (HTTP {status}): {detail}")

    def register_run(self, workflow: str) -> str:
        run_id = f"modal-{uuid.uuid4().hex[:12]}"
        response = self.client.post("/api/runs", json={
            "run_id": run_id,
            "workflow": workflow,
            "status": "running",
        })
        self._require_success(response, "run registration")
        return run_id

    def complete_run(self, run_id: str, summary: dict, start_time: float = None):
        duration_s = time.time() - start_time if start_time else None
        response = self.client.patch("/api/runs", json={
            "run_id": run_id,
            "status": "completed",
            "summary": summary,
            "duration_s": duration_s,
        })
        self._require_success(response, "run completion")

    def fail_run(self, run_id: str, error: str, start_time: float = None):
        duration_s = time.time() - start_time if start_time else None
        response = self.client.patch("/api/runs", json={
                "run_id": run_id,
                "status": "failed",
                "error": error,
                "duration_s": duration_s,
            })
        self._require_success(response, "run failure update")

    def append_events(self, events: list[dict], run_id: str = None):
        if not events:
            return
        payload = [{"run_id": run_id, **evt} if run_id else evt for evt in events]
        res = self.client.post("/api/events", json=payload)
        self._require_success(res, "event append")

    def get_active_positions(self) -> list[dict]:
        res = self._require_success(self.client.get("/api/positions?active=true"), "active positions read")
        data = res.json()
        if not isinstance(data, list):
            raise RuntimeError("Cloudflare active positions response was not a list")
        return data

    def close_position(self, pos_id: int, reason: str, run_id: str = None):
        response = self.client.patch("/api/positions", json={
                "id": pos_id,
                "run_id": run_id,
                "is_active": False,
                "close_reason": reason,
                "closed_at": time.strftime("%Y-%m-%d"),
            })
        self._require_success(response, "position close")

    def get_bars(self, symbol: str = None, limit: int = 5000) -> list[dict]:
        url = f"/api/bars?symbol={symbol}&limit={limit}" if symbol else f"/api/bars?limit={limit}"
        res = self._require_success(self.client.get(url), "bars read")
        data = res.json()
        if not isinstance(data, list):
            raise RuntimeError("Cloudflare bars response was not a list")
        return data

    def upsert_bars(self, bars: list[dict], batch_size: int = 500):
        if not bars:
            return
        if batch_size < 1:
            raise ValueError("bar batch size must be positive")
        for offset in range(0, len(bars), batch_size):
            response = self.client.post("/api/bars", json=bars[offset:offset + batch_size])
            self._require_success(response, "bar upsert")

    def get_universe(self, symbol: str = None, sector: str = None) -> list[dict]:
        params = []
        if symbol:
            params.append(f"symbol={symbol}")
        if sector:
            params.append(f"sector={sector}")
        url = f"/api/universe?{'&'.join(params)}" if params else "/api/universe"
        res = self._require_success(self.client.get(url), "universe read")
        data = res.json()
        if not isinstance(data, list):
            raise RuntimeError("Cloudflare universe response was not a list")
        return data

    def store_universe(self, rows: list[dict]):
        if not rows:
            return
        response = self.client.post("/api/universe", json=rows)
        self._require_success(response, "universe upsert")

    def get_risk_events(self, symbol: str = None, event_type: str = None) -> list[dict]:
        params = []
        if symbol:
            params.append(f"symbol={symbol}")
        if event_type:
            params.append(f"type={event_type}")
        url = f"/api/risk_events?{'&'.join(params)}" if params else "/api/risk_events"
        res = self._require_success(self.client.get(url), "risk events read")
        data = res.json()
        if not isinstance(data, list):
            raise RuntimeError("Cloudflare risk events response was not a list")
        return data

    def store_risk_events(self, events: list[dict]):
        if not events:
            return
        response = self.client.post("/api/risk_events", json=events)
        self._require_success(response, "risk event append")

    def store_basket(self, as_of: str, rows: list[dict], run_id: str = None):
        response = self.client.post(
            "/api/basket",
            json={"as_of": as_of, "run_id": run_id, "rows": rows},
        )
        self._require_success(response, "basket upsert")

    def get_basket(self, as_of: str = None, run_id: str = None) -> list[dict]:
        params = [f"_ts={time.time_ns()}"]
        if as_of:
            params.append(f"as_of={as_of}")
        if run_id:
            params.append(f"run_id={run_id}")
        res = self._require_success(self.client.get(f"/api/basket?{'&'.join(params)}"), "basket read")
        data = res.json()
        if not isinstance(data, list):
            raise RuntimeError("Cloudflare basket response was not a list")
        return data

    def record_account(self, snapshot: dict, run_id: str = None):
        payload = {"run_id": run_id, **snapshot} if run_id else snapshot
        self._require_success(self.client.post("/api/account", json=payload), "account snapshot")
