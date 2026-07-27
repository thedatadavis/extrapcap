from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path

from .config import AppConfig
from .improvement import NebiusPolicyLearner, SafePolicyLearner
from .llm.nebius import NebiusReviewer
from .playback import replay_day


def run_improvement_analysis(root: str | Path, trading_day: str, output_dir: str | Path) -> list[Path]:
    events = replay_day(root, trading_day)
    config = AppConfig.from_env()
    config_dict = {
        "z_threshold": config.strategy.z_threshold,
        "max_option_spread_pct": config.strategy.max_option_spread_pct,
        "min_credit_pct_width": config.strategy.min_credit_pct_width,
        "max_candidates": 25,
    }
    learner = NebiusPolicyLearner(reviewer=NebiusReviewer())
    proposals = learner.analyze_and_propose(events, config_dict)
    written_paths = []
    out_dir = Path(output_dir)
    for proposal in proposals:
        path = out_dir / f"proposal-{proposal.parameter}-{trading_day}.json"
        SafePolicyLearner.write(path, proposal)
        written_paths.append(path)
    return written_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Run GLM 5.2 self-improvement policy analysis")
    parser.add_argument("--root", default="logs")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--output-dir", default="logs/proposals")
    args = parser.parse_args()
    paths = run_improvement_analysis(args.root, args.date, args.output_dir)
    print(json.dumps({"status": "completed", "proposals_written": len(paths), "paths": [str(p) for p in paths]}, indent=2))


if __name__ == "__main__":
    main()
