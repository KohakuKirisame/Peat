import copy

import httpx
import pytest

from peat.brokers import BrokerService, ProviderError, Trading212, group_pie_holdings
from peat.config import Config
from peat.db import Database
from peat.security import Vault


def position(ticker, quantity, in_pies, value, pnl=20):
    return {
        "ticker": ticker,
        "name": ticker.split("_")[0],
        "quantity": quantity,
        "quantity_in_pies": in_pies,
        "value": value,
        "cost": value - pnl,
        "pnl": pnl,
        "price": 100,
        "currency": "USD",
        "account_currency": "EUR",
    }


def result(value, cost):
    return {"priceAvgValue": value, "priceAvgInvestedValue": cost, "priceAvgResult": value - cost}


def metadata():
    return [
        {
            "id": 1,
            "name": "Growth",
            "value": 700,
            "cost": 540,
            "pnl": 160,
            "cash": 15,
            "as_of": "2026-10-05T12:00:00Z",
            "positions": [
                {"ticker": "AAPL_US_EQ", "quantity": 3, "value": 300, "cost": 240, "pnl": 60},
                {"ticker": "MSFT_US_EQ", "quantity": 2, "value": 400, "cost": 300, "pnl": 100},
            ],
        },
        {
            "id": 2,
            "name": "Income",
            "value": 200,
            "cost": 150,
            "pnl": 50,
            "cash": 0,
            "as_of": "2026-10-05T12:00:05Z",
            "positions": [{"ticker": "AAPL_US_EQ", "quantity": 2, "value": 200, "cost": 150, "pnl": 50}],
        },
    ]


def snapshot():
    return {
        "currency": "EUR",
        "total_value": 1500,
        "unrealized": 325,
        "positions": [
            position("AAPL_US_EQ", 10, 5, 1000, 200),
            position("MSFT_US_EQ", 2, 2, 400, 100),
            position("NVDA_US_EQ", 1, 0, 100, 25),
        ],
    }


def test_pies_group_shared_tickers_without_mutating_or_double_counting_account():
    original = snapshot()
    before = copy.deepcopy(original)
    grouped = group_pie_holdings(original, metadata())
    assert original == before
    assert grouped["pie_status"]["state"] == "ready"
    assert [p["name"] for p in grouped["pies"]] == ["Growth", "Income"]
    assert grouped["pies"][0]["positions"][0]["currency"] == "USD"
    assert grouped["pies"][0]["account_currency"] == "EUR"
    outside = grouped["ungrouped_positions"]
    assert [(p["ticker"], p["quantity"]) for p in outside] == [("AAPL_US_EQ", 5), ("NVDA_US_EQ", 1)]
    assert outside[0]["value"] == 500
    assert outside[0]["pnl"] is None and outside[0]["cost"] is None
    assert outside[0]["partial_position"]
    assert outside[1]["pnl"] == 25
    for item in original["positions"]:
        shown = [p for pie in grouped["pies"] for p in pie["positions"]] + outside
        assert sum(p["quantity"] for p in shown if p["ticker"] == item["ticker"]) == item["quantity"]
    assert sum(p["value"] for p in grouped["pies"]) + sum(p["value"] for p in outside) == 1500


@pytest.mark.parametrize("change", ["overallocated", "missing_pie", "unknown_instrument"])
def test_inconsistent_pie_membership_keeps_flat_holdings(change):
    original, pies = snapshot(), metadata()
    if change == "overallocated":
        pies[0]["positions"][0]["quantity"] = 20
    elif change == "missing_pie":
        pies.pop()
    else:
        pies[0]["positions"][0]["ticker"] = "UNKNOWN_US_EQ"
    grouped = group_pie_holdings(original, pies)
    assert grouped["pies"] == []
    assert grouped["ungrouped_positions"] == original["positions"]
    assert grouped["pie_status"]["error"] == "pies_out_of_sync"


def test_empty_pie_and_cached_failure_remain_explicit():
    empty = {"id": 9, "name": "Cash only", "value": 0, "cost": 0, "pnl": 0, "cash": 40, "positions": []}
    assert group_pie_holdings({"positions": [], "currency": "EUR"}, [empty])["pies"][0]["cash"] == 40
    stale = group_pie_holdings(snapshot(), metadata(), "broker_rate_limited")
    assert stale["pie_status"]["state"] == "stale"
    assert len(stale["pies"]) == 2


