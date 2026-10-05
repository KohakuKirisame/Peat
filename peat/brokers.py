"""Read-only broker adapters. No order submission endpoint exists in Peat."""

import asyncio
import csv
import io
import json
import math
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

import httpx

from .db import Database, now
from .security import Vault, digest


class ProviderError(Exception):
    def __init__(self, code: str, retry_after: int | None = None):
        self.code, self.retry_after = code, retry_after
        super().__init__(code)


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


class Broker(ABC):
    @abstractmethod
    async def snapshot(self) -> dict: ...


class Trading212(Broker):
    # Deliberately contains only GET operations.
    PATHS = {
        "/equity/account/summary",
        "/equity/positions",
        "/equity/metadata/exchanges",
        "/equity/metadata/instruments",
        "/equity/history/orders",
        "/equity/history/dividends",
        "/equity/history/transactions",
    }

    def __init__(self, credentials: dict, client: httpx.AsyncClient):
        self.client = client
        self.environment = credentials.get("environment", "live")
        self.base = f"https://{'demo' if self.environment == 'demo' else 'live'}.trading212.com/api/v0"
        self.auth = httpx.BasicAuth(credentials["api_key"], credentials["api_secret"])

    async def get(self, path: str):
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.fragment or "\\" in path:
            raise ProviderError("invalid_broker_pagination")
        clean = parsed.path.removeprefix("/api/v0")
        if clean not in self.PATHS:
            raise ProviderError("invalid_broker_endpoint")
        try:
            response = await self.client.get(
                self.base + clean + ("?" + parsed.query if parsed.query else ""),
                auth=self.auth,
                follow_redirects=False,
            )
        except httpx.RequestError:
            raise ProviderError("broker_unreachable") from None
        if response.status_code == 429:
            try:
                delay = min(3600, max(10, int(response.headers.get("retry-after", "60"))))
            except ValueError:
                delay = 60
            raise ProviderError("broker_rate_limited", delay)
        if response.status_code in (401, 403):
            raise ProviderError("broker_credentials_rejected")
        if response.status_code != 200:
            raise ProviderError("broker_response_error")
        try:
            return response.json()
        except ValueError:
            raise ProviderError("broker_invalid_response") from None

    async def snapshot(self):
        summary, positions = await asyncio.gather(
            self.get("/equity/account/summary"), self.get("/equity/positions")
        )
        if not isinstance(summary, dict) or not isinstance(positions, list) or "investments" not in summary:
            raise ProviderError("broker_schema_changed")
        currency = summary.get("currency")
        investments = summary["investments"]
        normalized = []
        for position in positions:
            instrument = position.get("instrument", {})
            wallet = position.get("walletImpact", {})
            normalized.append(
                {
                    "ticker": instrument.get("ticker", ""),
                    "name": instrument.get("name", ""),
                    "isin": instrument.get("isin"),
                    "currency": instrument.get("currency"),
                    "quantity": number(position.get("quantity")),
                    "price": number(position.get("currentPrice")),
                    "average_price": number(position.get("averagePricePaid")),
                    "value": number(wallet.get("currentValue")),
                    "cost": number(wallet.get("totalCost")),
                    "pnl": number(wallet.get("unrealizedProfitLoss")),
                    "account_currency": wallet.get("currency", currency),
                }
            )
        return {
            "provider": "trading212",
            "environment": self.environment,
            "currency": currency,
            "total_value": number(summary.get("totalValue")),
            "invested": number(investments.get("totalCost")),
            "market_value": number(investments.get("currentValue")),
            "realized": number(investments.get("realizedProfitLoss")),
            "unrealized": number(investments.get("unrealizedProfitLoss")),
            "cash": number(summary.get("cash", {}).get("availableToTrade")),
            "positions": normalized,
            "source": "Trading 212 account summary / positions",
            "as_of": now(),
        }


