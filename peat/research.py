"""Fresh research inputs and explicit news/price timing for both LLM paths."""

import asyncio
from datetime import datetime, timezone

from .brokers import ProviderError
from .charts import suggested_symbol
from .db import now
from .portfolio_context import investment_context
from .temporal import news_timing, price_alignment, timestamp


class ResearchContext:
    def __init__(self, db, brokers, news, markets, charts):
        self.db, self.brokers, self.news, self.markets, self.charts = db, brokers, news, markets, charts

    async def refresh(self, uid, progress=None):
        if progress:
            progress("refreshing")
        results = {}

        async def source(name, operation):
            try:
                async with asyncio.timeout(55):
                    await operation()
                results[name] = {"status": "requested", "checked_at": now()}
            except (ProviderError, TimeoutError) as exc:
                results[name] = {
                    "status": "retained_or_unavailable",
                    "error": exc.code if isinstance(exc, ProviderError) else "source_timeout",
                    "checked_at": now(),
                }

        await source("portfolio", lambda: self.brokers.sync(uid, refresh_pies=False))
        await asyncio.gather(
            source("markets", lambda: self.markets.refresh(force=True)),
            source("news", lambda: self.news.sync(uid)),
        )
        return results

    async def enrich(self, uid, settings, evidence, refresh_results, progress=None, focus=None):
        if progress:
            progress("price_context")
        # Body acquisition can take time. Bring account quantities and macro quotes forward again.
        cached = self.db.cached(uid, "portfolio")
        fetched = timestamp((cached or {}).get("updated_at"))
        if fetched and (datetime.now(timezone.utc) - fetched).total_seconds() > 30:
            try:
                async with asyncio.timeout(25):
                    await self.brokers.sync(uid, refresh_pies=False)
            except (ProviderError, TimeoutError):
                pass
        evidence["portfolio"] = investment_context(self.db.cached(uid, "portfolio"))
        try:
            async with asyncio.timeout(25):
                evidence["markets"] = await self.markets.refresh(force=True)
        except (ProviderError, TimeoutError):
            evidence["markets"] = self.db.cached(0, "markets")
        holdings = (evidence.get("portfolio") or {}).get("data", {}).get("positions", [])
        targets = {
            p["ticker"]: {
                "ticker": p["ticker"],
                "name": p.get("name") or p["ticker"],
                "currency": p.get("currency"),
                "weight": p.get("weight_pct") or 0,
            }
            for p in holdings
        }
        for watch in evidence.get("watchlist", []):
            targets.setdefault(
                watch["symbol"], {"ticker": watch["symbol"], "name": watch["name"], "weight": 0}
            )
        focus = (focus or "").casefold()
        ordered = sorted(
            targets.values(),
            key=lambda p: (
                bool(
                    focus and (p["ticker"].split("_")[0].casefold() in focus or p["name"].casefold() in focus)
                ),
                p["weight"],
            ),
            reverse=True,
        )
        selected = ordered[:60]
        mappings = {
            row["ticker"]: row["symbol"]
            for row in self.db.all("SELECT ticker,symbol FROM symbol_mappings WHERE user_id=?", (uid,))
        }
        collected, slots = {}, asyncio.Semaphore(4)
        horizon = settings.get("holding_horizon") or "medium_long"
        trend_interval, trend_period = ("5m", "5d") if horizon == "ultra_short" else ("1h", "1mo")

        async def instrument(target):
            async with slots:
                ticker = target["ticker"]
                symbol = mappings.get(ticker) or suggested_symbol(ticker, target.get("currency"))
                if not symbol:
                    metadata = await self.brokers.chart_instrument(uid, ticker)
                    symbol = suggested_symbol(ticker, metadata=metadata)
                if not symbol:
                    collected[ticker] = {**target, "status": "unavailable", "error": "chart_symbol_required"}
                    return
                queries = [("minute", "1m", "1d"), ("daily", "1d", "1y")]
                if horizon != "medium_long":
                    queries.append(("trend", trend_interval, trend_period))
                results = await asyncio.gather(
                    *(
                        self.charts.fetch(symbol, interval, period, extended=True, force=True)
                        for _, interval, period in queries
                    ),
                    return_exceptions=True,
                )
                record = {**target, "symbol": symbol, "series": {}}
                for (kind, _, _), value in zip(queries, results, strict=True):
                    if isinstance(value, dict):
                        record["series"][kind] = value["data"]
                best = record["series"].get("minute") or record["series"].get("daily")
                record.update(
                    status=best["status"] if best else "unavailable",
                    quote=best.get("latest_quote") if best else None,
                    fetched_at=best.get("fetched_at") if best else None,
                    currency=best.get("currency") if best else target.get("currency"),
                    provider_name=best.get("name") if best else None,
                    provider_symbol=best.get("symbol") if best else None,
                )
                collected[ticker] = record

        try:
            async with asyncio.timeout(75):
                await asyncio.gather(*(instrument(target) for target in selected))
        except TimeoutError:
            pass
        at = datetime.now(timezone.utc)
        for article in evidence["news"]:
            article.update(news_timing(article, horizon, at))
            article["price_context"] = []
            related = []
            for entity in article.get("related_entities", []):
                record = collected.get(entity.get("symbol"))
                if record:
                    related.append(record)
                if entity.get("kind") == "industry":
                    for watch in evidence.get("watchlist", []):
                        if (watch.get("sector") or "").strip().casefold() == entity[
                            "name"
                        ].strip().casefold():
                            match = collected.get(watch["symbol"]) or next(
                                (
                                    item
                                    for item in collected.values()
                                    if item.get("symbol") == watch["symbol"]
                                ),
                                None,
                            )
                            if match:
                                related.append(match)
            unique = {record.get("symbol", record["ticker"]): record for record in related}
            article["price_context_omitted_symbols"] = list(unique)[6:]
            for record in list(unique.values())[:6]:
                published = timestamp(article["effective_published_at"])
                choices = [record.get("series", {}).get(key) for key in ("minute", "trend")]
                intraday = next(
                    (
                        value
                        for value in choices
                        if value
                        and published
                        and value["candles"][0]["time"]
                        <= published.timestamp()
                        <= (value["candles"][-1].get("end_time") or value["candles"][-1]["time"])
                    ),
                    None,
                )
                article["price_context"].append(
                    {
                        "symbol": record.get("symbol"),
                        **price_alignment(article, intraday, record.get("series", {}).get("daily")),
                    }
                )
        histories = []
        for target in selected:
            record = collected.get(
                target["ticker"], {**target, "status": "unavailable", "error": "source_timeout"}
            )
            series = record.pop("series", {})
            cap = max(8, min(60, 1600 // max(1, len(selected)) // max(1, len(series))))
            record["histories"] = []
            for kind, data in series.items():
                bars = data["candles"][-cap:]
                record["histories"].append(
                    {
                        "kind": kind,
                        "interval": data["interval"],
                        "timezone": data["timezone"],
                        "source": data["source"],
                        "corporate_actions": data.get("corporate_actions", {}),
                        "status": data["status"],
                        "coverage_start": bars[0]["time"],
                        "coverage_end": bars[-1]["time"],
                        "columns": ["time", "open", "high", "low", "close", "volume", "session", "complete"],
                        "bars": [
                            [
                                bar[key]
                                for key in (
                                    "time",
                                    "open",
                                    "high",
                                    "low",
                                    "close",
                                    "volume",
                                    "session",
                                    "complete",
                                )
                            ]
                            for bar in bars
                        ],
                    }
                )
            quote_time = timestamp((record.get("quote") or {}).get("as_of"))
            record["quote_age_seconds"] = round((at - quote_time).total_seconds()) if quote_time else None
            histories.append(record)
        evidence["price_histories"] = histories
        evidence["price_coverage"] = {
            "total_assets": len(ordered),
            "prepared_assets": len(histories),
            "available_assets": sum(bool(p.get("quote")) for p in histories),
            "omitted_symbols": [p["ticker"] for p in ordered[60:]],
        }
        evidence["freshness"] = {
            "mode": "live_refresh",
            "collected_at": at.isoformat(),
            "refresh": refresh_results,
            "quote_times": {
                p.get("symbol", p["ticker"]): p["quote"]["as_of"] for p in histories if p.get("quote")
            },
            "note": "retrieval_time_is_not_quote_time; provider_quotes_may_be_delayed",
        }
        evidence["generated_at"] = at.isoformat()
        return evidence
