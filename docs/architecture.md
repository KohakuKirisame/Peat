# Architecture and data contracts

```text
Browser (React, TypeScript)
          │ same-origin session cookie / JSON API
FastAPI ──┼── SQLite: users, settings, encrypted API credentials
          ├── Trading212 adapter (GET allowlist only)
          ├── Markets + Charts: Treasury XML / Yahoo chart feed
          ├── News: Google RSS → plain text → per-user retention
          ├── Intelligence: persisted background tasks → OpenAI API / shared Codex login
          └── Runtime: device-login jobs, dependency installs, admin console
```

## Persistence

`Database` enables SQLite WAL and foreign keys. Bootstrap registration uses a write transaction so exactly one first account becomes administrator. Users own credentials, watchlists, news, statement rows, histories, portfolio snapshots and saved analyses. Public market data is shared under cache owner `0`.

API keys are encrypted as one provider-specific JSON object per user. The generated key is independent of the database. The API returns configured flags, base URLs and environment choices; it never returns stored keys. User deactivation/password changes/role changes revoke sessions. At least one active administrator must remain.

## Broker contract

`Broker.snapshot()` is the extension point for future brokers. `Trading212.get()` accepts a fixed GET path allowlist, rejects absolute pagination URLs and never follows redirects carrying authentication. Histories retain the provider payload and stable fill/reference IDs. Pagination state is kept per history kind. Rate-limit responses carry retry hints; failed portfolio refreshes retain the previous snapshot and publish a failure status.

Account metrics come from `/equity/account/summary`. Position prices are in `instrument.currency`; position wallet values come from `walletImpact`, retaining its currency. No position cost/value is reconstructed by multiplying mismatched currencies. Realized history fills use `realisedProfitLoss`, while current account summary uses `realizedProfitLoss` as documented by the provider.

Pie grouping reads only `GET /equity/pies` and numeric-ID `GET /equity/pies/{id}`. Names come from `settings.name`, membership from `ownedQuantity`, and displayed Pie financial results from `priceAvgValue` / `priceAvgResult`. Pie data is cached for five minutes and detail calls are spaced by 5.1 seconds. Account data is cached before these slower requests. Optional Pie failures do not turn an account sync into a failure.

Canonical `positions` remains the complete account-wide list for totals and news discovery. `pies` and `ungrouped_positions` are alternative presentation views. Grouping checks aggregate assigned quantities against `quantityInPies` and total quantities, including a small floating-point tolerance. Unmatched snapshots fall back to canonical positions. For mixed ownership, only market value can be split proportionally; outside-Pie cost and P&L remain null without a separate cost basis. Saved chart symbol mappings are applied to every view. AI prompts explicitly identify the grouped fields as alternative views to avoid double counting.

CSV parsing accepts UTF-8 English Trading 212 exports with Action, Time, Total and Currency (Total). Imports are transactional, content-deduplicated, bounded to 10 MB / 50,000 rows, and retain the original row data. Deposit/withdrawal, dividend and Result sums use Decimal and remain separate by currency and source. Entirely identical rows without distinguishing broker IDs cannot be distinguished from duplicates.

## Prices and clocks

Yahoo OHLC data retains provider timestamps, currency, timezone and missing-bar gaps. The UI does not interpolate missing candles. Minute ranges are bounded to the provider's supported retention; daily/weekly/monthly ranges extend further. Users can confirm and persist symbol mappings per instrument. Quote cache lifetime is 5 minutes; chart cache lifetime is 60 seconds.

Intraday requests can include pre/post-market bars using `includePrePost`. Session labels follow the provider's dated trading periods, including holiday/early-close schedules, and cache keys separate regular/extended series. Each candle records its interval end, session date and completion status. Explicit dated windows cannot expose today's metadata quote as a historical price. Splits/dividends remain attached to price history. Public research tools bypass the local candle cache; failed refreshes retain cached values only with a stale marker.

Chart symbols support country-tagged broker IDs and legacy venue-letter IDs such as `AIRp_EQ`. For unresolved IDs, the broker metadata fallback joins `workingScheduleId` to exchange working schedules and combines the instrument's `shortName` with the listing suffix. Metadata is cached per account for 24 hours, with retries throttled to one minute. Currency alone does not select a US venue. Explicit user mappings override automatic resolution. Chart requests clear obsolete data when their key changes, and selecting another holding remounts chart state.

