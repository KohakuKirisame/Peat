"""Deterministic, portfolio-aware news selection with coverage and duplicate controls."""

import math
import re
from datetime import datetime, timezone

from .db import Database
from .temporal import news_timing

SECTOR_TERMS = {
    "semiconductors": ("semiconductor", "semiconductors", "chips", "chipmaker", "半导体", "芯片"),
    "technology": (
        "technology",
        "software",
        "cloud computing",
        "artificial intelligence",
        "科技",
        "软件",
        "人工智能",
    ),
    "energy": ("energy", "crude oil", "natural gas", "能源", "原油", "天然气"),
    "healthcare": ("healthcare", "pharma", "biotech", "clinical trial", "医疗", "医药", "生物科技"),
    "financials": ("banking", "bank", "banks", "insurance", "financial sector", "银行", "保险", "金融"),
    "consumer electronics": ("consumer electronics", "smartphone", "smartphones", "消费电子", "智能手机"),
}


def normalize(value: str) -> str:
    return " ".join(re.findall(r"[\w&]+", value.casefold()))


def mentions(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    if re.search(r"[\u3400-\u9fff]", phrase):
        return phrase in text
    return f" {phrase} " in f" {text} "


def aliases(name: str, ticker: str) -> set[str]:
    clean = re.sub(
        r"\b(?:incorporated|inc|corporation|corp|plc|ltd|limited|class [abc])\b", " ", name, flags=re.I
    )
    values = {normalize(name), normalize(clean).strip(), normalize(clean.split("(")[0])}
    symbol = ticker.split("_")[0].split(".")[0]
    if len(symbol) >= 3:
        values.add(normalize(symbol))
    return {value for value in values if len(value) >= 2}


def select_news(db: Database, uid: int, limit: int = 30, horizon="medium_long"):
    cached_portfolio = db.cached(uid, "portfolio")
    portfolio = (cached_portfolio or {}).get("data", {})
    holdings = portfolio.get("positions", [])
    watchlist = db.all("SELECT symbol,name,sector FROM watchlist WHERE user_id=?", (uid,))
    total = sum(max(0, item.get("value") or 0) for item in holdings) or 1
    entities, sectors = [], {}
    for item in holdings:
        entities.append(
            {
                "kind": "holding",
                "symbol": item["ticker"],
                "name": item.get("name") or item["ticker"],
                "aliases": aliases(item.get("name") or item["ticker"], item["ticker"]),
                "weight": max(0, item.get("value") or 0) / total,
            }
        )
    for item in watchlist:
        names = aliases(item["name"], item["symbol"])
        held = next((entity for entity in entities if names & entity["aliases"]), None)
        if not held:
            entities.append(
                {
                    "kind": "watchlist",
                    "symbol": item["symbol"],
                    "name": item["name"],
                    "aliases": names,
                    "weight": 0,
                }
            )
        if item["sector"]:
            label = item["sector"].strip()
            key = normalize(label)
            terms = {key}
            for group, vocabulary in SECTOR_TERMS.items():
                if key in {normalize(group), *(normalize(term) for term in vocabulary)}:
                    terms.update(normalize(term) for term in vocabulary)
            sectors[key] = {
                "kind": "industry",
                "name": label,
                "aliases": terms,
                "weight": max(sectors.get(key, {}).get("weight", 0), held["weight"] if held else 0),
            }
    candidates = db.all(
        "SELECT n.id,n.fingerprint,n.title,substr(n.content,1,1600) AS content,n.topic,n.source,n.url,n.published_at,n.fetched_at,"
        "b.published_at AS source_published_at,b.modified_at AS source_modified_at "
        "FROM news n LEFT JOIN news_bodies b ON b.news_id=n.id WHERE n.user_id=?",
        (uid,),
    )
    ranked = []
    current = datetime.now(timezone.utc)
    for article in candidates:
        title, body, topic = (normalize(article[field] or "") for field in ("title", "content", "topic"))
        related, score = [], 0.0
        for entity in [*entities, *sectors.values()]:
            in_title = any(mentions(title, term) for term in entity["aliases"])
            in_body = any(mentions(body, term) for term in entity["aliases"])
            in_topic = any(topic in {term, f"{term} industry"} for term in entity["aliases"])
            if not (in_title or in_body or in_topic):
                continue
            strength = 90 if in_title else 55 if in_body else 40
            priority = 1 if entity["kind"] == "holding" else 0.7 if entity["kind"] == "industry" else 0.55
            score += strength * priority + 25 * math.sqrt(entity["weight"])
            related.append(
                {
                    "kind": entity["kind"],
                    "name": entity["name"],
                    "symbol": entity.get("symbol"),
                    "matched_by": "headline" if in_title else "text" if in_body else "topic",
                }
            )
        if not related:
            continue
        timing = news_timing(article, horizon, current)
        if timing["timing_class"] == "future_unverified":
            continue
        age = timing["age_hours"]
        decay = {"ultra_short": 24, "short": 168, "medium_long": 720}.get(horizon, 720)
        score *= 0.25 + 0.75 * math.exp(-max(0, age) / decay) if age is not None else 0.2
        article.update(timing)
        article.update(relevance_score=round(score, 2), related_entities=related)
        ranked.append(article)
    ranked.sort(
        key=lambda item: (item["relevance_score"], item["published_at"] or item["fetched_at"], item["id"]),
        reverse=True,
    )

    selected, signatures, selected_ids, topic_counts, source_counts = [], [], set(), {}, {}

    def add(article):
        if article["id"] in selected_ids or len(selected) >= limit:
            return
        headline = article["title"]
        if " - " in headline and normalize(headline.rsplit(" - ", 1)[-1]) == normalize(article["source"]):
            headline = headline.rsplit(" - ", 1)[0]
        signature = set(normalize(headline).split())
        if any(
            signature == seen
            or (len(signature) >= 6 and len(signature & seen) / max(1, len(signature | seen)) >= 0.82)
            for seen in signatures
        ):
            return
        main = article["related_entities"][0]
        key = (main["kind"], main.get("symbol") or main["name"])
        if topic_counts.get(key, 0) >= 5:
            return
        selected.append(article)
        selected_ids.add(article["id"])
        signatures.append(signature)
        topic_counts[key] = topic_counts.get(key, 0) + 1
        source_counts[article["source"]] = source_counts.get(article["source"], 0) + 1

    # Reserve coverage for each held company and selected industry before filling by score.
    for entity in sorted(
        [*entities, *sectors.values()], key=lambda e: (e["kind"] == "holding", e["weight"]), reverse=True
    ):
        for article in ranked:
            if any(
                related["name"] == entity["name"] and related["kind"] == entity["kind"]
                for related in article["related_entities"]
            ):
                add(article)
                break
    remaining = [article for article in ranked if article["id"] not in selected_ids]
    while remaining and len(selected) < limit:
        article = max(
            remaining, key=lambda item: item["relevance_score"] - 8 * source_counts.get(item["source"], 0)
        )
        remaining.remove(article)
        add(article)
    selected.sort(key=lambda item: item["relevance_score"], reverse=True)
    return {
        "portfolio": cached_portfolio,
        "watchlist": watchlist,
        "items": selected,
        "selection": {
            "method": "holdings_industries_relevance",
            "candidate_count": len(candidates),
            "relevant_count": len(ranked),
            "selected_count": len(selected),
            "max_articles": limit,
            "holding_symbols": [entity["symbol"] for entity in entities if entity["kind"] == "holding"],
            "industries": [sector["name"] for sector in sectors.values()],
            "holding_horizon": horizon,
            "recent_count": sum(a["timing_class"] == "recent" for a in selected),
            "background_count": sum(a["timing_class"] == "background" for a in selected),
        },
    }
