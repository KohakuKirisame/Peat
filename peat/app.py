import asyncio
import importlib.metadata
import json
import os
import sqlite3
import sys
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .ai import Intelligence
from .analysis_jobs import AnalysisJobs
from .brokers import BrokerService, ProviderError, import_statement, statement_summary
from .charts import Charts, suggested_symbol
from .config import Config
from .db import Database, now
from .markets import Markets, exchange_status
from .news import NewsService
from .prompts import defaults
from .research import ResearchContext
from .runtime import Runtime
from .security import Vault, digest, hasher, new_session, validate_llm_url, verify_password


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Body):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=128)


class Settings(Body):
    theme: Literal["light", "dark", "system"] = "dark"
    accent: str = Field(default="#8a9aff", pattern=r"^#[0-9a-fA-F]{6}$")
    language: Literal["zh", "en"] = "en"
    style: Literal["very_conservative", "conservative", "balanced", "aggressive", "very_aggressive"] = (
        "balanced"
    )
    holding_horizon: Literal["ultra_short", "short", "medium_long"] = "medium_long"
    analysis_limit: int = Field(default=0, ge=0, le=1000)
    ai_live_data: bool = True
    ai_web_search: bool = True
    ai_market_tools: bool = True
    news_limit: int = Field(default=500, ge=10, le=20000)
    news_days: int = Field(default=30, ge=1, le=365)
    news_interval: int = Field(default=900, ge=300, le=86400)
    portfolio_interval: int = Field(default=60, ge=15, le=3600)
    ai_provider: Literal["openai", "codex"] = "openai"
    ai_model: str = Field(default="", max_length=120, pattern=r"^[A-Za-z0-9_./:@-]*$")
    reasoning_effort: Literal["auto", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"] = (
        "auto"
    )
    news_language: Literal["zh", "en"] = "en"
    ai_base_prompt: str = Field(default="", max_length=15000)
    ai_style_prompts: dict[
        Literal["very_conservative", "conservative", "balanced", "aggressive", "very_aggressive"], str
    ] = Field(default_factory=dict, max_length=5)
    ai_horizon_prompts: dict[Literal["ultra_short", "short", "medium_long"], str] = Field(
        default_factory=dict, max_length=3
    )


class Credential(Body):
    api_key: str = Field(default="", max_length=4096)
    api_secret: str = Field(default="", max_length=4096)
    base_url: str = Field(default="https://api.openai.com/v1", max_length=500)
    environment: Literal["live", "demo"] = "live"


class Watch(Body):
    symbol: str = Field(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9.^=_-]+$")
    name: str = Field(min_length=1, max_length=120)
    sector: str = Field(default="", max_length=100)


class AdminEdit(Body):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    role: Literal["admin", "user"]
    active: bool
    password: str = Field(default="", max_length=128)


class Command(Body):
    command: str = Field(min_length=1, max_length=4000)


class Version(Body):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:-[a-zA-Z0-9.]+)?$")


