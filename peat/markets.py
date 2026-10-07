import asyncio
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import quote

import exchange_calendars as xcals
import httpx
import pandas as pd
from defusedxml import ElementTree

from .brokers import number
from .db import Database, now

EXCHANGES = [
    ("XNYS", "New York", "NYSE / NASDAQ", "America/New_York"),
    ("XLON", "London", "LSE", "Europe/London"),
    ("XAMS", "Amsterdam", "Euronext", "Europe/Amsterdam"),
    ("XETR", "Frankfurt", "Xetra", "Europe/Berlin"),
    ("XHKG", "Hong Kong", "HKEX", "Asia/Hong_Kong"),
    ("XTKS", "Tokyo", "TSE", "Asia/Tokyo"),
    ("XSHG", "Shanghai", "SSE", "Asia/Shanghai"),
]
COMMODITIES = [
    ("CL=F", "WTI crude", "USD/barrel"),
    ("BZ=F", "Brent crude", "USD/barrel"),
    ("NG=F", "Natural gas", "USD/MMBtu"),
    ("GC=F", "Gold", "USD/oz"),
    ("SI=F", "Silver", "USD/oz"),
    ("PL=F", "Platinum", "USD/oz"),
]


@lru_cache(maxsize=32)
def exchange_calendar(code: str, year: int):
    try:
        return xcals.get_calendar(code, start=f"{year - 1}-01-01", end=f"{year + 2}-12-31")
    except ValueError:
        # Some exchanges only publish holidays through the current year.
        return xcals.get_calendar(code, start=f"{year - 1}-01-01", end=f"{year}-12-31")


def exchange_status(at: datetime | None = None) -> list[dict]:
    current = pd.Timestamp(at or datetime.now(timezone.utc)).floor("min")
    result = []
    for code, city, name, zone in EXCHANGES:
        item = {"code": code, "city": city, "name": name, "timezone": zone, "as_of": current.isoformat()}
        try:
            cal = exchange_calendar(code, current.year)
            opened = cal.is_open_on_minute(current, ignore_breaks=False)
            item.update(
                {
                    "status": "open" if opened else "closed",
                    "next_open": cal.next_open(current).isoformat(),
                    "next_close": cal.next_close(current).isoformat(),
                    "local_time": current.tz_convert(zone).strftime("%H:%M"),
                    "source": "exchange_calendars",
                }
            )
        except (ValueError, KeyError, IndexError, NotImplementedError):
            item.update({"status": "unknown", "error": "calendar_unavailable"})
        result.append(item)
    return result


class Markets:
    def __init__(self, db: Database, client: httpx.AsyncClient):
        self.db, self.client = db, client
        self.lock = asyncio.Lock()

    async def commodity(self, symbol, name, unit):
        item = {
            "symbol": symbol,
            "name": name,
            "unit": unit,
            "source": "Yahoo Finance",
            "kind": "futures",
            "url": f"https://finance.yahoo.com/quote/{quote(symbol)}/",
            "status": "delayed",
        }
        try:
            response = await self.client.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}",
                params={"interval": "1d", "range": "1mo"},
                headers={"User-Agent": "Mozilla/5.0 Peat/0.1"},
            )
            response.raise_for_status()
            chart = response.json()["chart"]["result"][0]
            meta = chart["meta"]
            value, previous = number(meta.get("regularMarketPrice")), number(meta.get("previousClose"))
            closes = chart["indicators"]["quote"][0]["close"]
            valid = [number(x) for x in closes if number(x) is not None]
            # chartPreviousClose is the start of the requested range, not the prior day's close.
            if previous is None and len(valid) >= 2:
                previous = valid[-2]
            item.update(
                {
                    "value": value,
                    "change_pct": (value / previous - 1) * 100 if value is not None and previous else None,
                    "as_of": datetime.fromtimestamp(meta["regularMarketTime"], timezone.utc).isoformat(),
                    "timezone": meta.get("exchangeTimezoneName") or "UTC",
                    "series": valid[-22:],
                    "observations": [
                        {
                            "date": datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
                            "value": number(close),
                        }
                        for stamp, close in zip(chart.get("timestamp", []), closes, strict=False)
                        if number(close) is not None
                    ][-22:],
                }
            )
            if value is None:
                item["status"] = "unavailable"
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            item.update({"value": None, "status": "unavailable", "error": "quote_unavailable"})
        return item

    async def treasury(self):
        url = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
        try:
            response = await self.client.get(
                url,
                params={
                    "data": "daily_treasury_yield_curve",
                    "field_tdr_date_value": datetime.now(timezone.utc).year,
                },
            )
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
            rows = []
            for properties in root.iter():
                if properties.tag.endswith("}properties"):
                    row = {child.tag.split("}")[-1]: child.text for child in properties}
                    if row.get("NEW_DATE"):
                        rows.append(row)
            rows.sort(key=lambda row: row["NEW_DATE"])
            latest = rows[-1]
            return [
                {
                    "symbol": f"UST{term}",
                    "name": f"US {term}Y Treasury",
                    "value": number(latest.get(f"BC_{term}YEAR")),
                    "unit": "%",
                    "kind": "yield",
                    "status": "daily",
                    "source": "US Treasury",
                    "url": "https://home.treasury.gov/treasury-daily-interest-rate-xml-feed",
                    "as_of": latest["NEW_DATE"],
                    "series": [
                        number(row.get(f"BC_{term}YEAR"))
                        for row in rows[-22:]
                        if number(row.get(f"BC_{term}YEAR")) is not None
                    ],
                    "observations": [
                        {"date": row["NEW_DATE"], "value": number(row.get(f"BC_{term}YEAR"))}
                        for row in rows[-22:]
                        if number(row.get(f"BC_{term}YEAR")) is not None
                    ],
                }
                for term in (2, 10, 30)
            ]
        except (httpx.HTTPError, ValueError, IndexError, ElementTree.ParseError):
            return [
                {
                    "symbol": f"UST{term}",
                    "name": f"US {term}Y Treasury",
                    "value": None,
                    "unit": "%",
                    "kind": "yield",
                    "source": "US Treasury",
                    "status": "unavailable",
                }
                for term in (2, 10, 30)
            ]

    async def refresh(self, *, force=False):
        async with self.lock:
            cached = self.db.cached(0, "markets")
            if cached and (
                datetime.now(timezone.utc) - datetime.fromisoformat(cached["updated_at"])
            ).total_seconds() < (15 if force else 300):
                return cached
            results = await asyncio.gather(self.treasury(), *(self.commodity(*item) for item in COMMODITIES))
            quotes = results[0] + list(results[1:])
            # Preserve last successful values while explicitly marking them stale.
            previous = {q["symbol"]: q for q in (cached or {}).get("data", {}).get("quotes", [])}
            for i, item in enumerate(quotes):
                if (
                    item["status"] == "unavailable"
                    and previous.get(item["symbol"], {}).get("value") is not None
                ):
                    quotes[i] = previous[item["symbol"]] | {"status": "stale", "error": "quote_unavailable"}
            self.db.put_cache(0, "markets", {"quotes": quotes, "as_of": now()})
            return self.db.cached(0, "markets")
