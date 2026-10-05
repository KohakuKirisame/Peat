import copy
import json
import socket
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from peat.ai import Intelligence
from peat.app import create_app
from peat.articles import ArticleReader
from peat.brokers import ProviderError
from peat.config import Config
from peat.db import Database, now
from peat.portfolio_context import investment_context
from peat.prompts import defaults
from peat.relevance import select_news


def add_news(db, uid, title, topic="", source="Fixture Press", days=0, url=None):
    stamp = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return db.execute(
        "INSERT INTO news(user_id,fingerprint,title,content,url,source,topic,published_at,fetched_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (
            uid,
            title + source,
            title,
            title + " fixture excerpt",
            url or "https://publisher.example/article",
            source,
            topic,
            stamp,
            now(),
        ),
    )


@pytest.fixture
def db(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    db.execute(
        "INSERT INTO users(id,username,password_hash,role,created_at) VALUES(1,'fixture','unused','admin',?)",
        (now(),),
    )
    db.put_cache(
        1,
        "portfolio",
        {
            "currency": "EUR",
            "total_value": 999999,
            "cash": 998999,
            "market_value": 1000,
            "positions": [
                {"ticker": "AAPL_US_EQ", "name": "Apple Inc", "value": 600},
                {"ticker": "MSFT_US_EQ", "name": "Microsoft Corp", "value": 400},
            ],
        },
    )
    return db


def test_relevance_uses_holdings_industries_and_coverage_instead_of_latest_five(db):
    db.execute("INSERT INTO watchlist(user_id,symbol,name,sector) VALUES(1,'NVDA','NVIDIA','Semiconductors')")
    unrelated = [add_news(db, 1, f"Football tournament fixture number {i}", "sports") for i in range(8)]
    apple = add_news(db, 1, "Apple quarterly earnings improve - Fixture Press", "Apple Inc", days=2)
    duplicate = add_news(
        db, 1, "Apple quarterly earnings improve - Second Press", "Apple Inc", source="Second Press", days=1
    )
    microsoft = add_news(db, 1, "Microsoft announces cloud earnings", "Microsoft Corp", days=3)
    industry = add_news(db, 1, "Chipmakers expand advanced manufacturing capacity", "Semiconductors", days=4)
    for i in range(8):
        add_news(db, 1, f"Apple product event discussion edition {i}", "Apple Inc", days=1)
    selected = select_news(db, 1)
    ids = {article["id"] for article in selected["items"]}
    assert not ids.intersection(unrelated)
    assert microsoft in ids and industry in ids
    assert len(ids.intersection({apple, duplicate})) == 1
    assert selected["selection"]["candidate_count"] == 20
    assert all(article["related_entities"] for article in selected["items"])
    assert selected["selection"]["industries"] == ["Semiconductors"]


def test_cash_and_deposits_are_absent_from_research_but_retained_in_account_data(db):
    original = db.cached(1, "portfolio")
    original["data"].update(
        cash_in_pies=120,
        cash_reserved=80,
        deposit=998999,
        pies=[
            {
                "id": 1,
                "name": "Core",
                "cash": 120,
                "value": 1000,
                "positions": copy.deepcopy(original["data"]["positions"]),
            }
        ],
    )
    before = copy.deepcopy(original)
    scoped = investment_context(original)
    assert original == before
    for key in ("cash", "cash_in_pies", "cash_reserved", "deposit", "total_value"):
        assert key not in scoped["data"]
    assert "cash" not in scoped["data"]["pies"][0]
    assert [p["weight_pct"] for p in scoped["data"]["positions"]] == [60, 40]
    assert original["data"]["cash"] == 998999


def test_ai_evidence_includes_relevant_article_text_and_selection_reasons(db):
    article = add_news(db, 1, "Apple releases quarterly results", "Apple Inc")
    add_news(db, 1, "Local football fixtures", "sports")
    body = "Full article evidence about Apple earnings and company demand. " * 30
    db.execute(
        "INSERT INTO news_bodies VALUES(?,?,?,?,?,?,?)",
        (article, body, "https://publisher.example/apple", now(), "ready", None, 0),
    )
    ai = Intelligence(db, None, None, None, Config(background=False))
    evidence = ai.evidence(1)
    assert [item["id"] for item in evidence["news"]] == [article]
    assert evidence["news"][0]["content"] == body
    assert evidence["news"][0]["content_kind"] == "article_body"
    assert evidence["news"][0]["related_entities"][0]["symbol"] == "AAPL_US_EQ"
    assert "cash" not in evidence["portfolio"]["data"]
    assert "999999" not in json.dumps(evidence["portfolio"])


def test_research_keeps_the_portfolio_used_to_select_news(db):
    add_news(db, 1, "Apple quarterly business update", "Apple Inc")
    selection = select_news(db, 1)
    db.put_cache(1, "portfolio", {"currency": "EUR", "positions": [], "market_value": 0, "cash": 50000})
    ai = Intelligence(db, None, None, None, Config(background=False))
    evidence = ai.evidence(1, selection)
    assert evidence["portfolio"]["data"]["market_value"] == 1000
    assert evidence["portfolio"]["data"]["positions"][0]["ticker"] == "AAPL_US_EQ"
    assert "cash" not in evidence["portfolio"]["data"]


def test_background_research_keeps_selected_news_after_cleanup_and_id_reuse(db):
    article = add_news(db, 1, "Apple original story", "Apple Inc")
    selection = select_news(db, 1)
    db.execute("DELETE FROM news WHERE id=?", (article,))
    reused = add_news(db, 1, "Unrelated later story", "Sports")
    assert reused == article
    ai = Intelligence(db, None, None, None, Config(background=False))
    evidence = ai.evidence(1, selection)
    assert evidence["news"][0]["title"] == "Apple original story"
    assert evidence["news"][0]["content_kind"] == "rss_excerpt"


def test_article_schema_upgrade_keeps_existing_news(db):
    article = add_news(db, 1, "Apple retained article", "Apple Inc")
    db.execute("DROP TABLE news_bodies")
    db.execute("PRAGMA user_version=1")
    upgraded = Database(db.path)
    assert upgraded.one("SELECT id FROM news WHERE id=?", (article,))
    assert upgraded.one("PRAGMA user_version")["user_version"] == 3


@pytest.mark.asyncio
async def test_article_reader_extracts_paragraphs_and_resolves_google_rpc(monkeypatch):
    reader = ArticleReader()
    paragraph = "This is an artificial article fixture describing company operations, quarterly demand and a manufacturing plan. The story contains source observations for a local extraction test."
    html = f"<html><head><title>Fixture article</title></head><body><nav>Navigation</nav><article><h1>Fixture company report</h1><p>{paragraph}</p><p>Second paragraph with additional details about operations and the results reported in this synthetic fixture.</p></article></body></html>"
    calls = []

    async def download(url, *, form=None):
        calls.append((url, form))
        if "rss/articles" in url:
            return b'<div data-n-a-sg="fixture-signature" data-n-a-ts="1234"></div>', url
        if "batchexecute" in url:
            return (
                json.dumps(
                    [["wrb.fr", "Fbv4je", json.dumps(["garturlres", "https://publisher.example/story"])]]
                )
                + "\n"
            ).encode(), url
        return html.encode(), url

    monkeypatch.setattr(reader, "download", download)
    result = await reader.read("https://news.google.com/rss/articles/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    assert paragraph in result["content"]
    assert "Navigation" not in result["content"]
    assert result["source_url"] == "https://publisher.example/story"
    assert calls[1][1]["f.req"]


@pytest.mark.asyncio
async def test_article_redirect_cannot_reach_private_network(monkeypatch):
    calls = []
    original_client = httpx.AsyncClient

    def transport(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    monkeypatch.setattr(
        "peat.articles.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(transport)),
    )
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, *args, **kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("127.0.0.1" if host == "127.0.0.1" else "93.184.216.34", 443),
            )
        ],
    )
    with pytest.raises(ProviderError, match="article_url_blocked"):
        await ArticleReader().download("https://publisher.example/story")
    assert len(calls) == 1
    assert calls[0].url.host == "93.184.216.34"
    assert calls[0].headers["host"] == "publisher.example"
    assert "authorization" not in calls[0].headers


