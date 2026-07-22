from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from urllib.request import urlopen


SOURCE_URL = "https://raw.githubusercontent.com/bootstrapital/stockstreaks-registry/main/data/active_tickers.csv"
SOURCE_API_URL = "https://api.github.com/repos/bootstrapital/stockstreaks-registry/contents/data/active_tickers.csv"
INDEX_SECTORS = {"SPY": "Broad Market ETF", "QQQ": "Broad Market ETF", "IWM": "Broad Market ETF"}


@dataclass(frozen=True)
class GreenlistFilter:
    min_avg_volume: int = 1_000_000
    min_market_cap: float | None = None
    allowed_cap_tiers: tuple[str, ...] = ("Mega-Cap", "Large-Cap")
    allowed_exchanges: tuple[str, ...] = ("NMS", "NYQ", "ASE", "BATS")
    require_weekly_options: bool = False
    require_penny_pricing: bool = False
    min_options_volume: int | None = None


def _read_csv(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def filter_greenlist(rows: list[dict[str, str]], policy: GreenlistFilter) -> tuple[list[dict], list[dict]]:
    accepted, decisions = [], []
    for row in rows:
        reasons = []
        try:
            volume = int(row.get("avg_volume", "0"))
        except ValueError:
            volume = 0
        if volume < policy.min_avg_volume:
            reasons.append("avg_volume_below_threshold")
        if row.get("cap_tier") not in policy.allowed_cap_tiers:
            reasons.append("cap_tier_excluded")
        if row.get("exchange") not in policy.allowed_exchanges:
            reasons.append("exchange_excluded")
        if policy.min_market_cap is not None:
            try:
                if float(row.get("market_cap", "0")) < policy.min_market_cap:
                    reasons.append("market_cap_below_threshold")
            except (TypeError, ValueError):
                reasons.append("market_cap_unavailable")
        if policy.require_weekly_options and str(row.get("weekly_options", "")).lower() not in {"1", "true", "yes"}:
            reasons.append("weekly_options_unavailable")
        if policy.require_penny_pricing and str(row.get("penny_pricing", "")).lower() not in {"1", "true", "yes"}:
            reasons.append("penny_pricing_unavailable")
        if policy.min_options_volume is not None:
            try:
                if int(row.get("options_volume", "0")) < policy.min_options_volume:
                    reasons.append("options_activity_below_threshold")
            except (TypeError, ValueError):
                reasons.append("options_activity_unavailable")
        accepted_flag = not reasons
        decision = {"ticker": row.get("ticker"), "accepted": accepted_flag, "reasons": reasons}
        decisions.append(decision)
        if accepted_flag:
            accepted.append(row)
    return accepted, decisions


def refresh_greenlist(output_dir: str | Path = "data/universe", policy: GreenlistFilter | None = None) -> Path:
    """Fetch and pin the registry snapshot plus every filter decision."""
    policy = policy or GreenlistFilter()
    with urlopen(SOURCE_URL, timeout=30) as response:
        raw = response.read().decode("utf-8")
    rows = _read_csv(raw)
    accepted, decisions = filter_greenlist(rows, policy)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot = directory / f"greenlist-{stamp}.csv"
    with snapshot.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(accepted[:1000])
    metadata = {
        "source_url": SOURCE_URL,
        "source_api_url": SOURCE_API_URL,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "raw_rows": len(rows),
        "accepted_rows": len(accepted[:1000]),
        "policy": asdict(policy),
        "decisions": decisions,
    }
    (directory / f"greenlist-{stamp}.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return snapshot


def load_sector_map(path: str | Path | None = None, root: str | Path = "data/universe") -> dict[str, str]:
    if path is None:
        snapshots = sorted(Path(root).glob("greenlist-*.csv"))
        if not snapshots:
            raise RuntimeError("no versioned Greenlist snapshot is available for sector controls")
        target = snapshots[-1]
    else:
        target = Path(path)
    rows = _read_csv(target.read_text(encoding="utf-8"))
    if not rows or not {"ticker", "sector"}.issubset(rows[0]):
        raise RuntimeError("Greenlist snapshot is missing ticker/sector metadata")
    result = dict(INDEX_SECTORS)
    for row in rows:
        ticker = str(row.get("ticker", "")).strip().upper()
        sector = str(row.get("sector", "")).strip()
        if ticker and sector and sector.upper() != "N/A":
            result[ticker] = sector
    return result
