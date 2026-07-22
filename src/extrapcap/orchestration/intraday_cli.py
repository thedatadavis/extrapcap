from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os

from .live_cycle import run_live_cycle


def expiration_window(now: datetime, minimum_days: int = 2, maximum_days: int = 35) -> tuple[str, str]:
    if minimum_days < 1 or maximum_days < minimum_days:
        raise ValueError("expiration day bounds are invalid")
    return (
        (now + timedelta(days=minimum_days)).date().isoformat(),
        (now + timedelta(days=maximum_days)).date().isoformat(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one provider-backed intraday Extrapcap scan")
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--model", default=os.getenv("SNIPER_MODEL_PATH"))
    parser.add_argument("--execution-mode", choices=("dry-run", "paper-submit"), default="dry-run")
    parser.add_argument("--minimum-expiration-days", type=int, default=2)
    parser.add_argument("--maximum-expiration-days", type=int, default=35)
    args = parser.parse_args()
    if not args.model:
        parser.error("--model or SNIPER_MODEL_PATH is required")
    lower, upper = expiration_window(datetime.now(timezone.utc), args.minimum_expiration_days, args.maximum_expiration_days)
    print(json.dumps(run_live_cycle(args.symbol, args.model, lower, upper, args.execution_mode, "1Min"), indent=2))


if __name__ == "__main__":
    main()