class Mapping(Body):
    ticker: str = Field(max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")
    symbol: str = Field(max_length=30, pattern=r"^[A-Za-z0-9^][A-Za-z0-9.^=\-]*$")


class Followup(Body):
    question: str = Field(min_length=1, max_length=8000)
    request_id: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    refresh_context: bool | None = None
    web_search: bool | None = None
    market_tools: bool | None = None
    provider: Literal["openai", "codex"] | None = None
    model: str | None = Field(default=None, max_length=120, pattern=r"^[A-Za-z0-9_./:@-]*$")
    reasoning_effort: (
        Literal["auto", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"] | None
    ) = None


def create_app(config: Config | None = None):
    config = config or Config()
    db = Database(config.database)
    vault = Vault(config, db)
    client = httpx.AsyncClient(
        timeout=20, follow_redirects=False, headers={"User-Agent": "Peat/0.1 (+self-hosted research)"}
    )
    brokers, news, markets = BrokerService(db, vault, client), NewsService(db, client), Markets(db, client)
    runtime, charts = Runtime(config, db), Charts(db, client)
    research = ResearchContext(db, brokers, news, markets, charts)
    ai = Intelligence(db, vault, client, runtime, config, news=news, live=research)
    analysis_jobs = AnalysisJobs(db, ai)
    attempts = defaultdict(deque)

    async def scheduler():
        last = {}
        while True:
            try:
                for user in db.all("SELECT id FROM users WHERE active=1"):
                    uid = user["id"]
                    settings = db.settings(uid)
                    for kind, interval, operation in (
                        ("portfolio", settings["portfolio_interval"], brokers.sync),
                        ("news", settings["news_interval"], news.sync),
                    ):
                        if time.monotonic() - last.get((uid, kind), 0) < interval:
                            continue
                        last[uid, kind] = time.monotonic()
                        if kind == "portfolio" and not vault.get(uid, "trading212"):
                            continue
                        try:
                            await operation(uid)
                        except ProviderError:
                            pass
                await markets.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:
                # No provider responses or credentials enter server logs.
                pass
            await asyncio.sleep(15)

    @asynccontextmanager
    async def lifespan(app):
        analysis_jobs.recover()
        task = asyncio.create_task(scheduler()) if config.background else None
        yield
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await analysis_jobs.shutdown()
        runtime.shutdown()
        await client.aclose()

    app = FastAPI(title="Peat", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.db, app.state.vault, app.state.brokers = db, vault, brokers
    app.state.client, app.state.ai, app.state.runtime, app.state.news = client, ai, runtime, news
    app.state.analysis_jobs = analysis_jobs
    app.state.research, app.state.charts = research, charts
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-Peat-Request"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        allowed_hosts = {urlparse(origin).hostname for origin in config.origins}
        if request.url.hostname not in allowed_hosts:
            return JSONResponse({"detail": "unrecognized_host"}, 400)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            same_origin = str(request.base_url).rstrip("/")
            if request.headers.get("x-peat-request") != "1" or (
                origin and origin not in [same_origin, *config.origins]
            ):
                return JSONResponse({"detail": "invalid_origin"}, 403)
            try:
                if int(request.headers.get("content-length", "0")) > 11_000_000:
                    return JSONResponse({"detail": "request_too_large"}, 413)
            except ValueError:
                return JSONResponse({"detail": "invalid_request"}, 400)
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
            }
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return JSONResponse(
            {"detail": exc.code, "retry_after": exc.retry_after},
            status_code=429 if exc.retry_after else 502,
            headers={"Retry-After": str(exc.retry_after)} if exc.retry_after else None,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            {"detail": "invalid_request", "fields": [list(error["loc"]) for error in exc.errors()]}, 422
        )

    def current_user(request: Request):
        token = request.cookies.get("peat_session", "")
        user = db.one(
            "SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token_hash=? "
            "AND s.expires_at>? AND u.active=1",
            (digest(token), now()),
        )
        if not user:
            raise HTTPException(401, "login_required")
        return user

    def admin(user=Depends(current_user)):
        if user["role"] != "admin":
            raise HTTPException(403, "admin_required")
        return user

    def public_user(user):
        return {key: user[key] for key in ("id", "username", "role", "active", "created_at")} | {
            "settings": db.settings(user["id"])
        }

    def login_limit(request):
        ip = request.client.host if request.client else "local"
        records = attempts[ip]
        while records and records[0] < time.monotonic() - 300:
            records.popleft()
        if len(records) >= 20:
            raise HTTPException(429, "too_many_attempts")
        records.append(time.monotonic())

    def set_session(response, uid):
        response.set_cookie(
            "peat_session",
            new_session(db, uid),
            httponly=True,
            samesite="strict",
            secure=config.secure_cookies,
            max_age=604800,
            path="/",
        )

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/auth/setup")
    def setup():
        first = not bool(db.one("SELECT id FROM users LIMIT 1"))
        return {"setup_required": first, "registration_open": config.registration_open or first}

    @app.post("/api/auth/register")
    def register(body: Login, request: Request, response: Response):
        login_limit(request)
        hashed = hasher.hash(body.password)
        try:
            with db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                first = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
                if not first and not config.registration_open:
                    raise HTTPException(403, "registration_closed")
                uid = conn.execute(
                    "INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
                    (body.username, hashed, "admin" if first else "user", now()),
                ).lastrowid
        except sqlite3.IntegrityError:
            raise HTTPException(409, "username_taken") from None
        set_session(response, uid)
        return public_user(db.one("SELECT * FROM users WHERE id=?", (uid,)))

    @app.post("/api/auth/login")
    def login(body: Login, request: Request, response: Response):
        login_limit(request)
        user = db.one("SELECT * FROM users WHERE username=?", (body.username,))
        if not user or not user["active"] or not verify_password(user["password_hash"], body.password):
            raise HTTPException(401, "invalid_credentials")
        set_session(response, user["id"])
        return public_user(user)

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        db.execute(
            "DELETE FROM sessions WHERE token_hash=?", (digest(request.cookies.get("peat_session", "")),)
        )
        response.delete_cookie("peat_session", path="/")
        return {"ok": True}

    @app.get("/api/me")
    def me(user=Depends(current_user)):
        return public_user(user)

    @app.put("/api/settings")
    def settings(body: Settings, user=Depends(current_user)):
        body = Settings(**(db.settings(user["id"]) | body.model_dump(exclude_unset=True)))
        if any(
            len(value) > 8000
            for value in (*body.ai_style_prompts.values(), *body.ai_horizon_prompts.values())
        ):
            raise HTTPException(422, "prompt_too_long")
        db.execute("UPDATE users SET settings=? WHERE id=?", (body.model_dump_json(), user["id"]))
        analysis_jobs.reports.prune(user["id"], limit=body.analysis_limit)
        news.prune(user["id"])
        return body

    @app.get("/api/connections")
    def connections(user=Depends(current_user)):
        broker, llm = vault.get(user["id"], "trading212"), vault.get(user["id"], "openai")
        return {
            "trading212": {
                "configured": bool(broker.get("api_key")),
                "environment": broker.get("environment", "live"),
            },
            "openai": {
                "configured": bool(llm.get("base_url")),
                "base_url": llm.get("base_url", "https://api.openai.com/v1"),
            },
        }

    @app.put("/api/connections/{provider}")
    async def connect(
        provider: Literal["trading212", "openai"], body: Credential, user=Depends(current_user)
    ):
        async with brokers.locks.setdefault(user["id"], asyncio.Lock()):
            existing = vault.get(user["id"], provider)
            if provider == "trading212":
                value = {
                    "api_key": body.api_key or existing.get("api_key", ""),
                    "api_secret": body.api_secret or existing.get("api_secret", ""),
                    "environment": body.environment,
                }
                if not value["api_key"] or not value["api_secret"]:
                    raise HTTPException(422, "broker_keys_required")
                # Changing account or environment starts a new history to avoid mixing account records.
                if existing and value != existing:
                    for table in ("cache", "snapshots", "history", "statement_rows"):
                        db.execute(f"DELETE FROM {table} WHERE user_id=?", (user["id"],))
            else:
                validate_llm_url(body.base_url, config)
                value = {
                    "base_url": body.base_url.rstrip("/"),
                    "api_key": body.api_key
                    or (
                        existing.get("api_key", "")
                        if existing.get("base_url") == body.base_url.rstrip("/")
                        else ""
                    ),
                }
            vault.set(user["id"], provider, value)
            brokers.next_attempt.pop((user["id"], "portfolio"), None)
            brokers.next_attempt.pop((user["id"], "pies"), None)
            brokers.next_attempt.pop((user["id"], "chart_instruments"), None)
            return {"ok": True}

    @app.delete("/api/connections/{provider}")
    async def disconnect(provider: Literal["trading212", "openai"], user=Depends(current_user)):
        async with brokers.locks.setdefault(user["id"], asyncio.Lock()):
            db.execute("DELETE FROM credentials WHERE user_id=? AND provider=?", (user["id"], provider))
            if provider == "trading212":
                for table in ("cache", "snapshots", "history", "statement_rows"):
                    db.execute(f"DELETE FROM {table} WHERE user_id=?", (user["id"],))
            return {"ok": True}

    @app.get("/api/portfolio")
    def portfolio(user=Depends(current_user)):
        uid = user["id"]
        cached = db.cached(uid, "portfolio")
        if cached:
            mappings = {
                row["ticker"]: row["symbol"]
                for row in db.all("SELECT * FROM symbol_mappings WHERE user_id=?", (uid,))
            }
            views = [cached["data"]["positions"], cached["data"].get("ungrouped_positions", [])]
            views.extend(pie["positions"] for pie in cached["data"].get("pies", []))
            for position in [position for view in views for position in view]:
                position["chart_symbol"] = mappings.get(
                    position["ticker"], suggested_symbol(position["ticker"], position.get("currency"))
                )
                position["symbol_confirmed"] = position["ticker"] in mappings
        return {
            "snapshot": cached,
            "status": db.cached(uid, "portfolio_status"),
            "timeline": db.all(
                "SELECT total_value,total_cost,currency,created_at FROM snapshots WHERE user_id=? "
                "ORDER BY id DESC LIMIT 1000",
                (uid,),
            )[::-1],
            "statement": statement_summary(db, uid),
        }

    @app.post("/api/portfolio/sync")
    async def sync_portfolio(user=Depends(current_user)):
        return await brokers.sync(user["id"])

    @app.get("/api/history")
    def history(
        kind: Literal["orders", "dividends", "transactions"] = "orders",
        offset: int = Query(0, ge=0),
        user=Depends(current_user),
    ):
        rows = db.all("SELECT payload FROM history WHERE user_id=? AND kind=?", (user["id"], kind))
        items = [json.loads(row["payload"]) for row in rows]
        items.sort(
            key=lambda item: (
                item.get("fill", {}).get("filledAt") or item.get("dateTime") or item.get("paidOn", "")
            ),
            reverse=True,
        )
        return {
            "items": items[offset : offset + 50],
            "total": len(items),
            "sync": db.cached(user["id"], f"history_{kind}"),
        }

    @app.post("/api/history/sync")
    async def sync_history(
        kind: Literal["orders", "dividends", "transactions"] = "orders",
        cursor: str | None = Query(None, max_length=500),
        user=Depends(current_user),
    ):
        return await brokers.history(user["id"], kind, cursor)

    @app.post("/api/statements")
    async def statement(file: UploadFile, user=Depends(current_user)):
        data = await file.read(10_000_001)
        if len(data) > 10_000_000:
            raise HTTPException(413, "statement_too_large")
        return import_statement(db, user["id"], data)

    @app.delete("/api/statements")
    def clear_statements(user=Depends(current_user)):
        db.execute("DELETE FROM statement_rows WHERE user_id=?", (user["id"],))
        return {"ok": True}

    @app.get("/api/watchlist")
    def watchlist(user=Depends(current_user)):
        return db.all(
            "SELECT id,symbol,name,sector FROM watchlist WHERE user_id=? ORDER BY id DESC", (user["id"],)
        )

    @app.post("/api/watchlist")
    def add_watch(body: Watch, user=Depends(current_user)):
        if db.one("SELECT COUNT(*) AS n FROM watchlist WHERE user_id=?", (user["id"],))["n"] >= 100:
            raise HTTPException(422, "watchlist_full")
        db.execute(
            "INSERT INTO watchlist(user_id,symbol,name,sector) VALUES(?,?,?,?) ON CONFLICT(user_id,symbol) "
            "DO UPDATE SET name=excluded.name,sector=excluded.sector",
            (user["id"], body.symbol.upper(), body.name, body.sector),
        )
        return {"ok": True}

    @app.delete("/api/watchlist/{item_id}")
    def remove_watch(item_id: int, user=Depends(current_user)):
        db.execute("DELETE FROM watchlist WHERE id=? AND user_id=?", (item_id, user["id"]))
        return {"ok": True}

    @app.get("/api/news")
    def get_news(
        q: str = Query("", max_length=120), offset: int = Query(0, ge=0), user=Depends(current_user)
    ):
        query, args = "user_id=?", [user["id"]]
        if q:
            query += " AND (title LIKE ? OR content LIKE ? OR topic LIKE ?)"
            args += [f"%{q}%"] * 3
        return {
            "items": db.all(
                f"SELECT * FROM news WHERE {query} ORDER BY COALESCE(published_at,fetched_at) DESC LIMIT 50 OFFSET ?",
                (*args, offset),
            ),
            "total": db.one(f"SELECT COUNT(*) AS n FROM news WHERE {query}", args)["n"],
            "status": db.cached(user["id"], "news_status"),
        }

    @app.post("/api/news/sync")
    async def sync_news(user=Depends(current_user)):
        return await news.sync(user["id"])

    @app.post("/api/news/{article_id}/fulltext")
    async def news_fulltext(article_id: int, refresh: bool = False, user=Depends(current_user)):
        return await news.full_text(user["id"], article_id, refresh=refresh)

    @app.delete("/api/news")
    def clear_news(user=Depends(current_user)):
        db.execute("DELETE FROM news WHERE user_id=?", (user["id"],))
        return {"ok": True}

    @app.get("/api/markets")
    async def get_markets(user=Depends(current_user)):
        values = await markets.refresh()
        return {**values, "exchanges": await asyncio.to_thread(exchange_status)}

    @app.get("/api/charts")
    async def get_chart(
        symbol: str = Query(max_length=60),
        interval: str = "1d",
        period: str = "3mo",
        extended: bool = False,
        user=Depends(current_user),
    ):
        if "_" in symbol:
            broker_ticker = symbol
            mapping = db.one(
                "SELECT symbol FROM symbol_mappings WHERE user_id=? AND ticker=?", (user["id"], broker_ticker)
            )
            portfolio = db.cached(user["id"], "portfolio")
            position = next(
                (
                    p
                    for p in (portfolio or {}).get("data", {}).get("positions", [])
                    if p["ticker"] == broker_ticker
                ),
                {},
            )
            symbol = (
                mapping["symbol"] if mapping else suggested_symbol(broker_ticker, position.get("currency"))
            )
            if not symbol:
                metadata = await brokers.chart_instrument(user["id"], broker_ticker)
                symbol = suggested_symbol(broker_ticker, metadata=metadata)
            if not symbol:
                raise ProviderError("chart_symbol_required")
        symbol = symbol.strip().upper()
        return await charts.fetch(symbol, interval, period, extended=extended)

    @app.put("/api/charts/mapping")
    def set_mapping(body: Mapping, user=Depends(current_user)):
        db.execute(
            "INSERT INTO symbol_mappings VALUES(?,?,?) ON CONFLICT(user_id,ticker) DO UPDATE SET symbol=excluded.symbol",
            (user["id"], body.ticker, body.symbol.upper()),
        )
        return {"ok": True}

    @app.get("/api/ai/models")
    async def get_models(provider: Literal["openai", "codex"], user=Depends(current_user)):
        return await ai.models(user["id"], provider)

    @app.get("/api/ai/prompts")
    def prompts(user=Depends(current_user)):
        return defaults(db.settings(user["id"])["language"])

    @app.get("/api/ai/analyses")
    def analyses(before: int | None = Query(None, ge=1), summary: bool = False, user=Depends(current_user)):
        if summary:
            return db.all(
                "SELECT id,provider,model,style,created_at,updated_at,json_extract(evidence,'$.reasoning_effort') AS reasoning_effort,"
                "json_extract(evidence,'$.holding_horizon') AS holding_horizon FROM analyses WHERE user_id=? AND (? IS NULL OR id<?) ORDER BY id DESC LIMIT 20",
                (user["id"], before, before),
            )
        rows = db.all(
            "SELECT * FROM analyses WHERE user_id=? AND (? IS NULL OR id<?) ORDER BY id DESC LIMIT 20",
            (user["id"], before, before),
        )
        for row in rows:
            row["evidence"] = json.loads(row["evidence"])
            row["reasoning_effort"] = row["evidence"].get("reasoning_effort", "auto")
            row["holding_horizon"] = row["evidence"].get("holding_horizon")
        return rows

    @app.get("/api/ai/storage")
    def analysis_storage(user=Depends(current_user)):
        return analysis_jobs.reports.storage(user["id"])

    @app.post("/api/ai/analyze", status_code=202)
    async def analyze(user=Depends(current_user)):
        return analysis_jobs.start(user["id"])

    @app.get("/api/ai/analyses/{analysis_id}")
    def analysis(analysis_id: int, user=Depends(current_user)):
        return analysis_jobs.followups.report(user["id"], analysis_id)

    @app.delete("/api/ai/analyses/{analysis_id}")
    def delete_analysis(analysis_id: int, user=Depends(current_user)):
        analysis_jobs.reports.delete(user["id"], analysis_id)
        return {"ok": True}

    @app.get("/api/ai/analyses/{analysis_id}/followups")
    def followups(analysis_id: int, before: int | None = Query(None, ge=1), user=Depends(current_user)):
        return analysis_jobs.followups.history(user["id"], analysis_id, before)

    @app.get("/api/ai/analyses/{analysis_id}/followups/{turn_id}/evidence")
    def followup_evidence(analysis_id: int, turn_id: int, user=Depends(current_user)):
        return analysis_jobs.followups.evidence(user["id"], analysis_id, turn_id)

    @app.post("/api/ai/analyses/{analysis_id}/followups", status_code=202)
    async def ask_followup(analysis_id: int, body: Followup, user=Depends(current_user)):
        return analysis_jobs.start(user["id"], body.model_dump() | {"analysis_id": analysis_id})

    @app.get("/api/ai/jobs/current")
    def current_analysis_job(user=Depends(current_user)):
        return analysis_jobs.current(user["id"])

    @app.get("/api/ai/jobs/{job_id}")
    def analysis_job(job_id: str, user=Depends(current_user)):
        return analysis_jobs.get(user["id"], job_id)

    @app.post("/api/ai/jobs/{job_id}/cancel")
    async def cancel_analysis_job(job_id: str, user=Depends(current_user)):
        return analysis_jobs.cancel(user["id"], job_id)

    @app.post("/api/codex/login")
    def codex_login(user=Depends(admin)):
        return {"job_id": runtime.login(user["id"])}

    @app.get("/api/codex/status")
    async def codex_status(user=Depends(current_user)):
        try:
            return {
                **await asyncio.to_thread(runtime.login_status, user["id"]),
                "shared": True,
                "can_manage": user["role"] == "admin",
            }
        except ProviderError as exc:
            return {
                "logged_in": False,
                "error": exc.code,
                "shared": True,
                "can_manage": user["role"] == "admin",
            }

    @app.post("/api/codex/logout")
    async def codex_logout(user=Depends(admin)):
        if any(job["kind"] == "login" and job["status"] == "running" for job in runtime.jobs.values()):
            raise HTTPException(409, "login_in_progress")
        code, _, _ = await asyncio.to_thread(runtime.run, user["id"], runtime.codex() + ["logout"])
        if code:
            raise ProviderError("codex_logout_failed")
        runtime.clear_model_cache()
        return {"ok": True}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, user=Depends(current_user)):
        result = runtime.job(user["id"], job_id)
        if "output" in result:
            result["output"] = vault.redact(user["id"], result["output"])
        return result

    @app.get("/api/admin/users")
    def users(user=Depends(admin)):
        return db.all("SELECT id,username,role,active,created_at FROM users ORDER BY id")

    @app.put("/api/admin/users/{uid}")
    def edit_user(uid: int, body: AdminEdit, user=Depends(admin)):
        if body.password and len(body.password) < 10:
            raise HTTPException(422, "password_too_short")
        try:
            with db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                target = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
                if not target:
                    raise HTTPException(404, "user_not_found")
                removing_admin = (
                    target["role"] == "admin"
                    and target["active"]
                    and (body.role != "admin" or not body.active)
                )
                if (
                    removing_admin
                    and conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[
                        0
                    ]
                    <= 1
                ):
                    raise HTTPException(409, "last_admin_required")
                conn.execute(
                    "UPDATE users SET username=?,role=?,active=? WHERE id=?",
                    (body.username, body.role, body.active, uid),
                )
                if body.password:
                    conn.execute(
                        "UPDATE users SET password_hash=? WHERE id=?", (hasher.hash(body.password), uid)
                    )
                if body.password or not body.active or body.role != target["role"]:
                    conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "username_taken") from None
        return {"ok": True}

    @app.get("/api/admin/runtime")
    async def runtime_status(user=Depends(admin)):
        try:
            code, version, _ = await asyncio.to_thread(
                runtime.run, user["id"], runtime.codex() + ["--version"]
            )
        except ProviderError:
            version = "not_installed"
        return {
            "codex": version.strip(),
            "python": sys.version.split()[0],
            "peat": __version__,
            "calendar": importlib.metadata.version("exchange-calendars"),
            "calendar_restart_pending": (
                (config.runtime / "calendar-active.json").exists()
                and json.loads((config.runtime / "calendar-active.json").read_text())["path"] not in sys.path
            ),
            "console_enabled": config.console_enabled,
        }

    @app.post("/api/admin/runtime/codex")
    def update_codex(body: Version, user=Depends(admin)):
        if any(job["kind"] == "update" and job["status"] == "running" for job in runtime.jobs.values()):
            raise HTTPException(409, "update_running")
        return {"job_id": runtime.update_codex(user["id"], body.version)}

    @app.post("/api/admin/runtime/calendar")
    def update_calendar(body: Version, user=Depends(admin)):
        if any(job["kind"] == "update" and job["status"] == "running" for job in runtime.jobs.values()):
            raise HTTPException(409, "update_running")
        return {"job_id": runtime.update_calendar(user["id"], body.version)}

    @app.get("/api/admin/runtime/releases")
    async def runtime_releases(user=Depends(admin)):
        result = {}
        for name, url in (
            ("codex", "https://registry.npmjs.org/@openai/codex/latest"),
            ("calendar", "https://pypi.org/pypi/exchange-calendars/json"),
        ):
            try:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                result[name] = data.get("version") or data["info"]["version"]
            except (httpx.HTTPError, KeyError, ValueError):
                result[name] = None
        return result

    @app.post("/api/admin/console")
    def console(body: Command, user=Depends(admin)):
        if not config.console_enabled:
            raise HTTPException(403, "console_disabled")
        args = (
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); " + body.command,
            ]
            if os.name == "nt"
            else ["/bin/bash", "-lc", body.command]
        )
        return {"job_id": runtime.start_job(user["id"], "console", args, 60)}

    dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}")
        def frontend(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "not_found")
            candidate = (dist / path).resolve()
            if candidate.is_relative_to(dist.resolve()) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app
