import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from .brokers import ProviderError, number
from .db import Database

INTERVALS = {
    "1m": {"1d", "5d"},
    "5m": {"1d", "5d", "1mo"},
    "15m": {"5d", "1mo"},
    "1h": {"1mo", "3mo", "6mo", "1y"},
    "1d": {"1mo", "3mo", "6mo", "1y", "5y", "max"},
    "1wk": {"1y", "5y", "max"},
    "1mo": {"5y", "max"},
}


def suggested_symbol(ticker: str):
    parts = ticker.split("_")
    suffix = {"US": "", "UK": ".L", "DE": ".DE", "NL": ".AS", "FR": ".PA", "IT": ".MI", "ES": ".MC"}
    if len(parts) >= 3 and parts[-2] in suffix:
        return parts[0].replace(".", "-") + suffix[parts[-2]]
    return None


class Charts:
    def __init__(self, db: Database, client: httpx.AsyncClient):
        self.db, self.client = db, client
        self.lock = asyncio.Lock()

    async def fetch(self, symbol: str, interval: str, period: str):
        if not re.fullmatch(r"[A-Za-z0-9^][A-Za-z0-9.^=\-]{0,29}", symbol) or period not in INTERVALS.get(
            interval, set()
        ):
            raise ProviderError("invalid_chart_query")
        async with self.lock:
            key = f"chart:{symbol}:{interval}:{period}"
            cached = self.db.cached(0, key)
            if (
                cached
                and (
                    datetime.now(timezone.utc) - datetime.fromisoformat(cached["updated_at"])
                ).total_seconds()
                < 60
            ):
                return cached
            try:
                response = await self.client.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}",
                    params={"interval": interval, "range": period, "events": "div,splits"},
                    headers={"User-Agent": "Mozilla/5.0 Peat/0.1"},
                )
                response.raise_for_status()
                data = response.json()["chart"]["result"][0]
                quote_data = data["indicators"]["quote"][0]
                candles = []
                for i, timestamp in enumerate(data.get("timestamp", [])):
                    candle = {
                        "time": timestamp,
                        **{
                            key: number(quote_data[key][i])
                            for key in ("open", "high", "low", "close", "volume")
                        },
                    }
                    if all(candle[key] is not None for key in ("open", "high", "low", "close")):
                        candles.append(candle)
                if not candles:
                    raise ProviderError("chart_no_data")
                meta = data["meta"]
                result = {
                    "symbol": meta.get("symbol", symbol),
                    "name": meta.get("longName", meta.get("shortName", symbol)),
                    "currency": meta.get("currency"),
                    "timezone": meta.get("exchangeTimezoneName"),
                    "exchange": meta.get("exchangeName"),
                    "interval": interval,
                    "period": period,
                    "candles": candles,
                    "source": "Yahoo Finance",
                    "status": "delayed",
                    "adjustment": "provider_ohlc",
                    "as_of": datetime.fromtimestamp(candles[-1]["time"], timezone.utc).isoformat(),
                }
                self.db.put_cache(0, key, result)
                return self.db.cached(0, key)
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
                if cached:
                    return {**cached, "data": cached["data"] | {"status": "stale"}}
                raise ProviderError("chart_unavailable") from None
