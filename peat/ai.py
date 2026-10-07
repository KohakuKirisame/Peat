import asyncio
import json
import sys
from pathlib import Path

import httpx

from .brokers import ProviderError
from .config import Config
from .db import Database, now
from .market_tools import MarketTools, function_tools
from .portfolio_context import investment_context
from .prompts import research_rules, resolve
from .relevance import select_news
from .reports import Reports
from .runtime import Runtime
from .security import Vault, validate_llm_url
from .temporal import news_timing


class Intelligence:
    def __init__(
        self,
        db: Database,
        vault: Vault,
        client: httpx.AsyncClient,
        runtime: Runtime,
        config: Config,
        news=None,
        live=None,
    ):
        self.db, self.vault, self.client, self.runtime, self.config = db, vault, client, runtime, config
        self.locks = {}
        self.news = news
        self.live = live
        self.tools = MarketTools(client)

    def openai_config(self, uid):
        credentials = self.vault.get(uid, "openai")
        if not credentials.get("base_url"):
            raise ProviderError("ai_not_connected")
        credentials["connect_ip"] = validate_llm_url(credentials["base_url"], self.config)
        return credentials

    async def request(self, credentials, method, path, **kwargs):
        url = httpx.URL(credentials["base_url"].rstrip("/") + path)
        headers = {"Authorization": f"Bearer {credentials.get('api_key', '')}"}
        extensions = {}
        if credentials.get("connect_ip"):
            headers["Host"] = url.netloc.decode()
            extensions["sni_hostname"] = url.host
            url = url.copy_with(host=credentials["connect_ip"])
        return await self.client.request(
            method, url, headers=headers, extensions=extensions, follow_redirects=False, **kwargs
        )

    async def models(self, uid, provider):
        if provider == "codex":
            models = await asyncio.to_thread(self.runtime.models, uid)
        else:
            credentials = await asyncio.to_thread(self.openai_config, uid)
            try:
                response = await self.request(credentials, "GET", "/models")
                response.raise_for_status()
                models = [
                    {"id": model["id"], "name": model["id"], "efforts": None}
                    for model in response.json()["data"]
                ]
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                raise ProviderError("models_unavailable") from None
        self.db.put_cache(uid, f"models_{provider}", models)
        return models

    def evidence(self, uid, selection=None):
        selection = selection or select_news(self.db, uid)
        portfolio = investment_context(selection["portfolio"])
        selected = {article["id"]: article for article in selection["items"]}
        placeholders = ",".join("?" for _ in selected)
        news = (
            self.db.all(
                "SELECT n.id,n.fingerprint,n.title,n.content,n.source,n.url,n.topic,n.published_at,b.content AS article_content,"
                "b.source_url,b.fetched_at AS article_fetched_at,b.published_at AS source_published_at,b.modified_at AS source_modified_at FROM news n LEFT JOIN news_bodies b "
                "ON b.news_id=n.id AND b.status='ready' WHERE n.user_id=? "
                f"AND n.id IN ({placeholders})",
                (uid, *selected),
            )
            if selected
            else []
        )
        current = {
            article["id"]: article
            for article in news
            if article["fingerprint"] == selected[article["id"]]["fingerprint"]
        }
        # News cleanup in another page must not replace a task's selected story with a reused row ID.
        news = [
            current.get(article_id)
            or {**article, "article_content": None, "source_url": None, "article_fetched_at": None}
            for article_id, article in selected.items()
        ]
        news.sort(key=lambda article: selected[article["id"]]["relevance_score"], reverse=True)
        full_bodies = sum(bool(article.get("article_content")) for article in news)
        body_limit = min(6000, 30000 // max(1, full_bodies))
        for article in news:
            article.pop("fingerprint", None)
            article["relevance_score"] = selected[article["id"]]["relevance_score"]
            article["related_entities"] = selected[article["id"]]["related_entities"]
            body = article.pop("article_content")
            if body:
                limit = body_limit
                article["content"] = body[:limit]
                article["content_kind"] = "article_excerpt" if len(body) > limit else "article_body"
                article["url"] = article["source_url"] or article["url"]
            else:
                article["content"] = article["content"][:1000]
                article["content_kind"] = "rss_excerpt"
        market = self.db.cached(0, "markets")
        return {
            "generated_at": now(),
            "portfolio": portfolio,
            "markets": market,
            "watchlist": selection["watchlist"],
            "news": news,
            "news_selection": selection["selection"],
        }

    async def prepare(self, uid, settings):
        provider, model, effort = settings["ai_provider"], settings["ai_model"], settings["reasoning_effort"]
        credentials = None
        if not model:
            raise ProviderError("model_required")
        if provider == "codex":
            cached = self.db.cached(uid, "models_codex")
            models = cached["data"] if cached else await self.models(uid, "codex")
            chosen = next((item for item in models if item["id"] == model), None)
            if not chosen:
                raise ProviderError("model_unavailable")
            if effort != "auto" and effort not in chosen["efforts"]:
                raise ProviderError("reasoning_not_supported")
        if provider == "openai":
            credentials = await asyncio.to_thread(self.openai_config, uid)
        return credentials

    async def collect(self, uid, settings, progress=None, focus=None):
        live = self.live is not None and settings.get("ai_live_data", True)
        refresh = await self.live.refresh(uid, progress) if live else {}
        selection = select_news(self.db, uid, horizon=settings.get("holding_horizon") or "medium_long")
        if self.news:
            if progress:
                progress("fetching_news")
            await self.news.enrich_for_analysis(uid, selection["items"])
        evidence = self.evidence(uid, selection)
        evidence["holding_horizon"] = settings.get("holding_horizon")
        for article in evidence["news"]:
            article.update(news_timing(article, settings.get("holding_horizon") or "medium_long"))
        if live:
            await self.live.enrich(uid, settings, evidence, refresh, progress, focus)
        else:
            evidence["freshness"] = {"mode": "saved_data", "collected_at": now()}
        evidence["news_selection"].update(
            {
                "recent_count": sum(item.get("timing_class") == "recent" for item in evidence["news"]),
                "background_count": sum(
                    item.get("timing_class") == "background" for item in evidence["news"]
                ),
                "undated_count": sum(item.get("timing_class") == "undated" for item in evidence["news"]),
            }
        )
        return evidence

    async def api_complete(self, uid, settings, system, messages, credentials, enabled, trace, progress):
        conversation = [{"role": "system", "content": system}, *messages]
        calls = trace.setdefault("market_calls", [])
        for round_index in range(17):
            body = {"model": settings["ai_model"], "messages": conversation}
            if settings["reasoning_effort"] != "auto":
                body["reasoning_effort"] = settings["reasoning_effort"]
            if enabled and round_index < 16 and len(calls) < 40:
                body["tools"] = function_tools()
            try:
                response = await self.request(
                    credentials, "POST", "/chat/completions", json=body, timeout=None
                )
                if response.status_code in (400, 422) and "tools" in body:
                    try:
                        error = response.json().get("error", {})
                        param = str(error.get("param", ""))
                        message = str(error.get("message", "")).lower()
                        unsupported = param in {"tools", "tool_choice", "parallel_tool_calls"} or (
                            "tool" in message
                            and any(
                                term in message
                                for term in (
                                    "not support",
                                    "unsupported",
                                    "unknown parameter",
                                    "unrecognized",
                                )
                            )
                        )
                    except (ValueError, AttributeError):
                        unsupported = False
                    if unsupported:
                        enabled = False
                        trace["market_tools_status"] = "provider_unsupported"
                        notice = "\nTool availability update: this endpoint rejected research tools. Use the refreshed supplied evidence and its timestamps. Do not claim additional lookups; keep unverified facts conditional."
                        trace["tool_availability_notice"] = notice
                        conversation[0] = {"role": "system", "content": system + notice}
                        del body["tools"]
                        response = await self.request(
                            credentials, "POST", "/chat/completions", json=body, timeout=None
                        )
                if response.status_code in (400, 422):
                    raise ProviderError("model_or_reasoning_rejected")
                response.raise_for_status()
                message = response.json()["choices"][0]["message"]
                requested = message.get("tool_calls") or []
                if not requested:
                    return message.get("content")
                if not enabled or round_index == 16 or len(requested) > 128:
                    raise ProviderError("research_tool_limit")
                if progress:
                    progress("researching")
                conversation.append(
                    {"role": "assistant", "content": message.get("content"), "tool_calls": requested}
                )
                for call in requested:
                    name = call["function"]["name"]
                    try:
                        arguments = json.loads(call["function"]["arguments"])
                    except (ValueError, TypeError):
                        arguments = None
                    result = (
                        await self.tools.call(name, arguments)
                        if len(calls) < 40
                        else {"error": "research_tool_limit"}
                    )
                    calls.append(
                        {"tool": name, "arguments": arguments, "result": result, "retrieved_at": now()}
                    )
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
                raise ProviderError("ai_request_failed") from None
        raise ProviderError("research_tool_limit")

    @staticmethod
    def record_codex_activity(event, trace):
        if event.get("type") != "item.completed":
            return
        item = event.get("item", {})
        kind = item.get("type")
        if kind in {"web_search", "web_search_call"}:
            action = item.get("action") or {}
            if not isinstance(action, dict):
                action = {}
            trace.setdefault("web_searches", []).append(
                {
                    "query": item.get("query") or action.get("query"),
                    "queries": item.get("queries") or action.get("queries"),
                    "url": item.get("url") or action.get("url"),
                    "status": item.get("status", "completed"),
                }
            )
        elif kind == "mcp_tool_call" and item.get("server") == "peat_research":
            result = item.get("result") or {}
            parsed = (
                (result.get("structuredContent") or result.get("structured_content"))
                if isinstance(result, dict)
                else None
            )
            if parsed is None and isinstance(result, dict):
                for part in result.get("content", []):
                    if part.get("type") == "text":
                        try:
                            parsed = json.loads(part["text"])
                            break
                        except (ValueError, KeyError):
                            pass
            trace.setdefault("market_calls", []).append(
                {
                    "tool": item.get("tool"),
                    "arguments": item.get("arguments"),
                    "result": parsed,
                    "status": item.get("status"),
                    "error": bool(item.get("error")),
                }
            )

    async def complete(self, uid, settings, system, messages, credentials=None, *, trace=None, progress=None):
        provider, model, effort = settings["ai_provider"], settings["ai_model"], settings["reasoning_effort"]
        trace = trace if trace is not None else {}
        live = settings.get("ai_live_data", True)
        enabled = live and settings.get("ai_market_tools", True)
        search = live and provider == "codex" and settings.get("ai_web_search", True)
        trace.update(web_search_enabled=search, market_tools_enabled=enabled)
        if provider == "openai":
            content = await self.api_complete(
                uid, settings, system, messages, credentials, enabled, trace, progress
            )
        else:
            # Shared login; only the bundled public research server is configured for this run.
            args = self.runtime.codex() + [
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--color",
                "never",
                "--json",
                "-c",
                'cli_auth_credentials_store="file"',
                "-c",
                "features.shell_tool=false",
                "-c",
                "features.unified_exec=false",
                "-c",
                "features.apply_patch_freeform=false",
                "-c",
                f'web_search="{"live" if search else "disabled"}"',
                "-m",
                model,
            ]
            for feature in (
                "apps",
                "plugins",
                "remote_plugin",
                "hooks",
                "browser_use",
                "browser_use_external",
                "browser_use_full_cdp_access",
                "computer_use",
                "image_generation",
                "view_image",
                "in_app_browser",
                "multi_agent",
                "multi_agent_v2",
                "code_mode_host",
                "goals",
                "skill_search",
                "workspace_dependencies",
                "tool_suggest",
            ):
                args += ["-c", f"features.{feature}=false"]
            args += ["-c", "features.skip_host_skill_discovery=true"]
            if effort != "auto":
                args += ["-c", f'model_reasoning_effort="{effort}"']
            if enabled:
                config = {
                    "command": sys.executable,
                    "args": [str(Path(__file__).resolve().parent / "market_mcp.py")],
                    "enabled_tools": [item["function"]["name"] for item in function_tools()],
                    "default_tools_approval_mode": "approve",
                    "startup_timeout_sec": 20,
                    "tool_timeout_sec": 70,
                }
                for key, value in config.items():
                    args += ["-c", f"mcp_servers.peat_research.{key}={json.dumps(value)}"]
            code, stdout, stderr = await self.runtime.run_cancellable(
                uid,
                args + ["-"],
                system + "\n\nConversation messages (in order):\n" + json.dumps(messages, ensure_ascii=False),
            )
            if code:
                raise ProviderError("codex_analysis_failed")
            texts = []
            for line in stdout.splitlines():
                try:
                    event = json.loads(line)
                    self.record_codex_activity(event, trace)
                    if (
                        event.get("type") == "item.completed"
                        and event.get("item", {}).get("type") == "agent_message"
                    ):
                        texts.append(event["item"]["text"])
                except (ValueError, KeyError):
                    pass
            content = "\n\n".join(texts)
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("ai_empty_response")
        return content[:60000]

    async def analyze(self, uid, *, settings=None, progress=None):
        lock = self.locks.setdefault(uid, asyncio.Lock())
        if lock.locked():
            raise ProviderError("analysis_running")
        async with lock:
            settings = settings or self.db.settings(uid)
            provider, model, effort = (
                settings["ai_provider"],
                settings["ai_model"],
                settings["reasoning_effort"],
            )
            credentials = await self.prepare(uid, settings)
            evidence = await self.collect(uid, settings, progress)
            evidence["holding_horizon"] = settings.get("holding_horizon", "medium_long")
            if not evidence["news"] and not evidence["portfolio"]:
                raise ProviderError("analysis_needs_evidence")
            used_prompts = resolve(settings)
            system = (
                used_prompts["base"]
                + "\n\n"
                + used_prompts["style"]
                + "\n\n"
                + used_prompts["horizon"]
                + "\nResponse language: "
                + ("Simplified Chinese." if settings["language"] == "zh" else "English.")
                + "\nCount holdings once using the account-wide positions list. The pies and ungrouped_positions "
                "fields are alternative allocation views of those holdings. Pie figures carry their own timestamps. "
                "Portfolio allocation uses securities market value. Exclude personal cash/deposits from the brief "
                "and never treat them as idle capital or proposed funding. "
                "\n" + research_rules(settings)
            )
            payload = json.dumps(evidence, ensure_ascii=False)
            if progress:
                progress("generating")
            trace = {}
            content = await self.complete(
                uid,
                settings,
                system,
                [{"role": "user", "content": payload}],
                credentials,
                trace=trace,
                progress=progress,
            )
            evidence["research_activity"] = trace
            evidence["system_prompt"] = system + trace.get("tool_availability_notice", "")
            evidence["completed_at"] = now()
            evidence["reasoning_effort"] = effort
            evidence["prompts"] = used_prompts
            created = now()
            aid = Reports(self.db).create(
                uid, provider, model, settings["style"], content[:60000], evidence, created
            )
            return {
                "id": aid,
                "provider": provider,
                "model": model,
                "style": settings["style"],
                "content": content[:60000],
                "reasoning_effort": effort,
                "holding_horizon": evidence["holding_horizon"],
                "evidence": evidence,
                "created_at": created,
            }
