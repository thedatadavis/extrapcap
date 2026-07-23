from __future__ import annotations

import json
import os
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class AlpacaMarketData:
    """Read-only Alpaca market-data adapter using the paper account credentials."""

    DEFAULT_STOCK_BAR_BATCH_SIZE = 100
    STOCK_SYMBOL_ALIASES = {
        # The Greenlist source uses Yahoo-style dash share classes; Alpaca's
        # market-data API uses dot notation for these symbols.
        "BF-B": "BF.B",
        "BRK-B": "BRK.B",
        "PBR-A": "PBR.A",
    }

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

    def stock_bars(
        self,
        symbols: list[str],
        start: str,
        end: str,
        timeframe: str = "1Day",
        *,
        symbol_batch_size: int = DEFAULT_STOCK_BAR_BATCH_SIZE,
    ) -> dict:
        """Fetch all stock-bar pages for the requested symbols.

        Alpaca paginates stock bars by row count, so a full Greenlist request
        must be split into bounded symbol batches and each batch must follow
        ``next_page_token`` until exhausted.
        """
        requested = list(dict.fromkeys(symbol.upper() for symbol in symbols if symbol.strip()))
        if not requested:
            raise ValueError("stock bar request requires at least one symbol")
        if symbol_batch_size < 1:
            raise ValueError("symbol_batch_size must be positive")

        bars: dict[str, list] = {}
        errors: dict[str, dict] = {}

        def fetch_batch(batch: list[str]) -> None:
            batch_bars: dict[str, list] = {}
            provider_batch = [self.STOCK_SYMBOL_ALIASES.get(symbol, symbol) for symbol in batch]
            page_token = None
            try:
                while True:
                    response = self._get(
                        "/v2/stocks/bars",
                        {
                            "symbols": ",".join(provider_batch),
                            "start": start,
                            "end": end,
                            "timeframe": timeframe,
                            "adjustment": "all",
                            "feed": "iex",
                            "limit": 10000,
                            "page_token": page_token,
                        },
                    )
                    for symbol, rows in (response.get("bars") or {}).items():
                        source_symbol = next(
                            (candidate for candidate, provider_symbol in zip(batch, provider_batch) if provider_symbol == symbol),
                            symbol,
                        )
                        batch_bars.setdefault(source_symbol, []).extend(rows)
                    page_token = response.get("next_page_token")
                    if not page_token:
                        break
            except HTTPError as exc:
                if exc.code != 400:
                    raise
                if len(batch) > 1:
                    midpoint = len(batch) // 2
                    fetch_batch(batch[:midpoint])
                    fetch_batch(batch[midpoint:])
                    return
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", errors="replace").strip()
                except Exception:
                    detail = str(exc)
                errors[batch[0]] = {"status": exc.code, "reason": exc.reason, "detail": detail}
                return
            for symbol, rows in batch_bars.items():
                bars.setdefault(symbol, []).extend(rows)

        for offset in range(0, len(requested), symbol_batch_size):
            fetch_batch(requested[offset:offset + symbol_batch_size])
        payload = {"bars": bars}
        if errors:
            payload["errors"] = errors
        return payload

    def option_contracts(self, underlying_symbols: list[str], expiration_date_gte: str, expiration_date_lte: str | None = None) -> dict:
        return self._get("/v2/options/contracts", {"underlying_symbols": ",".join(underlying_symbols), "expiration_date_gte": expiration_date_gte, "expiration_date_lte": expiration_date_lte, "status": "active", "limit": 1000}, self.trading_base_url)
