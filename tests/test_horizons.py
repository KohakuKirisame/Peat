import json

import pytest
from fastapi.testclient import TestClient

from peat.app import create_app
from peat.config import Config
from peat.db import DEFAULT_SETTINGS, now
from peat.prompts import defaults, resolve


def test_all_horizons_compose_with_every_risk_style_in_both_languages():
    for language in ("en", "zh"):
        templates = defaults(language)
        assert len(set(templates["horizons"].values())) == 3
        for style, style_text in templates["styles"].items():
            for horizon, horizon_text in templates["horizons"].items():
                prompts = resolve(
                    DEFAULT_SETTINGS | {"language": language, "style": style, "holding_horizon": horizon}
                )
                assert prompts["style"] == style_text
                assert prompts["horizon"] == horizon_text
    custom = DEFAULT_SETTINGS | {"holding_horizon": "short", "ai_horizon_prompts": {"short": "USER WINDOW"}}
    assert resolve(custom)["horizon"] == "USER WINDOW"
    custom["holding_horizon"] = "ultra_short"
    assert resolve(custom)["horizon"] == defaults()["horizons"]["ultra_short"]


def test_horizon_settings_validation_persistence_and_legacy_reports(tmp_path):
    app = create_app(Config(data_dir=tmp_path, background=False))
    with TestClient(app, base_url="http://localhost", headers={"X-Peat-Request": "1"}) as client:
        user = client.post(
            "/api/auth/register", json={"username": "horizon-owner", "password": "fixture-password-123"}
        ).json()
        assert user["settings"]["holding_horizon"] == "medium_long"
        settings = user["settings"] | {
            "holding_horizon": "short",
            "ai_horizon_prompts": {"short": "My weekly plan"},
        }
        assert client.put("/api/settings", json=settings).status_code == 200
        assert client.get("/api/me").json()["settings"]["holding_horizon"] == "short"
        assert client.get("/api/me").json()["settings"]["ai_horizon_prompts"] == {"short": "My weekly plan"}
        assert client.put("/api/settings", json=settings | {"holding_horizon": "invalid"}).status_code == 422
        assert (
            client.put(
                "/api/settings", json=settings | {"ai_horizon_prompts": {"short": "x" * 8001}}
            ).status_code
            == 422
        )
        for evidence in ({}, {"holding_horizon": "ultra_short"}):
            app.state.db.execute(
                "INSERT INTO analyses(user_id,provider,model,style,content,evidence,created_at) VALUES(1,'codex','fixture','balanced','Brief',?,?)",
                (json.dumps(evidence), now()),
            )
        reports = client.get("/api/ai/analyses").json()
        assert {report["holding_horizon"] for report in reports} == {None, "ultra_short"}


@pytest.mark.asyncio
async def test_codex_receives_selected_horizon_and_archives_the_resolved_prompt(tmp_path, monkeypatch):
    app = create_app(Config(data_dir=tmp_path, background=False))
    settings = DEFAULT_SETTINGS | {
        "ai_provider": "codex",
        "ai_live_data": False,
        "ai_model": "fixture-model",
        "holding_horizon": "short",
        "ai_horizon_prompts": {"short": "CUSTOM SHORT PLAN"},
    }
    db = app.state.db
    db.execute(
        "INSERT INTO users(id,username,password_hash,role,settings,created_at) VALUES(1,'fixture','unused','admin',?,?)",
        (json.dumps(settings), now()),
    )
    db.put_cache(1, "models_codex", [{"id": "fixture-model", "efforts": ["high"]}])
    db.put_cache(1, "portfolio", {"positions": [], "currency": "EUR", "market_value": 0})
    monkeypatch.setattr(app.state.runtime, "codex", lambda: ["fixture-codex"])
    captured = []

    async def generate(uid, args, prompt):
        captured.append(prompt)
        return (
            0,
            json.dumps(
                {"type": "item.completed", "item": {"type": "agent_message", "text": "# Fixture brief"}}
            ),
            "",
        )

    monkeypatch.setattr(app.state.runtime, "run_cancellable", generate)
    try:
        result = await app.state.ai.analyze(1)
        assert "CUSTOM SHORT PLAN" in captured[0]
        assert result["holding_horizon"] == "short"
        assert result["evidence"]["prompts"]["horizon"] == "CUSTOM SHORT PLAN"
    finally:
        await app.state.client.aclose()
