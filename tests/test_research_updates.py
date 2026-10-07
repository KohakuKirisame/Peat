import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from peat.ai import Intelligence
from peat.app import create_app
from peat.article_extract import inspect_page
from peat.brokers import ProviderError
from peat.config import Config
from peat.db import DEFAULT_SETTINGS, Database, now
from peat.research import ResearchContext


def save_report(db, uid, text="Archived view", evidence=None, created=None):
    stamp = created or now()
    return db.execute(
        "INSERT INTO analyses(user_id,provider,model,style,content,evidence,created_at,updated_at) VALUES(?,'openai','fixture','balanced',?,?,?,?)",
        (uid, text, json.dumps(evidence or {}), stamp, stamp),
    )


def test_report_delete_and_limits_remove_discussions_but_keep_active_report(tmp_path):
    app = create_app(Config(data_dir=tmp_path, background=False))
    db = app.state.db
    with TestClient(app, base_url="http://localhost", headers={"X-Peat-Request": "1"}) as client:
        owner = client.post(
            "/api/auth/register", json={"username": "retention-owner", "password": "fixture-password-123"}
        ).json()
        first = save_report(db, owner["id"], created="2026-01-01T00:00:00Z")
        second = save_report(db, owner["id"], created="2026-02-01T00:00:00Z")
        db.execute(
            "INSERT INTO analysis_jobs(id,user_id,status,phase,settings,kind,analysis_id,created_at,updated_at) VALUES('active',?,'running','replying',?,'followup',?,?,?)",
            (owner["id"], json.dumps(owner["settings"]), first, now(), now()),
        )
        db.execute(
            "INSERT INTO analysis_followups(analysis_id,job_id,request_key,question,answer,context,created_at) VALUES(?,'active','fixture-request','private question',NULL,'{}',?)",
            (first, now()),
        )
        assert client.delete(f"/api/ai/analyses/{first}").status_code == 409
        assert client.put("/api/settings", json=owner["settings"] | {"analysis_limit": 1}).status_code == 200
        assert client.get("/api/ai/storage").json() == {"count": 1, "limit": 1}
        assert client.get(f"/api/ai/analyses/{second}").status_code == 404
        assert client.get(f"/api/ai/analyses/{first}").status_code == 200
        client.post("/api/auth/logout")
        other = client.post(
            "/api/auth/register", json={"username": "retention-other", "password": "fixture-password-123"}
        ).json()
        other_report = save_report(db, other["id"])
        assert client.delete(f"/api/ai/analyses/{first}").status_code == 404
        client.post("/api/auth/logout")
        client.post(
            "/api/auth/login", json={"username": "retention-owner", "password": "fixture-password-123"}
        )
        db.execute("UPDATE analysis_jobs SET status='completed' WHERE id='active'")
        assert client.delete(f"/api/ai/analyses/{first}").status_code == 200
        assert db.all("SELECT * FROM analysis_followups WHERE analysis_id=?", (first,)) == []
        job = client.get("/api/ai/jobs/current").json()
        assert job["status"] == "deleted" and job["analysis_id"] is None
        assert (
            "ai_base_prompt" not in db.one("SELECT settings FROM analysis_jobs WHERE id='active'")["settings"]
        )
        assert db.one("SELECT id FROM analyses WHERE id=?", (other_report,))
        assert db.all("PRAGMA foreign_key_check") == []


def test_retention_keeps_recent_activity_and_archive_pages_are_lightweight(tmp_path):
    app = create_app(Config(data_dir=tmp_path, background=False))
    with TestClient(app, base_url="http://localhost", headers={"X-Peat-Request": "1"}) as client:
        user = client.post(
            "/api/auth/register", json={"username": "pages-owner", "password": "fixture-password-123"}
        ).json()
        ids = [
            save_report(
                app.state.db, user["id"], evidence={"reasoning_effort": "max", "holding_horizon": "short"}
            )
            for _ in range(23)
        ]
        page = client.get("/api/ai/analyses?summary=true").json()
        assert len(page) == 20 and "evidence" not in page[0] and "content" not in page[0]
        assert len(client.get(f"/api/ai/analyses?summary=true&before={page[-1]['id']}").json()) == 3
        app.state.db.execute("UPDATE analyses SET updated_at='2099-01-01T00:00:00Z' WHERE id=?", (ids[0],))
        client.put("/api/settings", json=user["settings"] | {"analysis_limit": 2})
        retained = client.get("/api/ai/analyses?summary=true").json()
        assert len(retained) == 2 and ids[0] in {row["id"] for row in retained}