def test_fulltext_is_cached_owned_and_deleted_with_news(tmp_path, monkeypatch):
    app = create_app(Config(data_dir=tmp_path, background=False))
    calls = []

    async def read(url, expected_title=None):
        calls.append(url)
        return {"content": "Fixture full article body. " * 20, "source_url": url, "truncated": False}

    monkeypatch.setattr(app.state.news.reader, "read", read)
    with TestClient(app, base_url="http://localhost", headers={"X-Peat-Request": "1"}) as client:
        client.post(
            "/api/auth/register", json={"username": "article-owner", "password": "fixture-password-123"}
        )
        article = add_news(app.state.db, 1, "Apple fixture", "Apple")
        first = client.post(f"/api/news/{article}/fulltext")
        assert first.status_code == 200 and first.json()["status"] == "ready"
        assert client.post(f"/api/news/{article}/fulltext").json()["content"] == first.json()["content"]
        assert len(calls) == 1
        client.post("/api/auth/logout")
        client.post(
            "/api/auth/register", json={"username": "article-other", "password": "fixture-password-123"}
        )
        assert client.post(f"/api/news/{article}/fulltext").status_code == 404
        assert len(calls) == 1
        app.state.db.execute("DELETE FROM news WHERE id=?", (article,))
        assert not app.state.db.one("SELECT news_id FROM news_bodies WHERE news_id=?", (article,))


def test_default_prompts_request_actions_and_securities_only_sizing():
    chinese = defaults("zh")["base"]
    for action in ("开仓", "增持", "减持", "平仓", "目标仓位", "触发条件", "证券持仓市值"):
        assert action in chinese
    assert "减少“不是……而是……”" in chinese
    assert "不得将 deposit 视为闲置现金" in chinese
    assert "OPEN, ADD, REDUCE, CLOSE, HOLD or WATCH" in defaults("en")["base"]
