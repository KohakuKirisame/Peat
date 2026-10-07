import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from peat.ai import Intelligence
from peat.brokers import ProviderError
from peat.charts import Charts
from peat.config import Config
from peat.db import DEFAULT_SETTINGS, Database, now
from peat.relevance import select_news
from peat.runtime import Runtime
from peat.temporal import news_timing, price_alignment


def epoch(value):
    return int(datetime.fromisoformat(value).timestamp())


def chart_payload():
    pre, opened, closed, post = (
        epoch(value)
        for value in (
            "2026-10-05T08:00:00+00:00",
            "2026-10-05T13:30:00+00:00",
            "2026-10-05T20:00:00+00:00",
            "2026-10-06T00:00:00+00:00",
        )
    )
    return {
        "meta": {
            "symbol": "AAPL",
            "currency": "USD",
            "exchangeName": "NMS",
            "instrumentType": "EQUITY",
            "exchangeTimezoneName": "America/New_York",
            "regularMarketTime": closed,
            "regularMarketPrice": 102,
            "tradingPeriods": {
                "pre": [[{"start": pre, "end": opened}]],
                "regular": [[{"start": opened, "end": closed}]],
                "post": [[{"start": closed, "end": post}]],
            },
        },
        "timestamp": [pre + 3600, opened + 600, closed + 3600],
        "indicators": {
            "quote": [
                {
                    "open": [99, 100, 103],
                    "high": [101, 104, 106],
                    "low": [98, 99, 102],
                    "close": [100, 102, 105],
                    "volume": [50, 200, 70],
                }
            ]
        },
    }


@pytest.mark.asyncio
async def test_extended_bars_are_classified_and_cached_separately(tmp_path):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"chart": {"result": [chart_payload()]}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        charts = Charts(Database(tmp_path / "test.sqlite3"), client)
        normal = await charts.fetch("AAPL", "5m", "5d")
        extended = await charts.fetch("AAPL", "5m", "5d", extended=True)
        await charts.fetch("AAPL", "5m", "5d", extended=True)
        assert len(requests) == 2
        assert requests[0].url.params["includePrePost"] == "false"
        assert requests[1].url.params["includePrePost"] == "true"
        assert not normal["data"]["extended_requested"]
        assert extended["data"]["extended_supported"]
        assert [bar["session"] for bar in extended["data"]["candles"]] == ["pre", "regular", "post"]
        assert extended["data"]["latest_quote"]["price"] == 105
        assert extended["data"]["latest_quote"]["session"] == "post"
        await charts.fetch("AAPL", "5m", "5d", extended=True, force=True)
        assert len(requests) == 3


@pytest.mark.asyncio
async def test_dated_price_window_never_substitutes_the_current_quote():
    payload = chart_payload()
    payload["meta"]["regularMarketTime"] = epoch("2026-10-07T16:00:00+00:00")
    payload["meta"]["regularMarketPrice"] = 999
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"chart": {"result": [payload]}}))
    ) as client:
        charts = Charts(None, client)
        result = (
            await charts.fetch(
                "AAPL", "5m", "5d", extended=True, start="2026-10-05T08:00:00Z", end="2026-10-06T00:00:00Z"
            )
        )["data"]
        assert result["latest_quote"]["price"] == 105
        assert result["as_of"].startswith("2026-10-05")
        with pytest.raises(ProviderError, match="invalid_chart_window"):
            await charts.fetch("AAPL", "5m", "5d", start="2026-10-05", end="2026-10-06")


def test_republished_old_news_is_background_and_undated_is_not_today(tmp_path):
    at = datetime.now(timezone.utc)
    old = {
        "published_at": at.isoformat(),
        "source_published_at": (at - timedelta(days=400)).isoformat(),
        "source_modified_at": at.isoformat(),
    }
    assert news_timing(old, "ultra_short", at)["timing_class"] == "background"
    assert news_timing({"fetched_at": at.isoformat()}, "ultra_short", at)["timing_class"] == "undated"
    db = Database(tmp_path / "news.sqlite3")
    db.execute(
        "INSERT INTO users(id,username,password_hash,role,created_at) VALUES(1,'fixture','unused','admin',?)",
        (now(),),
    )
    db.put_cache(1, "portfolio", {"positions": [{"ticker": "AAPL_US_EQ", "name": "Apple", "value": 100}]})
    ids = []
    for title in ("Apple old earnings reprinted", "Apple new product announcement"):
        ids.append(
            db.execute(
                "INSERT INTO news(user_id,fingerprint,title,content,url,source,topic,published_at,fetched_at) VALUES(1,?,?,?,'https://publisher.example/story','Fixture','Apple',?,?)",
                (title, title, title, at.isoformat(), at.isoformat()),
            )
        )
    db.execute(
        "INSERT INTO news_bodies(news_id,source_url,fetched_at,status,published_at) VALUES(?,'https://publisher.example/old',?,'ready',?)",
        (ids[0], now(), old["source_published_at"]),
    )
    selected = select_news(db, 1, horizon="ultra_short")["items"]
    assert selected[0]["id"] == ids[1]
    assert next(item for item in selected if item["id"] == ids[0])["timing_class"] == "background"


