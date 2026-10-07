import asyncio
import calendar
import re
from datetime import datetime, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


INTRADAY = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}
US_EXCHANGES = {"NMS", "NGM", "NCM", "NYQ", "ASE", "PCX", "BTS", "PNK", "BATS"}


def trading_periods(meta):
    periods = []

    def collect(value, session):
        if isinstance(value, list):
            for item in value:
                collect(item, session)
        elif (
            isinstance(value, dict)
            and isinstance(value.get("start"), (int, float))
            and isinstance(value.get("end"), (int, float))
        ):
            periods.append({"session": session, "start": value["start"], "end": value["end"]})

    source = meta.get("tradingPeriods", {})
    if isinstance(source, dict):
        for session in ("pre", "regular", "post"):
            collect(source.get(session, []), session)
    else:
        collect(source, "regular")
    for session, value in meta.get("currentTradingPeriod", {}).items():
        collect(value, session)
    return [
        dict(zip(("session", "start", "end"), key))
        for key in dict.fromkeys(tuple(p.values()) for p in periods)
    ]


def parse_chart(data, symbol, interval, period, extended, fetched_at):
    meta = data["meta"]
    schedule = trading_periods(meta)
    us = meta.get("exchangeName") in US_EXCHANGES and meta.get("instrumentType", "EQUITY") in {
        "EQUITY",
        "ETF",
    }
    try:
        zone = ZoneInfo(meta.get("exchangeTimezoneName") or "UTC")
    except ZoneInfoNotFoundError:
        zone = timezone.utc
    stamp = datetime.fromisoformat(fetched_at).timestamp()
    today = datetime.fromtimestamp(stamp, zone).date()
    quotes = data["indicators"]["quote"][0]
    candles = {}
    for index, timestamp in enumerate(data.get("timestamp", [])):
        values = {
            key: number((quotes.get(key) or [])[index]) if index < len(quotes.get(key) or []) else None
            for key in ("open", "high", "low", "close", "volume")
        }
        if not isinstance(timestamp, (int, float)) or any(
            values[key] is None for key in ("open", "high", "low", "close")
        ):
            continue
        session = next((p for p in schedule if p["start"] <= timestamp < p["end"]), None)
        if interval in INTRADAY and not extended and session and session["session"] in {"pre", "post"}:
            continue
        session_date = datetime.fromtimestamp(timestamp, zone).date()
        end = (
            min(timestamp + INTRADAY[interval], session["end"])
            if interval in INTRADAY and session
            else timestamp + INTRADAY[interval]
            if interval in INTRADAY
            else None
        )
        complete = end <= stamp if end else session_date < today or bool(session and session["end"] <= stamp)
        if interval == "1wk":
            complete = timestamp + 7 * 86400 <= stamp
        elif interval == "1mo":
            local_start = datetime.fromtimestamp(timestamp, zone)
            year, month = (
                (local_start.year + 1, 1)
                if local_start.month == 12
                else (local_start.year, local_start.month + 1)
            )
            period_end = local_start.replace(
                year=year, month=month, day=min(local_start.day, calendar.monthrange(year, month)[1])
            )
            complete = period_end.timestamp() <= stamp
        candles[timestamp] = {
            "time": timestamp,
            **values,
            "end_time": end,
            "session": session["session"]
            if session and interval in INTRADAY
            else "regular"
            if not extended or interval not in INTRADAY
            else "unknown",
            "session_date": session_date.isoformat(),
            "complete": complete,
        }
    candles = [candles[key] for key in sorted(candles)]
    if not candles:
        raise ProviderError("chart_no_data")
    latest = candles[-1]
    price, quote_time, precision = latest["close"], latest["time"], "bar_start"
    market_time, market_price = number(meta.get("regularMarketTime")), number(meta.get("regularMarketPrice"))
    if market_time and market_price is not None and latest["time"] <= market_time <= stamp + 60:
        price, quote_time, precision = market_price, market_time, "provider_quote"
    return {
        "symbol": meta.get("symbol", symbol),
        "name": meta.get("longName", meta.get("shortName", symbol)),
        "currency": meta.get("currency"),
        "timezone": meta.get("exchangeTimezoneName") or "UTC",
        "exchange": meta.get("exchangeName"),
        "interval": interval,
        "period": period,
        "candles": candles,
        "source": "Yahoo Finance",
        "status": "delayed",
        "adjustment": "provider_ohlc",
        "as_of": datetime.fromtimestamp(quote_time, timezone.utc).isoformat(),
        "fetched_at": fetched_at,
        "extended_requested": extended,
        "extended_supported": us and interval in INTRADAY,
        "has_extended": any(c["session"] in {"pre", "post"} for c in candles),
        "trading_periods": schedule,
        "corporate_actions": data.get("events", {}),
        "latest_quote": {
            "price": price,
            "as_of": datetime.fromtimestamp(quote_time, timezone.utc).isoformat(),
            "time_precision": precision,
            "session": latest["session"],
            "currency": meta.get("currency"),
        },
    }


