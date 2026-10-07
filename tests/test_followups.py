import asyncio
import json

import httpx
import pytest

from peat.app import create_app
from peat.config import Config
from peat.db import Database, now


async def owner(client, app, username="followup-owner", provider="openai"):
    user = (
        await client.post(
            "/api/auth/register", json={"username": username, "password": "fixture-password-123"}
        )
    ).json()
    uid = user["id"]
    await client.put("/api/settings", json=user["settings"] | {"ai_live_data": False})
    evidence = {
        "portfolio": {
            "updated_at": "2026-10-01T12:00:00Z",
            "data": {
                "positions": [{"ticker": "OLD_US_EQ", "value": 100}],
                "market_value": 100,
                "cash": 987654,
            },
        },
        "news": [{"id": 17, "content": "ARCHIVED INDUSTRY NEWS", "published_at": "2026-10-01"}],
        "prompts": {"base": "ORIGINAL BASE", "style": "ORIGINAL STYLE", "horizon": "ORIGINAL HORIZON"},
        "reasoning_effort": "max",
        "holding_horizon": "short",
    }
    aid = app.state.db.execute(
        "INSERT INTO analyses(user_id,provider,model,style,content,evidence,created_at) VALUES(?,?,?,?,?,?,?)",
        (uid, provider, "report-model", "aggressive", "# ORIGINAL REPORT", json.dumps(evidence), now()),
    )
    app.state.vault.set(uid, "openai", {"base_url": "http://localhost/v1", "api_key": "fixture-only-key"})
    app.state.db.put_cache(uid, "portfolio", {"positions": [{"ticker": "NEW_US_EQ"}], "cash": 111111})
    return uid, aid


async def terminal(client, job_id):
    for _ in range(300):
        job = (await client.get(f"/api/ai/jobs/{job_id}")).json()
        if job["status"] not in {"queued", "running", "cancelling"}:
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("Fixture job did not finish")


def client_for(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://localhost", headers={"X-Peat-Request": "1"}
    )


@pytest.mark.asyncio
async def test_multiturn_followups_use_saved_evidence_and_preserve_reports(tmp_path):
    app = create_app(Config(data_dir=tmp_path, background=False, llm_allowed_hosts={"localhost"}))
    requests = []

    def model(request):
        requests.append(json.loads(request.content))
        assert all(value is None for value in request.extensions["timeout"].values())
        return httpx.Response(
            200, json={"choices": [{"message": {"content": f"**Answer {len(requests)}** [news 17]"}}]}
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(model)) as provider,
        app.router.lifespan_context(app),
        client_for(app) as client,
    ):
        app.state.ai.client = provider
        uid, aid = await owner(client, app)
        path = f"/api/ai/analyses/{aid}/followups"
        first = {
            "question": "Why this allocation?",
            "request_id": "question-one",
            "model": "reply-model",
            "reasoning_effort": "high",
        }
        response = await client.post(path, json=first)
        assert response.status_code == 202
        job = response.json()
        assert job["kind"] == "followup" and job["analysis_id"] == aid
        assert job["style"] == "aggressive" and job["holding_horizon"] == "short"
        assert (await terminal(client, job["id"]))["status"] == "completed"
        # Retrying a lost response cannot duplicate the question or provider request.
        assert (await client.post(path, json=first)).json()["id"] == job["id"]
        assert (await client.post(path, json=first | {"question": "Changed question"})).status_code == 409
        second = (
            await client.post(
                path, json={"question": "And the exit condition?", "request_id": "question-two"}
            )
        ).json()
        assert (await terminal(client, second["id"]))["status"] == "completed"
        history = (await client.get(path)).json()["items"]
        assert (
            len(history) == 2
            and history[0]["model"] == "reply-model"
            and history[1]["model"] == "report-model"
        )
        assert requests[0]["reasoning_effort"] == "high"
        assert requests[1]["messages"][-3:] == [
            {"role": "user", "content": first["question"]},
            {"role": "assistant", "content": "**Answer 1** [news 17]"},
            {"role": "user", "content": "And the exit condition?"},
        ]
        payload = json.dumps(requests[0])
        for expected in (
            "ORIGINAL BASE",
            "ORIGINAL STYLE",
            "ORIGINAL HORIZON",
            "ORIGINAL REPORT",
            "ARCHIVED INDUSTRY NEWS",
            "OLD_US_EQ",
        ):
            assert expected in payload
        for absent in ("NEW_US_EQ", "987654", "111111", "fixture-only-key"):
            assert absent not in payload
        assert app.state.db.one("SELECT COUNT(*) AS n FROM analyses WHERE user_id=?", (uid,))["n"] == 1
        assert (await client.get(f"/api/ai/analyses/{aid}")).json()["content"] == "# ORIGINAL REPORT"