Market pulse plots use dated `observations` directly so skipped null quotes cannot shift timestamps. Hover/touch selects the nearest plotted observation; arrow keys, Home and End provide the same inspection. Tooltips display up to four decimal places and the source unit. Treasury dates are calendar dates without timezone conversion; commodity timestamps use the provider's exchange timezone. Older cache entries with only an undated series retain a static curve until refreshed.

Treasury data is fetched from the official daily yield XML feed. Time-series observations include dates. Exchange calendars account for scheduled holidays, DST and breaks. Unknown/out-of-range calendars return an explicit unknown state. Regular-session status does not imply live executable prices.

## News and AI

News topics are derived from held company names, watchlist names and industry keywords. Entries are deduplicated by URL and stripped of HTML. Retention applies both count and age limits per user. Article bodies are fetched on expansion or when selected for research and cached in a per-article table with cascading retention. Google News resolution handles legacy encoded links, redirects and framed RPC responses. Extraction combines main-article JSON-LD, Trafilatura's standard/recall fallbacks and explicit article paragraphs. If needed, it follows up to two declared AMP/canonical alternatives. Access declarations are matched to the main article, avoiding false subscription detection from related stories.

Every redirect is revalidated and DNS-pinned to a public address, with no browser credentials. Response size is capped at 4 MB and per-article acquisition at 60 seconds. Temporary transport and server failures get up to three attempts with backoff. Failed cache entries expire sooner than successful text and can be manually retried, with a five-second retry throttle. Subscription/blocked pages retain the resolved original-article link and a specific reason.

Analysis uses a securities-only projection of the portfolio: account total value, cash, reserved cash and interest-bearing deposits are omitted, and weights use securities market value. The raw account cache and funds UI retain these balances.

News selection scores headlines/excerpts against held companies, security weights, watchlist companies and industry terms. Publication age applies a multiplicative decay tuned to the holding horizon. Publisher `datePublished` and `dateModified` are stored separately; fetch time never substitutes for an unknown publication date. Stories are labelled recent, background or undated, and future publication timestamps are excluded. Coverage, source diversity and duplicate controls select up to 30 stories. Body acquisition has a 90-second budget, three concurrent downloads and a shared 30,000-character text budget. Selection provenance remains archived.

`ResearchContext` refreshes core portfolio quantities, macro data and news, then fetches fresh quotes and price windows. Pie detail calls are excluded from this latency-sensitive refresh. Up to 60 instruments are prepared with four concurrent workers and a 75-second acquisition budget; omitted coverage is explicit, and the model can query additional symbols. Histories share roughly 1,600 compact bars. News price alignment uses completed bars ending before publication and bars starting after it; a straddling candle cannot supply a pre-event close. Daily observations are labelled by session date. Out-of-window and unknown-date cases remain unmatched, with no substitution of the latest bars or automatic causal claim.

Default prompts request explicit OPEN/ADD/REDUCE/CLOSE/HOLD/WATCH plans with securities-based target weights, reference sizes and triggers, using concise direct wording. Users can replace the shared prompt and each style prompt. All inputs, resolved prompts, provider, model, effort and output are archived together. React Markdown plus GFM renders brief structure while raw HTML and remote images remain disabled.

`holding_horizon` is an independent setting (`ultra_short`, `short`, `medium_long`), defaulting to `medium_long` when upgrading old settings. `ai_horizon_prompts` stores optional overrides for each horizon. Prompt resolution combines the base, selected risk style and selected holding-horizon text for both providers. Jobs snapshot the choice; report evidence stores the horizon and resolved prompt. Existing reports without the field return null and receive no inferred horizon label.

OpenAI-compatible providers receive Chat Completions requests and optional public research function tools. A bounded tool loop records calls/results and can query fresh quotes, dated OHLCV, news search and article text. Explicitly unsupported tools fall back to refreshed inputs; reasoning effort is retained. Codex models/efforts come from app-server `model/list`. Codex uses shared administrator authentication, isolated per-user workspaces, live hosted web search and only the bundled `peat_research` MCP server. Shell, file-edit, host plugin and other general tools remain disabled. MCP uses the same public tool implementation and does not read the account database or credentials. Search and tool activity is archived; credentials never enter prompts.