class BrokerService:
    def __init__(self, db: Database, vault: Vault, client: httpx.AsyncClient):
        self.db, self.vault, self.client = db, vault, client
        self.locks: dict[int, asyncio.Lock] = {}
        self.next_attempt: dict[tuple, float] = {}

    def adapter(self, uid: int) -> Trading212:
        credentials = self.vault.get(uid, "trading212")
        if not credentials.get("api_key") or not credentials.get("api_secret"):
            raise ProviderError("broker_not_connected")
        return Trading212(credentials, self.client)

    async def sync(self, uid: int):
        async with self.locks.setdefault(uid, asyncio.Lock()):
            cached = self.db.cached(uid, "portfolio")
            if time.monotonic() < self.next_attempt.get((uid, "portfolio"), 0):
                if cached:
                    return cached
                raise ProviderError("broker_rate_limited")
            self.next_attempt[uid, "portfolio"] = time.monotonic() + 10
            try:
                data = await self.adapter(uid).snapshot()
            except ProviderError as exc:
                self.next_attempt[uid, "portfolio"] = time.monotonic() + (exc.retry_after or 60)
                self.db.put_cache(uid, "portfolio_status", {"error": exc.code})
                raise
            self.db.put_cache(uid, "portfolio", data)
            self.db.put_cache(uid, "portfolio_status", {"error": None})
            latest = self.db.one(
                "SELECT created_at FROM snapshots WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)
            )
            if data["total_value"] is not None and (
                not latest
                or datetime.fromisoformat(latest["created_at"])
                < datetime.now(timezone.utc) - timedelta(minutes=15)
            ):
                self.db.execute(
                    "INSERT INTO snapshots(user_id,total_value,total_cost,currency,created_at) VALUES(?,?,?,?,?)",
                    (uid, data["total_value"], data["invested"], data["currency"], now()),
                )
            return self.db.cached(uid, "portfolio")

    async def history(self, uid: int, kind: str, cursor: str | None = None):
        # One provider page per call. The browser continues through cursors at the published rate limit.
        async with self.locks.setdefault(uid, asyncio.Lock()):
            key = (uid, kind)
            if time.monotonic() < self.next_attempt.get(key, 0):
                raise ProviderError("broker_rate_limited", 11)
            self.next_attempt[key] = time.monotonic() + 11
            path = cursor or f"/equity/history/{kind}?limit=50"
            if urlsplit(path).path.removeprefix("/api/v0") != f"/equity/history/{kind}":
                raise ProviderError("invalid_broker_pagination")
            try:
                data = await self.adapter(uid).get(path)
            except ProviderError as exc:
                if exc.retry_after:
                    self.next_attempt[key] = time.monotonic() + exc.retry_after
                raise
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                raise ProviderError("broker_schema_changed")
            with self.db.connect() as conn:
                for item in data["items"]:
                    payload = json.dumps(item, sort_keys=True)
                    ext_id = str(
                        item.get("fill", {}).get("id")
                        or item.get("id")
                        or item.get("reference")
                        or digest(payload)
                    )
                    conn.execute(
                        "INSERT INTO history VALUES(?,?,?,?) ON CONFLICT(user_id,kind,external_id) "
                        "DO UPDATE SET payload=excluded.payload",
                        (uid, kind, ext_id, payload),
                    )
            self.db.put_cache(
                uid,
                f"history_{kind}",
                {"next": data.get("nextPagePath"), "complete": not data.get("nextPagePath")},
            )
            return {"imported": len(data["items"]), "next": data.get("nextPagePath")}


def import_statement(db: Database, uid: int, contents: bytes) -> dict:
    """Import English Trading 212 CSV. Sum stated cash flows/P&L separately by currency."""
    try:
        text = contents.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ProviderError("statement_utf8_required") from None
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or not {"Action", "Time", "Total", "Currency (Total)"}.issubset(
        reader.fieldnames
    ):
        raise ProviderError("statement_columns_missing")
    imported, skipped = 0, 0
    with db.connect() as conn:
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ProviderError("statement_invalid_row")
            if imported + skipped >= 50000:
                raise ProviderError("statement_too_many_rows")
            for key in ("Total", "Result"):
                if row.get(key):
                    try:
                        if not Decimal(row[key]).is_finite() or abs(Decimal(row[key])) > Decimal("1e15"):
                            raise InvalidOperation
                    except InvalidOperation:
                        raise ProviderError("statement_invalid_amount") from None
            raw = json.dumps(row, sort_keys=True, ensure_ascii=False)
            # IDs are broker-assigned; content hash also supports rows without a transaction ID.
            key = digest(raw)
            count = conn.execute(
                "INSERT OR IGNORE INTO statement_rows VALUES(?,?,?)", (uid, key, raw)
            ).rowcount
            imported += count
            skipped += 1 - count
    return {"imported": imported, "duplicates": skipped, "summary": statement_summary(db, uid)}


def statement_summary(db: Database, uid: int) -> dict:
    totals = {}
    rows = db.all("SELECT payload FROM statement_rows WHERE user_id=?", (uid,))
    dates = []
    for record in rows:
        row = json.loads(record["payload"])
        currency = row.get("Currency (Total)")
        if not currency:
            continue
        amounts = totals.setdefault(
            currency,
            {
                "deposits": Decimal(0),
                "withdrawals": Decimal(0),
                "dividends": Decimal(0),
                "realized": Decimal(0),
            },
        )
        action = row.get("Action", "").lower()
        total = Decimal(row.get("Total") or "0")
        if "deposit" in action:
            amounts["deposits"] += abs(total)
        elif "withdraw" in action:
            amounts["withdrawals"] += abs(total)
        elif "dividend" in action:
            amounts["dividends"] += total
        if row.get("Result"):
            result_currency = row.get("Currency (Result)") or currency
            result_totals = totals.setdefault(result_currency, {k: Decimal(0) for k in amounts})
            result_totals["realized"] += Decimal(row["Result"])
        dates.append(row.get("Time", ""))
    return {
        "rows": len(rows),
        "from": min(dates) if dates else None,
        "to": max(dates) if dates else None,
        "source": "Imported statement rows only",
        "currencies": {
            currency: {
                **{key: float(value) for key, value in amounts.items()},
                "net_deposits": float(amounts["deposits"] - amounts["withdrawals"]),
            }
            for currency, amounts in totals.items()
        },
    }
