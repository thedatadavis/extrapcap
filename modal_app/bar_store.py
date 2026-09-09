"""Persistent market-bar storage for Modal workflows.

Market bars are analytical inputs, not transactional state. Store them as
immutable date partitions on the shared Modal Volume so daily refreshes do not
rewrite the full history in D1.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

BAR_COLUMNS = ["date", "symbol", "open", "high", "low", "close", "volume", "vwap"]
DEFAULT_BAR_ROOT = "/data/market_bars"
DEFAULT_RETENTION_DAYS = 365
EASTERN = ZoneInfo("America/New_York")


def _session_dates(frame: pd.DataFrame) -> pd.Series:
    dates = pd.to_datetime(frame["date"], utc=True)
    return dates.dt.tz_convert(EASTERN).dt.date


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=BAR_COLUMNS)
    missing = set(BAR_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"market bars missing required columns: {sorted(missing)}")

    result = frame[BAR_COLUMNS].copy()
    result["date"] = pd.to_datetime(result["date"], utc=True)
    result["symbol"] = result["symbol"].astype(str).str.strip().str.upper()
    if result["symbol"].eq("").any():
        raise ValueError("market bars contain an empty symbol")
    return result.sort_values(["date", "symbol"]).reset_index(drop=True)


def _partition_day(path: Path) -> date | None:
    prefix = "date="
    if not path.name.startswith(prefix):
        return None
    try:
        return date.fromisoformat(path.name[len(prefix) :])
    except ValueError:
        return None


def _commit(volume) -> None:
    commit = getattr(volume, "commit", None)
    if callable(commit):
        try:
            commit()
        except RuntimeError:
            pass


def _reload(volume) -> None:
    reload = getattr(volume, "reload", None)
    if callable(reload):
        try:
            reload()
        except RuntimeError:
            pass


def write_bar_partitions(
    frame: pd.DataFrame,
    volume,
    *,
    root: str = DEFAULT_BAR_ROOT,
    retention_days: int | None = DEFAULT_RETENTION_DAYS,
    reference_date: date | None = None,
) -> dict:
    """Write missing completed-session partitions and prune old partitions.

    Existing partitions are immutable by default. A later backfill can delete
    a specific partition and rerun the refresh if a historical correction is
    required. One file per date also avoids same-file concurrent writers.
    """
    if retention_days is not None and retention_days < 1:
        raise ValueError("retention_days must be positive or None")

    normalized = _normalize(frame)
    target_root = Path(root)
    target_root.mkdir(parents=True, exist_ok=True)
    written_partitions = 0
    skipped_partitions = 0
    rows_written = 0

    if not normalized.empty:
        normalized["session_date"] = _session_dates(normalized)
        for session_day, day_frame in normalized.groupby("session_date", sort=True):
            partition_dir = target_root / f"date={session_day.isoformat()}"
            target = partition_dir / "bars.parquet"
            if target.exists():
                skipped_partitions += 1
                continue

            partition_dir.mkdir(parents=True, exist_ok=True)
            temporary = partition_dir / "bars.parquet.tmp"
            day_frame[BAR_COLUMNS].to_parquet(
                temporary,
                index=False,
                engine="pyarrow",
                compression="zstd",
            )
            temporary.replace(target)
            written_partitions += 1
            rows_written += len(day_frame)

    purged_partitions = 0
    if retention_days is not None:
        cutoff = (reference_date or datetime.now(EASTERN).date()) - timedelta(
            days=retention_days
        )
        for partition_dir in target_root.glob("date=*"):
            if not partition_dir.is_dir():
                continue
            session_day = _partition_day(partition_dir)
            if session_day is None or session_day >= cutoff:
                continue
            for child in partition_dir.iterdir():
                if child.is_file():
                    child.unlink()
            partition_dir.rmdir()
            purged_partitions += 1

    if written_partitions or purged_partitions:
        _commit(volume)

    return {
        "root": str(target_root),
        "input_rows": len(normalized),
        "rows_written": rows_written,
        "partitions_written": written_partitions,
        "partitions_skipped": skipped_partitions,
        "partitions_purged": purged_partitions,
    }


def read_bar_partitions(
    volume,
    *,
    root: str = DEFAULT_BAR_ROOT,
    reload: bool = True,
) -> pd.DataFrame:
    """Read all persisted market-bar partitions from the shared Volume."""
    if reload:
        _reload(volume)

    target_root = Path(root)
    paths = sorted(target_root.glob("date=*/bars.parquet"))
    if not paths:
        raise RuntimeError("Modal Volume contains no market bars; run data_refresh first")

    frames = [pd.read_parquet(path, columns=BAR_COLUMNS, engine="pyarrow") for path in paths]
    return _normalize(pd.concat(frames, ignore_index=True))