class Charts:
    def __init__(self, db: Database | None, client: httpx.AsyncClient):
        self.db, self.client = db, client
        self.locks = {}

    async def fetch(
        self, symbol: str, interval: str, period: str, *, extended=False, force=False, start=None, end=None
    ):
        if not valid_symbol(symbol) or interval not in INTERVALS:
            raise ProviderError("invalid_chart_query")
        params = {
            "interval": interval,
            "events": "div,splits",
            "includePrePost": "true" if extended and interval in INTRADAY else "false",
        }
        window = None
        if start is not None or end is not None:
            try:
                begin, finish = (
                    datetime.fromisoformat(value.replace("Z", "+00:00")) for value in (start, end)
                )
                maximum = (
                    7
                    if interval == "1m"
                    else 60
                    if interval in {"5m", "15m"}
                    else 730
                    if interval == "1h"
                    else 3660
                )
                if (
                    not begin.tzinfo
                    or not finish.tzinfo
                    or not 0 < (finish - begin).total_seconds() <= maximum * 86400
                ):
                    raise ValueError
                params.update(period1=int(begin.timestamp()), period2=int(finish.timestamp()))
                window = {"start": begin.isoformat(), "end": finish.isoformat()}
            except (TypeError, ValueError, AttributeError):
                raise ProviderError("invalid_chart_window") from None
        elif period not in INTERVALS[interval]:
            raise ProviderError("invalid_chart_query")
        else:
            params["range"] = period
        key = f"chart:v2:{symbol}:{interval}:{period}:{int(extended)}:{params.get('period1', '')}:{params.get('period2', '')}"
        async with self.locks.setdefault(key, asyncio.Lock()):
            cached = self.db.cached(0, key) if self.db else None
            if (
                cached
                and not force
                and (
                    datetime.now(timezone.utc) - datetime.fromisoformat(cached["updated_at"])
                ).total_seconds()
                < 60
            ):
                return cached
            try:
                response = await self.client.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}",
                    params=params,
                    headers={"User-Agent": "Mozilla/5.0 Peat/0.6"},
                )
                response.raise_for_status()
                fetched_at = datetime.now(timezone.utc).isoformat()
                result = parse_chart(
                    response.json()["chart"]["result"][0],
                    symbol,
                    interval,
                    period,
                    extended and interval in INTRADAY,
                    fetched_at,
                )
                if window:
                    result["requested_window"] = window
                    bars = [
                        bar
                        for bar in result["candles"]
                        if params["period1"] <= bar["time"] < params["period2"]
                    ]
                    if not bars:
                        raise ProviderError("chart_no_data")
                    result["candles"] = bars
                    quoted = datetime.fromisoformat(result["latest_quote"]["as_of"]).timestamp()
                    if not params["period1"] <= quoted < params["period2"]:
                        last = bars[-1]
                        result["latest_quote"] = {
                            "price": last["close"],
                            "as_of": datetime.fromtimestamp(
                                last["end_time"] or last["time"], timezone.utc
                            ).isoformat()
                            if interval in INTRADAY
                            else last["session_date"],
                            "time_precision": "bar_close"
                            if last.get("end_time") and last.get("complete")
                            else "bar_start"
                            if interval in INTRADAY
                            else "session_date",
                            "session": last["session"],
                            "currency": result["currency"],
                        }
                        result["as_of"] = result["latest_quote"]["as_of"]
                if self.db:
                    self.db.put_cache(0, key, result)
                return {"data": result, "updated_at": fetched_at}
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, ProviderError) as exc:
                if cached:
                    return {
                        **cached,
                        "data": cached["data"] | {"status": "stale", "refresh_error": "chart_unavailable"},
                    }
                if isinstance(exc, ProviderError):
                    raise
                raise ProviderError("chart_unavailable") from None
