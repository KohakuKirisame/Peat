import json

import httpx
import pytest

from peat.ai import Intelligence
from peat.app import create_app
from peat.brokers import ProviderError
from peat.config import Config
from peat.db import DEFAULT_SETTINGS
from peat.prompts import defaults, resolve


def test_five_distinct_editable_strategies():
    for language in ("en", "zh"):
        templates = defaults(language)
        assert len(set(templates["styles"].values())) == 5
        custom = DEFAULT_SETTINGS | {
            "language": language,
            "ai_base_prompt": "CUSTOM",
            "style": "aggressive",
            "ai_style_prompts": {"aggressive": "MY STYLE"},
        }
        assert resolve(custom) == {"base": "CUSTOM", "style": "MY STYLE"}


@pytest.mark.asyncio
async def test_ai_model_reasoning_prompt_and_provenance(tmp_path):
    config = Config(data_dir=tmp_path, background=False, llm_allowed_hosts={"localhost"})
    app = create_app(config)
    db = app.state.db
    settings = DEFAULT_SETTINGS | {
        "ai_model": "fixture-model",
        "reasoning_effort": "high",
        "ai_base_prompt": "MY BASE",
        "ai_style_prompts": {"balanced": "MY STRATEGY"},
    }
    db.execute(
        "INSERT INTO users(id,username,password_hash,role,created_at,settings) VALUES(1,'fixture','unused','admin','2026',?)",
        (json.dumps(settings),),
    )
    db.put_cache(1, "portfolio", {"positions": [], "total_value": 100, "as_of": "2026-01-01T00:00:00Z"})
    app.state.vault.set(1, "openai", {"base_url": "http://localhost:11434/v1", "api_key": "test-only-key"})
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "Evidence-based fixture answer."}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = Intelligence(db, app.state.vault, client, app.state.runtime, config)
        result = await service.analyze(1)
        assert requests[0]["model"] == "fixture-model" and requests[0]["reasoning_effort"] == "high"
        assert (
            "MY BASE" in requests[0]["messages"][0]["content"]
            and "MY STRATEGY" in requests[0]["messages"][0]["content"]
        )
        assert "test-only-key" not in json.dumps(result)
        assert result["evidence"]["prompts"]["base"] == "MY BASE"
        settings["reasoning_effort"] = "auto"
        db.execute("UPDATE users SET settings=? WHERE id=1", (json.dumps(settings),))
        await service.analyze(1)
        assert "reasoning_effort" not in requests[-1]
    await app.state.client.aclose()


def test_runtime_isolation_device_code_redaction_and_version_validation(tmp_path, monkeypatch):
    app = create_app(Config(data_dir=tmp_path, background=False))
    runtime = app.state.runtime
    monkeypatch.setenv("OPENAI_API_KEY", "host-secret")
    env = runtime.env(1)
    assert "OPENAI_API_KEY" not in env
    assert env["CODEX_HOME"] == runtime.env(2)["CODEX_HOME"]
    assert env["HOME"] != runtime.env(2)["HOME"]
    assert str(tmp_path) in env["CODEX_HOME"]
    runtime.jobs["login"] = {
        "id": "login",
        "uid": 1,
        "kind": "login",
        "status": "running",
        "exit_code": None,
        "output": "visit https://auth.openai.com/codex/device\nABCD-EFGH\nSECRET_ACCESS_TOKEN",
    }
    public = runtime.job(1, "login")
    assert public["user_code"] == "ABCD-EFGH"
    assert "SECRET_ACCESS_TOKEN" not in json.dumps(public)
    with pytest.raises(ProviderError):
        runtime.job(2, "login")
    with pytest.raises(ProviderError):
        runtime.update_codex(1, "latest; whoami")
