import httpx
import pytest
from fastapi.testclient import TestClient

from peat.app import create_app
from peat.brokers import BrokerService
from peat.charts import Charts, suggested_symbol
from peat.config import Config


def test_international_and_legacy_broker_codes_keep_the_listing():
    for ticker, currency, expected in (
        ("AIRp_EQ", "EUR", "AIR.PA"),
        ("SAPd_EQ", "EUR", "SAP.DE"),
        ("ASMLa_EQ", "EUR", "ASML.AS"),
        ("VUSA_EQ", "GBP", "VUSA.L"),
        ("ASML_NL_EQ", "EUR", "ASML.AS"),
        ("NOVN_CH_EQ", "CHF", "NOVN.SW"),
        ("700_HK_EQ", "HKD", "0700.HK"),
        ("7203_JP_EQ", "JPY", "7203.T"),
        ("VOLVb_SE_EQ", "SEK", "VOLV-B.ST"),
        ("BRK.B_US_EQ", "USD", "BRK-B"),
    ):
        assert suggested_symbol(ticker, currency) == expected
    # USD does not imply a US listing: London also has USD-denominated ETFs.
    assert suggested_symbol("VUSD_EQ", "USD") is None
    assert suggested_symbol("UNKNOWNx_EQ", "EUR") is None
    assert suggested_symbol("../unsafe", "EUR") is None
    assert suggested_symbol("AIR.PA") == "AIR.PA"


def test_exchange_metadata_distinguishes_nordic_nasdaq_and_us_nasdaq():
    assert (
        suggested_symbol("broker-id", metadata={"shortName": "NOVO B", "exchange": "Nasdaq Copenhagen"})
        == "NOVO-B.CO"
    )
    assert suggested_symbol("broker-id", metadata={"shortName": "AAPL", "exchange": "NASDAQ"}) == "AAPL"


def test_chart_route_resolves_airbus_unknown_ids_and_respects_user_mapping(tmp_path, monkeypatch):
    seen = []

    async def fetch(self, symbol, interval, period, **kwargs):
        seen.append((symbol, interval, period))
        return {"data": {"symbol": symbol, "candles": []}}

    async def metadata(self, uid, ticker):
        return {"shortName": "VUSD", "exchange": "London Stock Exchange"} if ticker == "VUSD_EQ" else None

    monkeypatch.setattr(Charts, "fetch", fetch)
    monkeypatch.setattr(BrokerService, "chart_instrument", metadata)
    app = create_app(Config(data_dir=tmp_path, background=False))
    with TestClient(app, base_url="http://localhost", headers={"X-Peat-Request": "1"}) as client:
        client.post(
            "/api/auth/register", json={"username": "chart-owner", "password": "fixture-password-123"}
        )
        app.state.db.put_cache(1, "portfolio", {"positions": [{"ticker": "AIRp_EQ", "currency": "EUR"}]})
        assert (
            client.get("/api/portfolio").json()["snapshot"]["data"]["positions"][0]["chart_symbol"]
            == "AIR.PA"
        )
        response = client.get("/api/charts?symbol=AIRp_EQ&interval=15m&period=5d")
        assert response.status_code == 200 and seen[-1] == ("AIR.PA", "15m", "5d")
        assert client.get("/api/charts?symbol=VUSD_EQ").json()["data"]["symbol"] == "VUSD.L"
        assert client.get("/api/charts?symbol=UNKNOWNx_EQ").json()["detail"] == "chart_symbol_required"
        assert (
            client.put("/api/charts/mapping", json={"ticker": "AIRp_EQ", "symbol": "AIR.DE"}).status_code
            == 200
        )
        assert client.get("/api/charts?symbol=AIRp_EQ").json()["data"]["symbol"] == "AIR.DE"


@pytest.mark.asyncio
async def test_chart_metadata_joins_working_schedules_and_reuses_cache(tmp_path, monkeypatch):
    app = create_app(Config(data_dir=tmp_path, background=False))
    db, broker = app.state.db, app.state.brokers
    db.execute(
        "INSERT INTO users(id,username,password_hash,role,created_at) VALUES(1,'fixture','unused','admin','2026')"
    )
    calls = []

    class Adapter:
        async def get(self, path):
            calls.append(path)
            if path.endswith("instruments"):
                return [
                    {"ticker": "VUSD_EQ", "shortName": "VUSD", "currencyCode": "USD", "workingScheduleId": 17}
                ]
            return [{"name": "London Stock Exchange", "workingSchedules": [{"id": 17}]}]

    monkeypatch.setattr(broker, "adapter", lambda uid: Adapter())
    for _ in range(2):
        instrument = await broker.chart_instrument(1, "VUSD_EQ")
        assert instrument["exchange"] == "London Stock Exchange"
        assert suggested_symbol("VUSD_EQ", metadata=instrument) == "VUSD.L"
    assert len(calls) == 2
    await app.state.client.aclose()


@pytest.mark.asyncio
async def test_market_observations_keep_timestamps_aligned_across_missing_quotes(tmp_path):
    from peat.db import Database
    from peat.markets import Markets

    payload = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "regularMarketPrice": 3.1234,
                        "regularMarketTime": 300,
                        "exchangeTimezoneName": "America/New_York",
                    },
                    "timestamp": [100, 200, 300],
                    "indicators": {"quote": [{"close": [3.0012, None, 3.1234]}]},
                }
            ]
        }
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    ) as client:
        quote = await Markets(Database(tmp_path / "test.sqlite3"), client).commodity(
            "NG=F", "Natural gas", "USD/MMBtu"
        )
    assert quote["timezone"] == "America/New_York"
    assert [point["value"] for point in quote["observations"]] == [3.0012, 3.1234]
    assert [point["date"] for point in quote["observations"]] == [
        "1970-01-01T00:01:40+00:00",
        "1970-01-01T00:05:00+00:00",
    ]