@pytest.mark.asyncio
async def test_pending_followup_ownership_cancellation_and_restart(tmp_path):
    app = create_app(Config(data_dir=tmp_path, background=False, llm_allowed_hosts={"localhost"}))
    started, closed = asyncio.Event(), asyncio.Event()

    async def model(request):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(model)) as provider,
        app.router.lifespan_context(app),
        client_for(app) as client,
    ):
        app.state.ai.client = provider
        _, aid = await owner(client, app)
        path = f"/api/ai/analyses/{aid}/followups"
        question = {"question": "A question to stop", "request_id": "cancel-request"}
        job = (await client.post(path, json=question)).json()
        await asyncio.wait_for(started.wait(), 2)
        assert (await client.post(path, json=question)).json()["id"] == job["id"]
        assert (await client.post(path, json=question | {"request_id": "second-active"})).status_code == 409
        # A report generation cannot silently return a follow-up job as its own result.
        settings = (await client.get("/api/me")).json()["settings"] | {"ai_model": "new-model"}
        await client.put("/api/settings", json=settings)
        assert (await client.post("/api/ai/analyze")).status_code == 409
        async with client_for(app) as other:
            await owner(other, app, "followup-other")
            assert (await other.get(path)).status_code == 404
            assert (await other.post(path, json=question)).status_code == 404
            assert (await other.get(f"/api/ai/analyses/{aid}")).status_code == 404
            assert (await other.post(f"/api/ai/jobs/{job['id']}/cancel")).status_code == 404
        async with client_for(app) as refreshed:
            refreshed.cookies.update(client.cookies)
            assert (await refreshed.get(path)).json()["items"][0]["status"] == "running"
        await client.post(f"/api/ai/jobs/{job['id']}/cancel")
        assert (await terminal(client, job["id"]))["status"] == "cancelled"
        assert closed.is_set()
        assert (await client.get(path)).json()["items"][0]["answer"] is None
        restarted = (
            await client.post(path, json={"question": "Restart fixture", "request_id": "restart-request"})
        ).json()
        app.state.analysis_jobs.cancel(1, restarted["id"])
        await terminal(client, restarted["id"])
        app.state.db.execute("UPDATE analysis_jobs SET status='running' WHERE id=?", (restarted["id"],))
        app.state.analysis_jobs.recover()
        assert (await client.get(path)).json()["items"][-1]["status"] == "interrupted"


@pytest.mark.asyncio
async def test_failed_questions_are_retained_but_not_replayed_as_conversation(tmp_path):
    app = create_app(Config(data_dir=tmp_path, background=False, llm_allowed_hosts={"localhost"}))
    calls = []

    def model(request):
        calls.append(json.loads(request.content))
        return (
            httpx.Response(503)
            if len(calls) == 1
            else httpx.Response(200, json={"choices": [{"message": {"content": "Recovered answer"}}]})
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(model)) as provider,
        app.router.lifespan_context(app),
        client_for(app) as client,
    ):
        app.state.ai.client = provider
        _, aid = await owner(client, app)
        path = f"/api/ai/analyses/{aid}/followups"
        failed = (
            await client.post(path, json={"question": "UNANSWERED QUESTION", "request_id": "failed-request"})
        ).json()
        assert (await terminal(client, failed["id"]))["status"] == "failed"
        retry = (
            await client.post(path, json={"question": "A new question", "request_id": "retry-request"})
        ).json()
        assert (await terminal(client, retry["id"]))["status"] == "completed"
        assert "UNANSWERED QUESTION" not in json.dumps(calls[-1])
        assert [item["status"] for item in (await client.get(path)).json()["items"]] == [
            "failed",
            "completed",
        ]


