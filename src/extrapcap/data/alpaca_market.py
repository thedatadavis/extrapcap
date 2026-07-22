from __future__ import annotations

import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class AlpacaMarketData:
    """Read-only Alpaca market-data adapter using the paper account credentials."""

    def __init__(self, api_key: str | None = None, secret_key: str | None = None, base_url: str = "https://data.alpaca.markets", trading_base_url: str = "https://paper-api.alpaca.markets"):
        self.api_key = api_key or os.getenv("ALPACA_API_KEY")
        self.secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY")
        self.base_url = base_url.rstrip("/")
        self.trading_base_url = trading_base_url.rstrip("/")

    def _get(self, path: str, params: dict, base_url: str | None = None) -> dict:
        if not self.api_key or not self.secret_key:
            raise RuntimeError("missing Alpaca credentials for market data")
        query = urlencode({k: v for k, v in params.items() if v is not None})
        request = Request(f"{(base_url or self.base_url).rstrip('/')}{path}?{query}", headers={"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.secret_key})
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read())

    def stock_bars(self, symbols: list[str], start: str, end: str, timeframe: str = "1Day") -> dict:
        return self._get("/v2/stocks/bars", {"symbols": ",".join(symbols), "start": start, "end": end, "timeframe": timeframe, "adjustment": "all", "feed": "iex", "limit": 10000})

    def option_contracts(self, underlying_symbols: list[str], expiration_date_gte: str, expiration_date_lte: str | None = None) -> dict:
        return self._get("/v2/options/contracts", {"underlying_symbols": ",".join(underlying_symbols), "expiration_date_gte": expiration_date_gte, "expiration_date_lte": expiration_date_lte, "status": "active", "limit": 1000}, self.trading_base_url)
