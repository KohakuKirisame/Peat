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

    def topics(self, uid: int):
        watchlist = self.db.all("SELECT name,sector FROM watchlist WHERE user_id=?", (uid,))
        portfolio = self.db.cached(uid, "portfolio")
        holdings = (portfolio or {}).get("data", {}).get("positions", [])
        names = [p["name"] or p["ticker"].split("_")[0] for p in holdings]
        names += [item["name"] for item in watchlist]
        sectors = [item["sector"] for item in watchlist if item["sector"]]
        industry_queries = [f"{name} industry" for name in names]
        return list(dict.fromkeys(names + sectors + industry_queries))[:30] or ["financial markets"]

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
