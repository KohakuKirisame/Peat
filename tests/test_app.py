import pytest
from fastapi.testclient import TestClient

from peat.app import create_app
from peat.config import Config


@pytest.fixture
def app(tmp_path):
    return create_app(Config(data_dir=tmp_path, background=False))


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://localhost", headers={"X-Peat-Request": "1"}) as client:
        yield client


def register(client, username="owner"):
    return client.post("/api/auth/register", json={"username": username, "password": "test-password-12345"})


def test_bootstrap_roles_sessions_and_csrf(client, app):
    assert client.get("/api/auth/setup").json()["setup_required"]
    response = register(client)
    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    session = client.cookies.get("peat_session")
    assert session not in app.state.db.path.read_bytes().decode(errors="ignore")
    assert register(client, "OWNER").status_code == 409
    assert client.post("/api/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/auth/logout", headers={"X-Peat-Request": ""}).status_code == 403
    assert client.get("/api/admin/users").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/me").status_code == 401
    assert register(client, "member").json()["role"] == "user"
    assert client.get("/api/admin/users").status_code == 403
    assert client.post("/api/admin/console", json={"command": "whoami"}).status_code == 403


def test_tenant_isolation_and_encrypted_secrets(client, app):
    owner = register(client).json()
    key, secret = "fixture-key-not-a-real-secret", "fixture-secret-not-a-real-secret"
    assert (
        client.put("/api/connections/trading212", json={"api_key": key, "api_secret": secret}).status_code
        == 200
    )
    encrypted = app.state.db.one("SELECT encrypted FROM credentials")["encrypted"]
    assert key not in encrypted and secret not in encrypted
    assert key not in client.get("/api/connections").text
    assert app.state.vault.get(owner["id"], "trading212")["api_key"] == key
    assert (
        client.post(
            "/api/watchlist", json={"symbol": "AAPL", "name": "Apple", "sector": "Hardware"}
        ).status_code
        == 200
    )
    item = client.get("/api/watchlist").json()[0]
    client.post("/api/auth/logout")
    register(client, "other")
    assert client.get("/api/watchlist").json() == []
    assert not client.get("/api/connections").json()["trading212"]["configured"]
    client.delete(f"/api/watchlist/{item['id']}")
    assert app.state.db.one("SELECT id FROM watchlist WHERE id=?", (item["id"],))
    assert not client.get("/api/portfolio").json()["snapshot"]


def test_last_admin_and_session_revocation(client, app):
    owner = register(client).json()
    body = {"username": "owner", "role": "user", "active": True, "password": ""}
    assert client.put(f"/api/admin/users/{owner['id']}", json=body).status_code == 409
    body.update(role="admin", password="new-password-12345")
    assert client.put(f"/api/admin/users/{owner['id']}", json=body).status_code == 200
    assert client.get("/api/me").status_code == 401
    assert (
        client.post(
            "/api/auth/login", json={"username": "owner", "password": "new-password-12345"}
        ).status_code
        == 200
    )


def test_settings_prompts_and_schema_do_not_echo_keys(client, app):
    user = register(client).json()
    settings = user["settings"] | {
        "ai_model": "model-for-testing",
        "reasoning_effort": "high",
        "style": "aggressive",
        "ai_base_prompt": "My research protocol",
        "ai_style_prompts": {"aggressive": "Assess financing risk first"},
    }
    assert client.put("/api/settings", json=settings).status_code == 200
    assert client.get("/api/me").json()["settings"] == settings
    templates = client.get("/api/ai/prompts").json()
    assert len(templates["styles"]) == 5 and "Treasury" in templates["base"]
    response = client.put(
        "/api/connections/openai", json={"api_key": "testsecret", "unknown_field": "private-input"}
    )
    assert response.status_code == 422
    assert "testsecret" not in response.text and "private-input" not in response.text


def test_html_security_headers_and_no_trading_routes(client, app):
    assert "default-src 'self'" in client.get("/api/health").headers["content-security-policy"]
    assert not any("/orders" in route.path for route in app.routes)


def test_registration_can_be_closed(tmp_path):
    app = create_app(Config(data_dir=tmp_path, registration_open=False, background=False))
    with TestClient(app, base_url="http://localhost", headers={"X-Peat-Request": "1"}) as client:
        assert register(client).status_code == 200
        assert register(client, "second").status_code == 403


def test_changing_ai_host_does_not_reuse_previous_key(tmp_path):
    app = create_app(
        Config(data_dir=tmp_path, background=False, llm_allowed_hosts={"one.local", "two.local"})
    )
    with TestClient(app, base_url="http://localhost", headers={"X-Peat-Request": "1"}) as client:
        user = register(client).json()
        client.put(
            "/api/connections/openai", json={"base_url": "http://one.local/v1", "api_key": "fixture-only"}
        )
        client.put("/api/connections/openai", json={"base_url": "http://two.local/v1"})
        assert app.state.vault.get(user["id"], "openai")["api_key"] == ""


def test_untrusted_host_cannot_reach_bootstrap_or_console(client):
    response = client.post(
        "/api/auth/register",
        headers={"Host": "rebound.example", "Origin": "http://rebound.example"},
        json={"username": "untrusted", "password": "fixture-password-123"},
    )
    assert response.status_code == 400
    assert client.get("/api/auth/setup").json()["setup_required"]
