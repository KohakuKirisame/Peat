import json
from datetime import datetime, timezone

import httpx
import pytest

from peat.brokers import ProviderError, Trading212, import_statement, statement_summary
from peat.charts import Charts, suggested_symbol
from peat.config import Config
from peat.db import Database
from peat.markets import exchange_status
from peat.news import NewsService, plain
from peat.security import validate_llm_url


@pytest.fixture
def db(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    db.execute(
        "INSERT INTO users(id,username,password_hash,role,created_at) VALUES(1,'fixture','unused','admin','2026-01-01')"
    )
    return db


@pytest.mark.asyncio
async def test_broker_currency_semantics_and_read_only():
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path.endswith("summary"):
            return httpx.Response(
                200,
                json={
                    "currency": "EUR",
                    "totalValue": 110,
                    "cash": {"availableToTrade": 20},
                    "investments": {
                        "totalCost": 80,
                        "currentValue": 90,
                        "realizedProfitLoss": 4,
                        "unrealizedProfitLoss": 10,
                    },
                },
            )
        return httpx.Response(
            200,
            json=[
                {
                    "instrument": {"ticker": "AAPL_US_EQ", "currency": "USD", "name": "Apple"},
                    "quantity": 1,
                    "currentPrice": 100,
                    "averagePricePaid": 92,
                    "walletImpact": {
                        "currency": "EUR",
                        "currentValue": 90,
                        "totalCost": 80,
                        "unrealizedProfitLoss": 10,
                    },
                }
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        broker = Trading212({"api_key": "fixture", "api_secret": "fixture"}, client)
        data = await broker.snapshot()
        assert data["unrealized"] == 10 and data["invested"] == 80
        position = data["positions"][0]
        assert position["price"] == 100 and position["value"] == 90 and position["currency"] == "USD"
        assert all(request.method == "GET" for request in requests)
        for path in (
            "https://evil.example/equity/history/orders",
            "//evil.example/equity/history/orders",
            "/equity/orders/market",
        ):
            with pytest.raises(ProviderError):
                await broker.get(path)
        assert len(requests) == 2


def test_statement_deduplication_multicurrency_and_atomic_rejection(db):
    csv = b"Action,Time,ID,Total,Currency (Total),Result,Currency (Result)\nDeposit,2026-01-01,A,1000,EUR,,\nWithdraw,2026-01-02,B,100,EUR,,\nMarket sell,2026-01-03,C,200,USD,12.34,EUR\nDividend,2026-01-04,D,2.50,USD,,\n"
    assert import_statement(db, 1, csv)["imported"] == 4
    assert import_statement(db, 1, csv)["duplicates"] == 4
    summary = statement_summary(db, 1)
    assert summary["currencies"]["EUR"]["net_deposits"] == 900
    assert summary["currencies"]["EUR"]["realized"] == 12.34
    assert summary["currencies"]["USD"]["dividends"] == 2.5
    invalid = csv + b"Deposit,2026-01-05,E,NaN,EUR,,\n"
    with pytest.raises(ProviderError):
        import_statement(db, 1, invalid)
    assert statement_summary(db, 1)["rows"] == 4


@pytest.mark.asyncio
async def test_news_plaintext_deduplication_and_retention(db):
    assert plain("<b>Title</b><script>alert(1)</script><p>Body &amp; more</p>") == "Title Body & more"
    db.execute("UPDATE users SET settings=? WHERE id=1", (json.dumps({"news_limit": 10, "news_days": 365}),))
    stamp = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    entries = "".join(
        f"<item><title>News {i}</title><description>&lt;b&gt;Content&lt;/b&gt;</description><link>https://example.com/{i}</link><pubDate>{stamp}</pubDate></item>"
        for i in range(15)
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=f'<rss version="2.0"><channel>{entries}</channel></rss>')
        )
    ) as client:
        service = NewsService(db, client)
        assert (await service.sync(1))["added"] == 15
        assert db.one("SELECT COUNT(*) AS n FROM news")["n"] == 10
        assert db.one("SELECT content FROM news")["content"] == "Content"


def test_exchange_holiday_dst_and_hong_kong_lunch():
    # US Independence Day, a normal Monday in summer, and the Hong Kong midday break.
    closed = {row["code"]: row for row in exchange_status(datetime(2026, 7, 3, 15, 0, tzinfo=timezone.utc))}
    assert closed["XNYS"]["status"] == "closed"
    opened = {row["code"]: row for row in exchange_status(datetime(2026, 7, 6, 14, 0, tzinfo=timezone.utc))}
    assert opened["XNYS"]["status"] == "open"
    lunch = {row["code"]: row for row in exchange_status(datetime(2026, 7, 6, 4, 30, tzinfo=timezone.utc))}
    assert lunch["XHKG"]["status"] == "closed"


@pytest.mark.asyncio
async def test_candles_skip_missing_values_without_fabricating_bars(db):
    chart = {
        "chart": {
            "result": [
                {
                    "meta": {"symbol": "AAPL", "currency": "USD"},
                    "timestamp": [100, 200, 300],
                    "indicators": {
                        "quote": [
                            {
                                "open": [10, None, 12],
                                "high": [12, None, 14],
                                "low": [9, None, 11],
                                "close": [11, None, 13],
                                "volume": [50, None, 70],
                            }
                        ]
                    },
                }
            ]
        }
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=chart))
    ) as client:
        service = Charts(db, client)
        result = await service.fetch("AAPL", "1d", "3mo")
        assert [c["time"] for c in result["data"]["candles"]] == [100, 300]
        with pytest.raises(ProviderError):
            await service.fetch("AAPL", "1m", "5y")
        with pytest.raises(ProviderError):
            await service.fetch("../../etc", "1d", "3mo")
    assert suggested_symbol("ASML_NL_EQ") == "ASML.AS"


def test_local_llm_requires_explicit_host_allowlist(tmp_path):
    from fastapi import HTTPException

    config = Config(data_dir=tmp_path)
    with pytest.raises(HTTPException):
        validate_llm_url("http://169.254.169.254/latest", config)
    with pytest.raises(HTTPException):
        validate_llm_url("https://127.0.0.1/v1", config)
    config.llm_allowed_hosts = {"localhost"}
    validate_llm_url("http://localhost:11434/v1", config)
