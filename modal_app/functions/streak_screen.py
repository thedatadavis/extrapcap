import time
import json
from datetime import datetime, timezone
import modal
from modal_app.base import app, image, secrets
from modal_app.cf_client import CloudflareAPIClient


@app.function(
    image=image,
    secrets=secrets,
    timeout=300,
)
def streak_screen():
    """Streak Screening Cron: Filter greenlist symbols by relative streak return and robust Z-score (5:45 AM UTC)."""
    cf = CloudflareAPIClient()
    start_time = time.time()
    run_id = cf.register_run("streak_screen")

    try:
        import pandas as pd
        from urllib.request import urlopen
        from extrapcap.universe.greenlist import SOURCE_URL, GreenlistFilter, filter_greenlist, _read_csv
        from extrapcap.universe.streak_screen import filter_tradable_basket
        from extrapcap.models.bayesian_reversion import BayesianReversionModel

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Fetch greenlist registry from source URL
        with urlopen(SOURCE_URL, timeout=30) as response:
            raw_text = response.read().decode("utf-8")
        raw_rows = _read_csv(raw_text)
        accepted_greenlist, _ = filter_greenlist(raw_rows, GreenlistFilter())

        # Generate the basket strictly from completed bars persisted by the
        # data_refresh workflow. Empty/stale storage is an operational failure,
        # not a reason to fabricate signals.
        bars = cf.get_bars(limit=100000)
        if not bars:
            raise RuntimeError("Cloudflare D1 contains no market bars; run data_refresh first")
        bars_df = pd.DataFrame(bars)
        basket_df = filter_tradable_basket(
            greenlist=accepted_greenlist,
            bars_df=bars_df,
        )
        bars_df["symbol"] = bars_df["symbol"].astype(str).str.upper()
        bars_df["date"] = pd.to_datetime(bars_df["date"], utc=True)
        benchmark = bars_df.loc[bars_df["symbol"] == "SPY"].set_index("date")["close"]
        model = BayesianReversionModel.fit_from_bars(bars_df[["symbol", "date", "close"]], benchmark)
        probabilities = []
        evidence = []
        for row in basket_df.to_dict(orient="records"):
            item = model.predict_evidence(symbol=row["symbol"], streak_length=int(row["streak_length"]), streak_direction=row["streak_direction"], day_of_week=pd.Timestamp(row["date"]).dayofweek)
            row["reversion_probability"] = item.probability
            row["bayesian_cell_observations"] = item.cell_observations
            row["bayesian_ticker_observations"] = item.ticker_observations
            row["features"] = json.dumps(row, default=str)
            evidence.append(row)
        basket_df = pd.DataFrame(evidence)
        rows = basket_df.to_dict(orient="records")

        # Store greenlist universe metadata in D1
        cf.store_universe(accepted_greenlist)

        # Store in D1 with run_id provenance
        cf.store_basket(as_of=today_str, rows=rows, run_id=run_id)
        cf.complete_run(run_id, summary={"universe_count": len(accepted_greenlist), "tradable_candidates": len(rows)}, start_time=start_time)
        return {"status": "success", "universe_count": len(accepted_greenlist), "candidates_count": len(rows), "run_id": run_id}

    except Exception as e:
        cf.fail_run(run_id, error=str(e), start_time=start_time)
        raise
