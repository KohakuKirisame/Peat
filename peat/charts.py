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


SUFFIXES = {
    "US": "",
    "UK": ".L",
    "GB": ".L",
    "DE": ".DE",
    "NL": ".AS",
    "FR": ".PA",
    "IT": ".MI",
    "ES": ".MC",
    "CH": ".SW",
    "BE": ".BR",
    "AT": ".VI",
    "PT": ".LS",
    "IE": ".IR",
    "SE": ".ST",
    "DK": ".CO",
    "FI": ".HE",
    "NO": ".OL",
    "PL": ".WA",
    "HK": ".HK",
    "JP": ".T",
    "CA": ".TO",
    "AU": ".AX",
    "SG": ".SI",
}
EXCHANGE_SUFFIXES = {
    "nasdaq": "",
    "new york": "",
    "nyse": "",
    "london": ".L",
    "lse": ".L",
    "xetra": ".DE",
    "frankfurt": ".F",
    "paris": ".PA",
    "amsterdam": ".AS",
    "milan": ".MI",
    "borsa italiana": ".MI",
    "madrid": ".MC",
    "brussels": ".BR",
    "vienna": ".VI",
    "lisbon": ".LS",
    "swiss": ".SW",
    "six": ".SW",
    "zurich": ".SW",
    "stockholm": ".ST",
    "copenhagen": ".CO",
    "helsinki": ".HE",
    "oslo": ".OL",
    "hong kong": ".HK",
    "tokyo": ".T",
    "toronto": ".TO",
    "australian": ".AX",
}


def valid_symbol(symbol: str):
    return bool(re.fullmatch(r"[A-Za-z0-9^][A-Za-z0-9.^=\-]{0,29}", symbol))


def listed_symbol(name: str, suffix: str):
    if suffix in {".ST", ".CO", ".HE"}:
        name = re.sub(r"^([A-Z0-9]+)([a-z])$", r"\1-\2", name)
    base = name.strip().upper().rstrip(".").replace(" ", "-")
    if not suffix or suffix in {".ST", ".CO", ".HE", ".TO"}:
        base = base.replace(".", "-")
    if suffix == ".HK" and base.isdigit():
        base = str(int(base)).zfill(4)
    result = base + suffix
    return result if valid_symbol(result) else None


def suggested_symbol(ticker: str, currency: str | None = None, metadata: dict | None = None):
    if metadata:
        exchange = (metadata.get("exchange") or "").casefold()
        for name in sorted(EXCHANGE_SUFFIXES, key=len, reverse=True):
            suffix = EXCHANGE_SUFFIXES[name]
            if name in exchange and metadata.get("shortName"):
                return listed_symbol(metadata["shortName"], suffix)
    # Trading 212 has both country-tagged IDs and older venue-letter IDs (AIRp_EQ).
    tagged = re.fullmatch(r"(.+)_([A-Z]{2})_(?:EQ|ETF)", ticker)
    if tagged and tagged[2] in SUFFIXES:
        return listed_symbol(tagged[1], SUFFIXES[tagged[2]])
    legacy = re.fullmatch(r"([A-Z0-9.]+)([padim])_EQ", ticker)
    if legacy:
        return listed_symbol(
            legacy[1], {"p": ".PA", "a": ".AS", "d": ".DE", "i": ".MI", "m": ".MC"}[legacy[2]]
        )
    if ticker.endswith("_EQ") and currency in {"GBP", "GBX", "GBp"}:
        return listed_symbol(ticker[:-3], ".L")
    if "_" not in ticker and valid_symbol(ticker):
        return ticker.upper()
    return None


class Charts:
    def __init__(self, db: Database, client: httpx.AsyncClient):
        self.db, self.client = db, client
        self.lock = asyncio.Lock()

    async def fetch(self, symbol: str, interval: str, period: str):
        if not valid_symbol(symbol) or period not in INTERVALS.get(interval, set()):
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
