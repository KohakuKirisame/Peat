import asyncio
import json
import sys

import httpx
import pytest

from peat.analysis_jobs import AnalysisJobs
from peat.app import create_app
from peat.config import Config
from peat.db import DEFAULT_SETTINGS, Database, now
from peat.runtime import Runtime


async def register(client, name="background-owner"):
    response = await client.post(
        "/api/auth/register", json={"username": name, "password": "fixture-password-123"}
    )
    response.raise_for_status()
    user = response.json()
    response = await client.put(
        "/api/settings", json=user["settings"] | {"ai_model": "fixture-max", "ai_live_data": False}
    )
    response.raise_for_status()
    return user["id"]


@pytest.mark.asyncio
async def test_background_job_survives_requests_and_settings_changes(tmp_path, monkeypatch):
    app = create_app(Config(data_dir=tmp_path, background=False))
    started, finish = asyncio.Event(), asyncio.Event()
    seen = []

    async def generate(uid, *, settings, progress):
        seen.append(settings["ai_model"])
        progress("generating")
        started.set()
        await finish.wait()
        aid = app.state.db.execute(
            "INSERT INTO analyses(user_id,provider,model,style,content,evidence,created_at) VALUES(?,?,?,?,?,?,?)",
            (
                uid,
                "openai",
                settings["ai_model"],
                settings["style"],
                "# Complete",
                json.dumps({"holding_horizon": settings["holding_horizon"]}),
                now(),
            ),
        )
        return {"id": aid}

    monkeypatch.setattr(app.state.ai, "analyze", generate)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://localhost", headers={"X-Peat-Request": "1"}
        ) as client:
            await register(client)
            response = await asyncio.wait_for(client.post("/api/ai/analyze"), 1)
            assert response.status_code == 202
            job = response.json()
            await started.wait()
            assert (await client.post("/api/ai/analyze")).json()["id"] == job["id"]
            assert len(seen) == 1
            settings = (await client.get("/api/me")).json()["settings"]
            await client.put(
                "/api/settings",
                json=settings | {"ai_model": "different-model", "holding_horizon": "ultra_short"},
            )
            # Other app operations remain available during the model call.
            assert (
                await client.post("/api/watchlist", json={"symbol": "ACME", "name": "Fixture company"})
            ).status_code == 200
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://localhost", cookies=client.cookies
            ) as refreshed:
                current = (await refreshed.get("/api/ai/jobs/current")).json()
                assert current["id"] == job["id"] and current["phase"] == "generating"
                assert current["model"] == "fixture-max"
                assert current["holding_horizon"] == "medium_long"
            task = app.state.analysis_jobs.tasks[job["id"]]
            finish.set()
            await task
            completed = (await client.get(f"/api/ai/jobs/{job['id']}")).json()
            assert completed["status"] == "completed" and completed["analysis_id"]
            assert (await client.get("/api/ai/analyses")).json()[0]["content"] == "# Complete"
            assert (await client.get("/api/ai/analyses")).json()[0]["holding_horizon"] == "medium_long"


@pytest.mark.asyncio
async def test_cancel_closes_model_request_without_deadline_and_is_user_scoped(tmp_path):
    app = create_app(Config(data_dir=tmp_path, background=False, llm_allowed_hosts={"localhost"}))
    started, closed = asyncio.Event(), asyncio.Event()
    timeouts = []

    async def model(request):
        timeouts.append(request.extensions["timeout"])
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    async with httpx.AsyncClient(transport=httpx.MockTransport(model)) as provider:
        app.state.ai.client = provider
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app),
                base_url="http://localhost",
                headers={"X-Peat-Request": "1"},
            ) as client:
                uid = await register(client)
                app.state.vault.set(
                    uid, "openai", {"base_url": "http://localhost/v1", "api_key": "fixture-only"}
                )
                app.state.db.put_cache(
                    uid, "portfolio", {"positions": [], "market_value": 0, "currency": "EUR"}
                )
                job = (await client.post("/api/ai/analyze")).json()
                await asyncio.wait_for(started.wait(), 2)
                assert all(value is None for value in timeouts[0].values())
                app.state.db.execute(
                    "UPDATE analysis_jobs SET created_at='2020-01-01T00:00:00+00:00' WHERE id=?", (job["id"],)
                )
                assert (await client.get("/api/ai/jobs/current")).json()["status"] == "running"
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app),
                    base_url="http://localhost",
                    headers={"X-Peat-Request": "1"},
                ) as other:
                    await register(other, "background-other")
                    assert (await other.get("/api/ai/jobs/current")).json() is None
                    assert (await other.get(f"/api/ai/jobs/{job['id']}")).status_code == 404
                    assert (await other.post(f"/api/ai/jobs/{job['id']}/cancel")).status_code == 404
                task = app.state.analysis_jobs.tasks[job["id"]]
                assert (await client.post(f"/api/ai/jobs/{job['id']}/cancel")).status_code == 200
                await asyncio.wait_for(task, 2)
                assert closed.is_set()
                assert (await client.get("/api/ai/jobs/current")).json()["status"] == "cancelled"
                assert (await client.get("/api/ai/analyses")).json() == []


@pytest.mark.asyncio
async def test_queued_cancel_and_restart_recovery(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    db.execute(
        "INSERT INTO users(id,username,password_hash,role,settings,created_at) VALUES(1,'fixture','unused','admin',?,?)",
        (json.dumps(DEFAULT_SETTINGS | {"ai_model": "fixture-max"}), now()),
    )

    class NeverStarted:
        async def analyze(self, *args, **kwargs):
            raise AssertionError("Cancelled queued jobs must not call a provider")

    manager = AnalysisJobs(db, NeverStarted())
    job = manager.start(1)
    manager.cancel(1, job["id"])
    await asyncio.sleep(0)
    assert manager.current(1)["status"] == "cancelled"
    db.execute("UPDATE analysis_jobs SET status='running' WHERE id=?", (job["id"],))
    AnalysisJobs(db, NeverStarted()).recover()
    assert manager.current(1)["status"] == "interrupted"
    assert manager.current(1)["error"] == "analysis_interrupted"


@pytest.mark.asyncio
async def test_cancelling_codex_runtime_reaps_process_tree_without_timeout(tmp_path):
    runtime = Runtime(Config(data_dir=tmp_path))
    marker = tmp_path / "started.txt"
    code = (
        "import subprocess,sys,time; from pathlib import Path; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(300)']); "
        f"Path({str(marker)!r}).write_text(str(child.pid)); time.sleep(300)"
    )
    task = asyncio.create_task(runtime.run_cancellable(1, [sys.executable, "-c", code], ""))
    for _ in range(100):
        if marker.exists():
            break
        await asyncio.sleep(0.02)
    assert marker.exists()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)


@pytest.mark.asyncio
async def test_server_shutdown_marks_active_jobs_interrupted(tmp_path, monkeypatch):
    app = create_app(Config(data_dir=tmp_path, background=False))
    started = asyncio.Event()

    async def generate(uid, *, settings, progress):
        progress("generating")
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(app.state.ai, "analyze", generate)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://localhost", headers={"X-Peat-Request": "1"}
        ) as client:
            await register(client)
            await client.post("/api/ai/analyze")
            await started.wait()
    assert app.state.db.one("SELECT status FROM analysis_jobs")["status"] == "interrupted"
