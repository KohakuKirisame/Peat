from pathlib import Path

from fastapi.testclient import TestClient

from peat.app import create_app
from peat.config import Config
from peat.db import Database
from peat.runtime import Runtime


def seed(db):
    db.execute(
        "INSERT INTO users(id,username,password_hash,role,created_at) VALUES(1,'owner','unused','admin','2026')"
    )
    db.execute(
        "INSERT INTO users(id,username,password_hash,role,created_at) VALUES(2,'member','unused','user','2026')"
    )


def test_existing_administrator_login_is_adopted_without_copying_tokens(tmp_path):
    db = Database(tmp_path / "peat.sqlite3")
    seed(db)
    legacy = tmp_path / "users/1/codex"
    legacy.mkdir(parents=True)
    (legacy / "auth.json").write_text('{"fixture":"not-a-real-credential"}')
    runtime = Runtime(Config(data_dir=tmp_path), db)
    assert Path(runtime.env(2)["CODEX_HOME"]) == legacy
    assert runtime.env(1)["HOME"] != runtime.env(2)["HOME"]
    assert not (tmp_path / "shared/codex/auth.json").exists()
    assert "not-a-real-credential" not in (tmp_path / "codex-shared.json").read_text()
    # Signing out never silently selects another account.
    (legacy / "auth.json").unlink()
    assert runtime.auth_home() == legacy


def test_regular_user_login_is_not_promoted_to_shared_identity(tmp_path):
    db = Database(tmp_path / "peat.sqlite3")
    seed(db)
    regular = tmp_path / "users/2/codex"
    regular.mkdir(parents=True)
    (regular / "auth.json").write_text('{"fixture":"member-credential"}')
    runtime = Runtime(Config(data_dir=tmp_path), db)
    assert runtime.auth_home() == tmp_path / "shared/codex"
    runtime.select_shared_login()
    assert runtime.env(1)["CODEX_HOME"] == runtime.env(2)["CODEX_HOME"]


def test_only_admin_can_manage_global_login_and_models_use_shared_identity(tmp_path, monkeypatch):
    app = create_app(Config(data_dir=tmp_path, background=False))
    runtime = app.state.runtime
    calls = []
    monkeypatch.setattr(runtime, "login", lambda uid: calls.append(("login", uid)) or "fixture-login-job")
    monkeypatch.setattr(runtime, "login_status", lambda uid: {"logged_in": True})
    monkeypatch.setattr(runtime, "codex", lambda: ["codex-fixture"])
    monkeypatch.setattr(runtime, "run", lambda *args: (0, "", ""))

    def models(uid):
        calls.append(("models", runtime.env(uid)["CODEX_HOME"]))
        return [{"id": "shared-model", "name": "Shared model", "efforts": ["high"], "default_effort": "high"}]

    monkeypatch.setattr(runtime, "models", models)
    with TestClient(app, base_url="http://localhost", headers={"X-Peat-Request": "1"}) as client:
        client.post("/api/auth/register", json={"username": "owner", "password": "fixture-password-123"})
        assert client.post("/api/codex/login").status_code == 200
        assert client.get("/api/codex/status").json() == {
            "logged_in": True,
            "shared": True,
            "can_manage": True,
        }
        shared_home = runtime.env(1)["CODEX_HOME"]
        client.post("/api/auth/logout")
        client.post("/api/auth/register", json={"username": "member", "password": "fixture-password-123"})
        assert client.post("/api/codex/login").status_code == 403
        assert client.post("/api/codex/logout").status_code == 403
        assert client.get("/api/codex/status").json() == {
            "logged_in": True,
            "shared": True,
            "can_manage": False,
        }
        assert client.get("/api/ai/models?provider=codex").json()[0]["id"] == "shared-model"
        assert calls[-1] == ("models", shared_home)
        assert "auth.json" not in client.get("/api/codex/status").text
