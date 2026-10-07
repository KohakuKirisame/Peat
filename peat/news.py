import asyncio
import calendar
import re
import time
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlencode, urlparse

import feedparser
import httpx
from fastapi import HTTPException

from .articles import ArticleReader
from .brokers import ProviderError
from .db import Database, now
from .security import digest


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.ignore = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignore += 1
        if tag in {"p", "br", "li", "div"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.ignore = max(0, self.ignore - 1)
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.ignore:
            self.parts.append(data)


def plain(value: str) -> str:
    parser = PlainText()
    parser.feed(value)
    return re.sub(r"\s+", " ", unescape(" ".join(parser.parts))).strip()


class NewsService:
    def __init__(self, db: Database, client: httpx.AsyncClient):
        self.db, self.client = db, client
        self.locks, self.cooldowns = {}, {}
        self.reader = ArticleReader()
        self.body_locks = {}
        self.body_slots = asyncio.Semaphore(3)
        self.body_retries = {}

    async def full_text(self, uid: int, article_id: int, refresh=False):
        article = self.db.one("SELECT * FROM news WHERE id=? AND user_id=?", (article_id, uid))
        if not article:
            raise HTTPException(404, "news_not_found")
        async with self.body_locks.setdefault(article_id, asyncio.Lock()):
            if not self.db.one(
                "SELECT id FROM news WHERE id=? AND user_id=? AND fingerprint=?",
                (article_id, uid, article["fingerprint"]),
            ):
                raise HTTPException(404, "news_not_found")
            cached = self.db.one("SELECT * FROM news_bodies WHERE news_id=?", (article_id,))
            if cached:
                if cached["status"] == "ready":
                    return cached
                age = (
                    datetime.now(timezone.utc) - datetime.fromisoformat(cached["fetched_at"])
                ).total_seconds()
                delay = (
                    60
                    if cached["error"]
                    in {"article_timeout", "article_source_temporary", "article_rate_limited"}
                    else 300
                )
                if not refresh and age < delay:
                    return cached
            if refresh:
                key = (uid, article_id)
                if time.monotonic() - self.body_retries.get(key, -10) < 5:
                    raise HTTPException(429, "article_retry_later", headers={"Retry-After": "5"})
                self.body_retries[key] = time.monotonic()
            result = {
                "news_id": article_id,
                "content": "",
                "source_url": cached["source_url"] if cached else article["url"],
                "fetched_at": now(),
                "status": "unavailable",
                "error": None,
                "truncated": False,
            }
            try:
                async with self.body_slots:
                    async with asyncio.timeout(60):
                        extracted = await self.reader.read(
                            result["source_url"], expected_title=article["title"]
                        )
                result.update(extracted, status="ready", fetched_at=now())
            except (ProviderError, TimeoutError) as exc:
                result["error"] = exc.code if isinstance(exc, ProviderError) else "article_timeout"
                if getattr(exc, "source_url", None):
                    result["source_url"] = exc.source_url
            # A retention cleanup may have removed/replaced this ID during the request.
            self.db.execute(
                "INSERT INTO news_bodies(news_id,content,source_url,fetched_at,status,error,truncated,published_at,modified_at) "
                "SELECT id,?,?,?,?,?,?,?,? FROM news WHERE id=? AND user_id=? AND fingerprint=? "
                "ON CONFLICT(news_id) DO UPDATE SET content=excluded.content,source_url=excluded.source_url,"
                "fetched_at=excluded.fetched_at,status=excluded.status,error=excluded.error,truncated=excluded.truncated,"
                "published_at=excluded.published_at,modified_at=excluded.modified_at",
                (
                    result["content"],
                    result["source_url"],
                    result["fetched_at"],
                    result["status"],
                    result["error"],
                    result["truncated"],
                    result.get("published_at"),
                    result.get("modified_at"),
                    article_id,
                    uid,
                    article["fingerprint"],
                ),
            )
            return result

    async def enrich_for_analysis(self, uid: int, articles: list[dict]):
        # Candidates have already been selected for holdings/industry relevance, not timestamp order.
        # Reuse cached bodies and bound total acquisition time while retaining every selected excerpt.
        try:
            async with asyncio.timeout(90):
                await asyncio.gather(
                    *(self.full_text(uid, article["id"]) for article in articles), return_exceptions=True
                )
        except TimeoutError:
            pass

    def topics(self, uid: int):
        watchlist = self.db.all("SELECT name,sector FROM watchlist WHERE user_id=?", (uid,))
        portfolio = self.db.cached(uid, "portfolio")
        holdings = (portfolio or {}).get("data", {}).get("positions", [])
        holdings = sorted(holdings, key=lambda position: position.get("value") or 0, reverse=True)
        names = [p["name"] or p["ticker"].split("_")[0] for p in holdings]
        names += [item["name"] for item in watchlist]
        sectors = [item["sector"] for item in watchlist if item["sector"]]
        company_queries = [query for name in names for query in (name, f"{name} industry")]
        return list(dict.fromkeys(sectors + company_queries))[:30] or ["financial markets"]

    def prune(self, uid: int):
        settings = self.db.settings(uid)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=settings["news_days"])).isoformat()
        with self.db.connect() as conn:
            conn.execute(
                "DELETE FROM news WHERE user_id=? AND COALESCE(published_at,fetched_at)<?", (uid, cutoff)
            )
            conn.execute(
                "DELETE FROM news WHERE user_id=? AND id NOT IN (SELECT id FROM news WHERE user_id=? "
                "ORDER BY COALESCE(published_at,fetched_at) DESC,id DESC LIMIT ?)",
                (uid, uid, settings["news_limit"]),
            )

    async def sync(self, uid: int):
        async with self.locks.setdefault(uid, asyncio.Lock()):
            if time.monotonic() < self.cooldowns.get(uid, 0):
                raise ProviderError("news_rate_limited", 60)
            self.cooldowns[uid] = time.monotonic() + 60
            language = self.db.settings(uid)["news_language"]
            locale = (
                {"hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"}
                if language == "zh"
                else {"hl": "en-GB", "gl": "GB", "ceid": "GB:en"}
            )
            added, errors = 0, []
            for topic in self.topics(uid):
                url = "https://news.google.com/rss/search?" + urlencode({"q": f"{topic} when:7d", **locale})
                try:
                    response = await self.client.get(url, follow_redirects=False)
                    response.raise_for_status()
                    if len(response.content) > 2_000_000:
                        raise ValueError("feed too large")
                    feed = feedparser.parse(response.content)
                    if not feed.entries:
                        errors.append({"topic": topic, "error": "empty_feed"})
                    with self.db.connect() as conn:
                        for entry in feed.entries[:35]:
                            title, content = (
                                plain(entry.get("title", ""))[:600],
                                plain(entry.get("summary", ""))[:6000],
                            )
                            link = entry.get("link", "")
                            if not title or urlparse(link).scheme not in {"https", "http"}:
                                continue
                            stamp = entry.get("published_parsed")
                            published = (
                                datetime.fromtimestamp(calendar.timegm(stamp), timezone.utc).isoformat()
                                if stamp
                                else None
                            )
                            source = plain(entry.get("source", {}).get("title", "Google News RSS"))[:200]
                            added += conn.execute(
                                "INSERT OR IGNORE INTO news(user_id,fingerprint,title,content,url,source,"
                                "topic,published_at,fetched_at) VALUES(?,?,?,?,?,?,?,?,?)",
                                (uid, digest(link), title, content, link, source, topic, published, now()),
                            ).rowcount
                except (httpx.HTTPError, ValueError):
                    errors.append({"topic": topic, "error": "news_feed_unavailable"})
            self.prune(uid)
            result = {"added": added, "errors": errors, "source": "Google News RSS", "as_of": now()}
            self.db.put_cache(uid, "news_status", result)
            return result