def test_deleted_report_ids_are_not_reused_and_old_settings_clients_keep_new_preferences(tmp_path):
    app = create_app(Config(data_dir=tmp_path, background=False))
    with TestClient(app, base_url="http://localhost", headers={"X-Peat-Request": "1"}) as client:
        user = client.post(
            "/api/auth/register", json={"username": "stable-owner", "password": "fixture-password-123"}
        ).json()
        reports = app.state.analysis_jobs.reports
        first = reports.create(user["id"], "openai", "fixture", "balanced", "First", {}, now())
        client.delete(f"/api/ai/analyses/{first}")
        second = reports.create(user["id"], "openai", "fixture", "balanced", "Second", {}, now())
        assert second > first
        assert client.get(f"/api/ai/analyses/{first}").status_code == 404
        client.put("/api/settings", json={"analysis_limit": 2, "ai_live_data": False, "ai_web_search": False})
        client.put("/api/settings", json={"theme": "light"})
        saved = client.get("/api/me").json()["settings"]
        assert saved["analysis_limit"] == 2 and not saved["ai_live_data"] and not saved["ai_web_search"]


def test_article_original_and_modified_dates_stay_distinct(monkeypatch):
    monkeypatch.setattr("peat.article_extract.trafilatura.extract", lambda *args, **kwargs: None)
    article = {
        "@type": "NewsArticle",
        "url": "https://publisher.example/story",
        "datePublished": "2023-01-02T10:00:00Z",
        "dateModified": "2026-10-07T11:00:00Z",
        "articleBody": "A fixture article about an older company event and its historical context. " * 8,
    }
    result = inspect_page(
        f'<script type="application/ld+json">{json.dumps(article)}</script>'.encode(), article["url"]
    )
    assert (
        result["published_at"] == article["datePublished"]
        and result["modified_at"] == article["dateModified"]
    )


@pytest.mark.asyncio
async def test_live_followup_refreshes_inputs_and_archives_new_evidence_separately(tmp_path):
    app = create_app(Config(data_dir=tmp_path, background=False, llm_allowed_hosts={"localhost"}))
    db, refreshed = app.state.db, []

    class Broker:
        async def sync(self, uid, **kwargs):
            refreshed.append("portfolio")
            db.put_cache(
                uid,
                "portfolio",
                {
                    "positions": [{"ticker": "AAPL_US_EQ", "name": "Apple", "value": 200, "currency": "USD"}],
                    "market_value": 200,
                    "cash": 987654,
                },
            )

    class News:
        async def sync(self, uid):
            refreshed.append("news")
            stamp = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
            db.execute(
                "INSERT OR IGNORE INTO news(user_id,fingerprint,title,content,url,source,topic,published_at,fetched_at) VALUES(?,'live','Apple current catalyst','LIVE NEWS','https://publisher.example/live','Fixture','Apple',?,?)",
                (uid, stamp, now()),
            )

        async def enrich_for_analysis(self, uid, articles):
            pass

    class Markets:
        async def refresh(self, **kwargs):
            refreshed.append("markets")
            db.put_cache(0, "markets", {"quotes": [{"symbol": "UST10", "value": 4.2, "as_of": now()}]})
            return db.cached(0, "markets")

    class Charts:
        async def fetch(self, symbol, interval, period, **kwargs):
            assert kwargs["force"] and kwargs["extended"]
            refreshed.append("prices")
            at = datetime.now(timezone.utc)
            bars = [
                {
                    "time": int((at - timedelta(minutes=30 - i)).timestamp()),
                    "end_time": int((at - timedelta(minutes=29 - i)).timestamp()),
                    "session_date": at.date().isoformat(),
                    "open": 320,
                    "high": 322,
                    "low": 319,
                    "close": 321.25,
                    "volume": 100,
                    "complete": True,
                    "session": "regular",
                }
                for i in range(25)
            ]
            return {
                "data": {
                    "symbol": symbol,
                    "name": "Apple",
                    "currency": "USD",
                    "timezone": "America/New_York",
                    "interval": interval,
                    "status": "delayed",
                    "source": "Fixture",
                    "fetched_at": now(),
                    "candles": bars,
                    "latest_quote": {
                        "price": 321.25,
                        "as_of": now(),
                        "session": "regular",
                        "currency": "USD",
                    },
                }
            }

    news = News()
    app.state.ai.news = news
    app.state.ai.live = ResearchContext(db, Broker(), news, Markets(), Charts())
    requests = []

    def model(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "Updated view using current evidence"}}]}
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(model)) as provider,
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://localhost", headers={"X-Peat-Request": "1"}
        ) as client,
    ):
        app.state.ai.client = provider
        user = (
            await client.post(
                "/api/auth/register", json={"username": "live-owner", "password": "fixture-password-123"}
            )
        ).json()
        aid = save_report(
            db,
            user["id"],
            evidence={
                "news": [{"id": 88, "content": "OLD NEWS", "published_at": "2020-01-01"}],
                "holding_horizon": "ultra_short",
            },
        )
        app.state.vault.set(
            user["id"], "openai", {"base_url": "http://localhost/v1", "api_key": "fixture-only"}
        )
        path = f"/api/ai/analyses/{aid}/followups"
        job = (
            await client.post(
                path, json={"question": "Is the trigger still valid now?", "request_id": "live-question"}
            )
        ).json()
        for _ in range(300):
            state = (await client.get(f"/api/ai/jobs/{job['id']}")).json()
            if state["status"] not in {"queued", "running"}:
                break
            await asyncio.sleep(0.01)
        assert state["status"] == "completed"
        context = json.loads(requests[0]["messages"][1]["content"].split("\n", 1)[1])
        assert context["live_evidence"]["price_histories"][0]["quote"]["price"] == 321.25
        assert "LIVE NEWS" in json.dumps(context["live_evidence"])
        assert "987654" not in json.dumps(context)
        assert set(refreshed) == {"portfolio", "markets", "news", "prices"}
        turn = (await client.get(path)).json()["items"][0]
        assert turn["context_mode"] == "live" and turn["freshness"]["mode"] == "live_refresh"
        assert (await client.get(f"{path}/{turn['id']}/evidence")).json()["evidence"]["price_histories"]
        assert (await client.get(f"/api/ai/analyses/{aid}")).json()["content"] == "Archived view"


