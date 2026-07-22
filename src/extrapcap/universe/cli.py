import argparse
from .greenlist import GreenlistFilter, refresh_greenlist


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the pinned StockStreaks Greenlist snapshot")
    parser.add_argument("--output-dir", default="data/universe")
    parser.add_argument("--min-avg-volume", type=int, default=1_000_000)
    parser.add_argument("--min-market-cap", type=float)
    parser.add_argument("--require-weekly-options", action="store_true")
    parser.add_argument("--require-penny-pricing", action="store_true")
    parser.add_argument("--min-options-volume", type=int)
    args = parser.parse_args()
    path = refresh_greenlist(
        args.output_dir,
        GreenlistFilter(
            min_avg_volume=args.min_avg_volume,
            min_market_cap=args.min_market_cap,
            require_weekly_options=args.require_weekly_options,
            require_penny_pricing=args.require_penny_pricing,
            min_options_volume=args.min_options_volume,
        ),
    )
    print(path)


if __name__ == "__main__":
    main()