`POST /api/ai/analyze` returns a job with HTTP 202 immediately. SQLite `analysis_jobs` stores owner, captured settings, phase, terminal status and report ID, with a unique active-job constraint per user. A process-level asyncio task runs independently of the HTTP connection. The browser polls `/api/ai/jobs/current` from a provider above page navigation; individual job lookup and cancellation are owner-scoped. Model inference has no application timeout. Cancellation closes the OpenAI request or signals a thread watcher to terminate the Codex process tree and wait for cleanup. Only completed output is stored as a report. Shutdown and restart mark unfinished jobs interrupted, without automatically rerunning a provider call.

Report discussions use `analysis_followups`, linked to the original report and an `analysis_jobs` entry with kind `followup`. Schema version 4 adds the job-kind field without rewriting existing reports. `POST /api/ai/analyses/{id}/followups` atomically stores the question and queues a task; a report-scoped request key makes retries idempotent. The shared active-job constraint covers research and follow-ups. Ownership is checked for report access, conversation pages and cancellation.

`Intelligence.prepare/complete` supplies a common provider path for research and replies. Follow-ups refresh data by default and distinguish the original view from `live_evidence`; historical-review mode disables refresh and external research tools. Original strategy/horizon prompts and successful conversation pairs stay available, with compact historical evidence in live mode. Every reply archives its fresh inputs, resolved prompt, included turn IDs and tool activity. Failed/cancelled questions do not enter model history. Complete pairs retain an 80,000-character/100-turn budget. The reply and successful job state are committed together; the original report body/evidence is immutable.

Schema version 5 adds publisher dates and report activity timestamps. Report retention is owner-scoped, unlimited by default, and ordered by last research activity with active discussions protected. Deletion cascades through follow-up evidence; job metadata becomes a minimal deleted tombstone so an older completion banner does not resurface. A persistent counter prevents deleted report IDs from being reused. Archive summaries paginate without transferring every report's full evidence.

The browser reuses global background-task polling and reloads the discussion on job-state changes. Conversations paginate in groups of 50, use safe Markdown rendering, and allow per-reply model/effort controls. View reply focuses the correct report even if the user is reading another brief; completion itself does not change their selection.

## Operations

The background loop updates configured portfolios and news at each user's interval. Market data is shared and cached. Manual refreshes use the same locks and throttles. Long-running AI calls run asynchronously; subprocess work and blocking connection setup are delegated to threads. Runtime maintenance jobs keep bounded output in memory and expire completed job metadata. Research job state is persisted separately.

The app is single-process, suited to a local or small self-hosted workspace. Administrators have service-level trust because the console can run local commands. Normal users cannot reach administrative routes or other users' jobs.

Interface zoom uses CSS zoom at 80–200%, with per-account browser-local storage. Media-query width breakpoints and viewport-sized elements are adjusted to the effective layout width/height so zoomed desktop pages can enter the existing narrow layouts. Top-bar presets and the Appearance slider control the same state; changing account restores that account's local preference. Zoom does not enter server research settings or prompts.

## Extending

- Add brokers by implementing `Broker`, normalizing money with explicit currencies and exposing only authorized read operations.
- Add market/news providers behind their service classes, preserving timestamps, provenance and error states.
- Add LLM providers inside `Intelligence`; keep model/effort selection and immutable evidence records.
- Keep credentials in `Vault` and runtime files under the data directory.

## 中文要点

SQLite 是本地事实存储；外部数据保留来源、时间与币种。Broker 抽象负责未来平台扩展，Trading212 适配器仅允许明确列出的 GET 路径。当前持仓成本、净入金、已实现收益按各自来源分开处理。

新闻保存 RSS 摘要并支持按需读取正文；研究按持仓与行业相关性选材，记录关联对象和正文来源。现金及计息 deposit 仅保留在账户资金中，简报使用证券持仓市值作为仓位基数。AI 分析保存完整输入证据和当时使用的提示词。用户选择的思考强度会传给平台，失败时不会自动切换成其他档位。Codex 模型能力来自运行实例的模型列表。

研究任务入库后在后台运行，切换页面或刷新不会中断；模型生成不限时，用户可手动中止。服务重启后未完成任务标记为中断。新闻正文结合结构化文章、可读页面与 AMP 回退，并提供重试和具体失败原因。

持仓、API 凭据、报告和任务按用户隔离；Codex 登录由管理员统一管理，全站共享，研究工作目录仍按用户独立。升级时通过私有目录标记沿用已有管理员登录。管理员控制台属于实例运维权限。Git 与容器构建都排除运行数据。应用使用单进程轮询与进程内任务管理。
