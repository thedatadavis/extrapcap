from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import pandas as pd

from ..config import RiskConfig
from ..events import EventDecision
from ..execution.alpaca import AlpacaPaperClient
from ..fills import FillAssumptions
from ..llm.nebius import NebiusReviewer
from ..orchestration.paper_run import PaperRunCoordinator, build_candidate
from ..risk import PortfolioRiskState
from ..models.sniper import SniperModel
from ..signals import SNIPER_FEATURES


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one chain-backed paper candidate")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--price", required=True, type=float)
    parser.add_argument("--contracts", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--probability", type=float, help="fixture-only probability; paper-submit requires --model")
    parser.add_argument("--model", help="versioned CatBoost Sniper artifact")
    parser.add_argument("--features-json", help="JSON object containing the Sniper feature vector")
    parser.add_argument("--trading-day", default=date.today().isoformat())
    parser.add_argument("--execution-mode", choices=("dry-run", "paper-submit"), default="dry-run")
    args = parser.parse_args()
    if args.execution_mode == "paper-submit" and not args.model:
        parser.error("--model is required for paper-submit")
    if args.model:
        if not args.features_json:
            parser.error("--features-json is required when --model is supplied")
        feature_values = json.loads(Path(args.features_json).read_text(encoding="utf-8"))
        model = SniperModel.load(args.model, SNIPER_FEATURES)
        probability = float(model.predict_probability(pd.DataFrame([feature_values]))[0])
    elif args.probability is not None:
        probability = args.probability
    else:
        parser.error("provide --probability for dry-run or --model with --features-json")
    os.environ["EXTRAPCAP_EXECUTION_MODE"] = args.execution_mode
    contracts = json.loads(Path(args.contracts).read_text(encoding="utf-8"))
    snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    candidate = build_candidate(underlying=args.symbol, trading_day=date.fromisoformat(args.trading_day), underlying_price=args.price, contracts_payload=contracts, snapshot_payload=snapshot, model_probability=probability, risk_state=PortfolioRiskState(nav=100_000), risk_config=RiskConfig(), event_decision=EventDecision("noise_or_opinion", True, "no headline supplied"), fill_assumptions=FillAssumptions())
    result = PaperRunCoordinator(AlpacaPaperClient.from_env(), NebiusReviewer()).execute(candidate)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