@pytest.mark.asyncio
async def test_unsupported_tools_fallback_does_not_drop_reasoning():
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        if "tools" in body:
            return httpx.Response(400, json={"error": {"param": "tools", "message": "unsupported parameter"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Refreshed evidence answer"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        ai = Intelligence(None, None, client, None, Config())
        trace = {}
        settings = DEFAULT_SETTINGS | {"ai_model": "fixture", "reasoning_effort": "max"}
        assert await ai.complete(
            1, settings, "Research", [], {"base_url": "https://api.example/v1"}, trace=trace
        )
        assert len(calls) == 2 and all(call["reasoning_effort"] == "max" for call in calls)
        assert trace["market_tools_status"] == "provider_unsupported"
        assert calls[0]["messages"][0]["content"] == "Research"
        assert calls[1]["messages"][0]["content"] == "Research" + trace["tool_availability_notice"]
        assert "Do not claim additional lookups" in calls[1]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_reasoning_rejections_are_not_silently_retried_without_effort():
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            400, json={"error": {"param": "reasoning_effort", "message": "unsupported reasoning effort"}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        ai = Intelligence(None, None, client, None, Config())
        with pytest.raises(ProviderError, match="model_or_reasoning_rejected"):
            await ai.complete(
                1,
                DEFAULT_SETTINGS | {"ai_model": "fixture", "reasoning_effort": "max"},
                "Research",
                [],
                {"base_url": "https://api.example/v1"},
            )
        assert len(calls) == 1 and calls[0]["reasoning_effort"] == "max"


def test_v4_upgrade_preserves_news_and_backfills_report_activity(tmp_path):
    db = Database(tmp_path / "upgrade.sqlite3")
    db.execute(
        "INSERT INTO users(id,username,password_hash,role,created_at) VALUES(1,'fixture','unused','admin','2026')"
    )
    report = save_report(db, 1, created="2026-01-01T00:00:00Z")
    db.execute(
        "INSERT INTO analysis_jobs(id,user_id,status,phase,settings,kind,analysis_id,created_at,updated_at) VALUES('reply',1,'completed','finished','{}','followup',?,'2026-02-01','2026-02-01')",
        (report,),
    )
    db.execute(
        "INSERT INTO analysis_followups(analysis_id,job_id,request_key,question,answer,created_at,answered_at) VALUES(?,'reply','fixture-key','Keep question','Keep answer','2026-02-01T00:00:00Z','2026-02-01T01:00:00Z')",
        (report,),
    )
    db.execute("ALTER TABLE analyses DROP COLUMN updated_at")
    db.execute("ALTER TABLE news_bodies DROP COLUMN published_at")
    db.execute("ALTER TABLE news_bodies DROP COLUMN modified_at")
    db.execute("DROP TABLE counters")
    db.execute("PRAGMA user_version=4")
    upgraded = Database(db.path)
    assert upgraded.one("SELECT updated_at FROM analyses")["updated_at"] == "2026-02-01T01:00:00Z"
    assert upgraded.one("SELECT answer FROM analysis_followups")["answer"] == "Keep answer"
    assert upgraded.one("SELECT value FROM counters WHERE name='analyses'")["value"] == report
    assert upgraded.one("PRAGMA user_version")["user_version"] == 5
    assert upgraded.all("PRAGMA foreign_key_check") == []
