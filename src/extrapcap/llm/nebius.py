from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen


class NebiusReviewer:
    """OpenAI-compatible Nebius reviewer; output is advisory and structured."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None):
        self.base_url = (base_url or os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1")).rstrip("/")
        self.api_key = api_key or os.getenv("NEBIUS_API_KEY")
        self.model = model or os.getenv("NEBIUS_MODEL", "Qwen/Qwen3-30B-A3B-Instruct-2507")

    def _request_json(self, system: str, user: dict) -> dict:
        if not self.api_key:
            return {"decision": "escalate", "reason": "NEBIUS_API_KEY is not configured", "provider": "nebius", "model": self.model}
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user)},
            ],
        }
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=30) as response:
            body = json.loads(response.read())
        content = body["choices"][0]["message"]["content"]
        try:
            judgment = json.loads(content)
        except (TypeError, json.JSONDecodeError):
            return {"decision": "escalate", "reason": "Nebius returned invalid JSON", "provider": "nebius", "model": self.model}
        if not isinstance(judgment, dict):
            return {"decision": "escalate", "reason": "Nebius returned a non-object JSON value", "provider": "nebius", "model": self.model}
        judgment.setdefault("provider", "nebius")
        judgment.setdefault("model", self.model)
        return judgment

    def review(self, candidate: dict, context: str = "") -> dict:
        judgment = self._request_json(
            "Return JSON with decision (go/no-go/escalate), reason, and structural_risk.",
            {"candidate": candidate, "context": context},
        )
        if judgment.get("decision") not in {"go", "no-go", "escalate"}:
            return {"decision": "escalate", "reason": "Nebius returned an invalid decision", "provider": "nebius", "model": self.model}
        judgment.setdefault("reason", "No rationale supplied")
        return judgment

    def classify_headline(self, headline: str, symbol: str | None = None) -> dict:
        judgment = self._request_json(
            "Classify this headline as exactly noise_or_opinion or structural_risk. Return JSON with category, structural_risk, and reason. Do not give trading advice.",
            {"symbol": symbol, "headline": headline},
        )
        category = judgment.get("category")
        structural = judgment.get("structural_risk")
        if category not in {"noise_or_opinion", "structural_risk"} or not isinstance(structural, bool):
            return {
                "category": "escalate",
                "structural_risk": True,
                "reason": "Nebius returned an invalid headline classification",
                "provider": "nebius",
                "model": self.model,
            }
        judgment.setdefault("reason", "No classification rationale supplied")
        return judgment

    def daily_note(self, summary: dict) -> dict:
        """Return a bounded portfolio note; the model cannot change execution state."""
        judgment = self._request_json(
            """Write a concise daily paper-trading note from the supplied ledger summary.
Return JSON with exactly these useful fields: note (string), anomalies (array of strings),
"risk_posture" (normal/watch/escalate), and reason (string). Do not invent trades, prices,
performance, or external news. Treat missing data as an anomaly.""",
            {"summary": summary},
        )
        if not isinstance(judgment.get("note"), str) or not isinstance(judgment.get("anomalies"), list):
            return {
                "note": "Nebius daily note unavailable; review the deterministic ledger report.",
                "anomalies": ["invalid_or_missing_nebius_daily_note"],
                "risk_posture": "escalate",
                "reason": "Nebius returned an invalid daily note",
                "provider": "nebius",
                "model": self.model,
            }
        if judgment.get("risk_posture") not in {"normal", "watch", "escalate"}:
            judgment["risk_posture"] = "escalate"
        judgment.setdefault("reason", "No daily-note rationale supplied")
        return judgment

    def post_trade_commentary(self, observation: dict) -> dict:
        """Summarize an observed paper-order outcome without changing state."""
        judgment = self._request_json(
            """Return JSON with commentary (string), anomalies (array of strings), and reason.
Describe only the supplied order/account/position observation. Do not invent fills,
prices, performance, or external news. Treat missing fields as an anomaly.""",
            {"observation": observation},
        )
        if not isinstance(judgment.get("commentary"), str) or not isinstance(judgment.get("anomalies"), list):
            return {
                "commentary": "Post-trade commentary unavailable; inspect the structured fill observation.",
                "anomalies": ["invalid_or_missing_post_trade_commentary"],
                "reason": "Nebius returned an invalid post-trade payload",
                "provider": "nebius",
                "model": self.model,
            }
        judgment.setdefault("reason", "No post-trade rationale supplied")
        judgment.setdefault("provider", "nebius")
        judgment.setdefault("model", self.model)
        return judgment

    def list_models(self) -> dict:
        if not self.api_key:
            raise RuntimeError("NEBIUS_API_KEY is not configured")
        request = Request(f"{self.base_url}/models", headers={"Authorization": f"Bearer {self.api_key}"})
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read())