def test_event_alignment_excludes_straddling_and_unfinished_bars():
    def bar(at, close, complete=True):
        start = epoch(at)
        return {
            "time": start,
            "end_time": start + 300,
            "close": close,
            "session_date": "2026-10-05",
            "session": "regular",
            "complete": complete,
        }

    series = {
        "interval": "5m",
        "candles": [
            bar("2026-10-05T13:25:00+00:00", 100),
            bar("2026-10-05T13:30:00+00:00", 999),
            bar("2026-10-05T13:35:00+00:00", 102),
            bar("2026-10-05T14:35:00+00:00", 108),
            bar("2026-10-05T14:40:00+00:00", 200, False),
        ],
    }
    article = {
        "effective_published_at": "2026-10-05T13:32:00+00:00",
        "publication_precision": "time",
        "timing_class": "recent",
    }
    match = price_alignment(article, series, None)
    assert match["before"]["price"] == 100
    assert match["first_after"]["price"] == 102
    assert match["one_hour_after"]["price"] == 108
    assert match["one_hour_change_pct"] == 8
    daily = {
        "timezone": "America/New_York",
        "candles": [dict(bar("2026-10-05T13:30:00+00:00", 110), end_time=None)],
    }
    assert (
        price_alignment(article | {"effective_published_at": "2020-01-01T10:00:00Z"}, series, daily)["status"]
        == "outside_price_window"
    )


def test_date_only_news_uses_session_dates_without_claiming_an_intraday_time():
    bars = [
        {
            "time": epoch(f"2026-10-{day}T13:30:00+00:00"),
            "end_time": None,
            "session_date": f"2026-10-{day}",
            "close": price,
            "complete": True,
            "session": "regular",
        }
        for day, price in (("02", 90), ("05", 100), ("06", 105))
    ]
    article = {
        "effective_published_at": "2026-10-05",
        "publication_precision": "date",
        "timing_class": "recent",
    }
    context = price_alignment(article, None, {"timezone": "America/New_York", "candles": bars})
    assert context["before"]["session_date"] == "2026-10-02" and context["before"]["time"] is None
    assert context["next_session"]["session_date"] == "2026-10-06"
    assert context["basis"] == "publication_date"


@pytest.mark.asyncio
async def test_openai_research_calls_tools_and_keeps_reasoning_strength():
    requests = []

    async def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert all(value is None for value in request.extensions["timeout"].values())
        message = (
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "quote-1",
                        "type": "function",
                        "function": {"name": "get_quote", "arguments": '{"symbol":"AAPL"}'},
                    }
                ],
            }
            if len(requests) == 1
            else {"content": "Use the newly checked quote."}
        )
        return httpx.Response(200, json={"choices": [{"message": message}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        ai = Intelligence(None, None, client, None, Config())

        async def tool(name, arguments):
            assert name == "get_quote" and arguments == {"symbol": "AAPL"}
            return {"symbol": "AAPL", "price": 123.45, "as_of": now(), "retrieved_at": now()}

        ai.tools.call = tool
        trace = {}
        result = await ai.complete(
            1,
            DEFAULT_SETTINGS | {"ai_model": "fixture", "reasoning_effort": "max"},
            "Research",
            [{"role": "user", "content": "Current price?"}],
            {"base_url": "https://api.example/v1"},
            trace=trace,
        )
        assert result == "Use the newly checked quote."
        assert requests[1]["messages"][-1]["role"] == "tool"
        assert "123.45" in requests[1]["messages"][-1]["content"]
        assert all(request["reasoning_effort"] == "max" for request in requests)
        assert trace["market_calls"][0]["result"]["price"] == 123.45


@pytest.mark.asyncio
async def test_codex_live_search_and_scoped_mcp_preserve_read_only_controls(tmp_path, monkeypatch):
    runtime = Runtime(Config(data_dir=tmp_path))
    calls = []
    monkeypatch.setattr(runtime, "codex", lambda: ["codex-fixture"])

    async def run(uid, args, prompt):
        calls.append(args)
        events = [
            {"type": "item.completed", "item": {"type": "web_search", "query": "issuer event date"}},
            {
                "type": "item.completed",
                "item": {
                    "type": "mcp_tool_call",
                    "server": "peat_research",
                    "tool": "get_quote",
                    "result": {"structuredContent": {"symbol": "AAPL", "price": 123}},
                },
            },
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Checked reply"}},
        ]
        return 0, "\n".join(json.dumps(event) for event in events), ""

    monkeypatch.setattr(runtime, "run_cancellable", run)
    ai = Intelligence(None, None, None, runtime, Config())
    settings = DEFAULT_SETTINGS | {"ai_provider": "codex", "ai_model": "fixture"}
    trace = {}
    assert await ai.complete(1, settings, "Research", [], trace=trace) == "Checked reply"
    assert (
        'web_search="live"' in calls[0]
        and "read-only" in calls[0]
        and "features.shell_tool=false" in calls[0]
    )
    assert any(arg.startswith("mcp_servers.peat_research.command=") for arg in calls[0])
    assert trace["web_searches"][0]["query"] == "issuer event date"
    assert trace["market_calls"][0]["result"]["price"] == 123
    await ai.complete(1, settings | {"ai_live_data": False}, "Historical", [])
    assert 'web_search="disabled"' in calls[1] and not any(arg.startswith("mcp_servers.") for arg in calls[1])


@pytest.mark.asyncio
async def test_mcp_server_exposes_only_public_read_tools(tmp_path):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).resolve().parents[1] / "peat" / "market_mcp.py")],
        env=Runtime(Config(data_dir=tmp_path)).env(1),
    )
    async with stdio_client(parameters) as (reader, writer), ClientSession(reader, writer) as session:
        await session.initialize()
        listed = await session.list_tools()
        assert {tool.name for tool in listed.tools} == {
            "get_quote",
            "get_price_history",
            "search_news",
            "read_news_article",
        }
        assert all(tool.annotations.readOnlyHint for tool in listed.tools)
        result = await session.call_tool("get_quote", {"symbol": "../private"})
        payload = result.structuredContent or json.loads(result.content[0].text)
        assert not result.isError and payload["error"] == "invalid_research_tool_arguments"