@pytest.mark.asyncio
async def test_pie_adapter_reads_names_slice_results_and_spaces_detail_requests(monkeypatch):
    requests, waits = [], []

    async def sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr("peat.brokers.asyncio.sleep", sleep)

    def respond(request):
        requests.append(request)
        if request.url.path == "/api/v0/equity/pies":
            return httpx.Response(
                200,
                json=[
                    {"id": 1, "cash": 12, "result": result(300, 240)},
                    {"id": 2, "cash": 0, "result": result(200, 150)},
                ],
            )
        pie_id = int(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(
            200,
            json={
                "settings": {"id": pie_id, "name": f"Pie name {pie_id}"},
                "instruments": [
                    {
                        "ticker": "AAPL_US_EQ",
                        "ownedQuantity": 3 if pie_id == 1 else 2,
                        "result": result(300, 240),
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        adapter = Trading212({"api_key": "fixture", "api_secret": "fixture"}, client)
        pies = await adapter.pies()
        assert pies[0]["name"] == "Pie name 1"
        assert pies[0]["positions"][0]["quantity"] == 3
        assert pies[0]["positions"][0]["pnl"] == 60
        assert pies[0]["cash"] == 12
        assert waits == [5.1]
        assert len(requests) == 3 and all(r.method == "GET" for r in requests)
        for path in ("/equity/pies/1/duplicate", "/equity/pies/1/../orders", "/equity/pies/not-an-id"):
            with pytest.raises(ProviderError):
                await adapter.get(path)
        assert len(requests) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("pie_status", [200, 403, 429, 410])
async def test_optional_pie_sync_is_cached_and_does_not_break_positions(tmp_path, pie_status):
    config = Config(data_dir=tmp_path)
    db = Database(config.database)
    db.execute(
        "INSERT INTO users(id,username,password_hash,role,created_at) VALUES(1,'fixture','unused','admin','2026')"
    )
    vault = Vault(config, db)
    vault.set(1, "trading212", {"api_key": "fixture", "api_secret": "fixture"})
    requests = []

    def respond(request):
        path = request.url.path
        requests.append(path)
        if path.endswith("/summary"):
            return httpx.Response(
                200,
                json={
                    "currency": "EUR",
                    "totalValue": 100,
                    "investments": {
                        "totalCost": 80,
                        "currentValue": 100,
                        "realizedProfitLoss": 0,
                        "unrealizedProfitLoss": 20,
                    },
                },
            )
        if path.endswith("/positions"):
            return httpx.Response(
                200,
                json=[
                    {
                        "instrument": {"ticker": "AAPL_US_EQ", "currency": "USD"},
                        "quantity": 1,
                        "quantityInPies": 1,
                        "walletImpact": {"currentValue": 100, "totalCost": 80, "unrealizedProfitLoss": 20},
                    }
                ],
            )
        if path.endswith("/pies"):
            return httpx.Response(pie_status, json=[{"id": 1, "result": result(100, 80)}])
        return httpx.Response(
            200,
            json={
                "settings": {"name": "Core"},
                "instruments": [{"ticker": "AAPL_US_EQ", "ownedQuantity": 1, "result": result(100, 80)}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service = BrokerService(db, vault, client)
        first = await service.sync(1)
        assert first["data"]["total_value"] == 100
        assert first["data"]["positions"][0]["quantity_in_pies"] == 1
        assert not db.cached(1, "portfolio_status")["data"]["error"]
        if pie_status == 200:
            assert first["data"]["pies"][0]["name"] == "Core"
            assert first["data"]["ungrouped_positions"] == []
        else:
            assert not first["data"]["pies"]
            assert len(first["data"]["ungrouped_positions"]) == 1
            assert first["data"]["pie_status"]["error"]
        if pie_status == 403:
            assert first["data"]["pie_status"]["error"] == "pies_permission_required"
        service.next_attempt.pop((1, "portfolio"))
        await service.sync(1)
        assert requests.count("/api/v0/equity/pies") == 1
        assert requests.count("/api/v0/equity/positions") == 2


def test_portfolio_applies_saved_chart_mapping_to_every_pie_view(client, app):
    # Shared fixtures are defined locally below so this also runs independently.
    user = client.post(
        "/api/auth/register", json={"username": "pie-owner", "password": "test-password-12345"}
    ).json()
    data = snapshot()
    data.update(group_pie_holdings(data, metadata()))
    app.state.db.put_cache(user["id"], "portfolio", data)
    client.put("/api/charts/mapping", json={"ticker": "AAPL_US_EQ", "symbol": "AAPL"})
    returned = client.get("/api/portfolio").json()["snapshot"]["data"]
    assert returned["pies"][0]["positions"][0]["chart_symbol"] == "AAPL"
    assert returned["pies"][1]["positions"][0]["chart_symbol"] == "AAPL"
    assert returned["ungrouped_positions"][0]["chart_symbol"] == "AAPL"
    assert returned["positions"][0]["quantity"] == 10


@pytest.fixture
def app(tmp_path):
    from peat.app import create_app

    return create_app(Config(data_dir=tmp_path, background=False))


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="http://localhost", headers={"X-Peat-Request": "1"}) as client:
        yield client