@pytest.mark.asyncio
async def test_codex_followup_uses_transcript_and_selected_effort(tmp_path, monkeypatch):
    app = create_app(Config(data_dir=tmp_path, background=False))
    captured = []

    async def run(uid, args, prompt):
        captured.append((args, prompt))
        return (
            0,
            json.dumps(
                {"type": "item.completed", "item": {"type": "agent_message", "text": "## Codex reply"}}
            ),
            "",
        )

    monkeypatch.setattr(app.state.runtime, "run_cancellable", run)
    monkeypatch.setattr(app.state.runtime, "codex", lambda: ["codex-fixture"])
    async with app.router.lifespan_context(app), client_for(app) as client:
        uid, aid = await owner(client, app, provider="codex")
        app.state.db.put_cache(uid, "models_codex", [{"id": "report-model", "efforts": ["max"]}])
        path = f"/api/ai/analyses/{aid}/followups"
        job = (
            await client.post(path, json={"question": "Explain the catalyst", "request_id": "codex-request"})
        ).json()
        assert (await terminal(client, job["id"]))["status"] == "completed"
        assert 'model_reasoning_effort="max"' in captured[0][0]
        assert "ORIGINAL HORIZON" in captured[0][1] and "Explain the catalyst" in captured[0][1]
        assert (await client.get(path)).json()["items"][0]["answer"] == "## Codex reply"


def test_schema_upgrade_preserves_existing_reports_and_jobs(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    db.execute(
        "INSERT INTO users(id,username,password_hash,role,created_at) VALUES(1,'fixture','unused','admin','2026')"
    )
    db.execute(
        "INSERT INTO analyses(id,user_id,provider,model,style,content,evidence,created_at) VALUES(1,1,'openai','fixture','balanced','KEEP REPORT','{}','2026')"
    )
    db.execute(
        "INSERT INTO analysis_jobs(id,user_id,status,phase,settings,analysis_id,created_at,updated_at) VALUES('old-job',1,'completed','finished','{}',1,'2026','2026')"
    )
    db.execute("DROP TABLE analysis_followups")
    db.execute("ALTER TABLE analysis_jobs DROP COLUMN kind")
    db.execute("PRAGMA user_version=3")
    migrated = Database(db.path)
    assert migrated.one("SELECT content FROM analyses")["content"] == "KEEP REPORT"
    assert migrated.one("SELECT kind FROM analysis_jobs")["kind"] == "analysis"
    assert migrated.one("PRAGMA user_version")["user_version"] == 5
    assert migrated.all("PRAGMA foreign_key_check") == []


@pytest.mark.asyncio
async def test_history_pagination_and_bounded_context_keep_complete_recent_turns(tmp_path):
    app = create_app(Config(data_dir=tmp_path, background=False, llm_allowed_hosts={"localhost"}))
    captured = []

    def model(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "A concise answer"}}]})

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(model)) as provider,
        app.router.lifespan_context(app),
        client_for(app) as client,
    ):
        app.state.ai.client = provider
        uid, aid = await owner(client, app)
        settings = json.dumps(app.state.db.settings(uid) | {"ai_model": "report-model"})
        with app.state.db.connect() as conn:
            for index in range(55):
                job_id = f"seeded-{index}"
                conn.execute(
                    "INSERT INTO analysis_jobs(id,user_id,status,phase,settings,kind,analysis_id,created_at,updated_at) VALUES(?,?,'completed','finished',?,'followup',?,?,?)",
                    (job_id, uid, settings, aid, now(), now()),
                )
                conn.execute(
                    "INSERT INTO analysis_followups(analysis_id,job_id,request_key,question,answer,created_at) VALUES(?,?,?,?,?,?)",
                    (aid, job_id, job_id, f"Question {index}", f"Answer {index}: " + "x" * 10000, now()),
                )
        path = f"/api/ai/analyses/{aid}/followups"
        page = (await client.get(path)).json()
        assert len(page["items"]) == 50 and page["items"][0]["question"] == "Question 5"
        earlier = (await client.get(path + f"?before={page['next_before']}")).json()
        assert len(earlier["items"]) == 5 and earlier["next_before"] is None
        job = (
            await client.post(
                path, json={"question": "Continue the last answer", "request_id": "budget-request"}
            )
        ).json()
        assert (await terminal(client, job["id"]))["status"] == "completed"
        latest = (await client.get(path)).json()["items"][-1]
        assert latest["included_turns"] == 7 and latest["omitted_turns"] == 48
        prior = captured[0]["messages"][2:-1]
        assert prior[0]["content"] == "Question 48" and prior[-2]["content"] == "Question 54"
        assert [message["role"] for message in prior] == ["user", "assistant"] * 7
        assert sum(len(message["content"]) for message in prior) < 80000
