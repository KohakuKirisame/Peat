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

Chart symbols support country-tagged broker IDs and legacy venue-letter IDs such as `AIRp_EQ`. For unresolved IDs, the broker metadata fallback joins `workingScheduleId` to exchange working schedules and combines the instrument's `shortName` with the listing suffix. Metadata is cached per account for 24 hours, with retries throttled to one minute. Currency alone does not select a US venue. Explicit user mappings override automatic resolution. Chart requests clear obsolete data when their key changes, and selecting another holding remounts chart state.

Market pulse plots use dated `observations` directly so skipped null quotes cannot shift timestamps. Hover/touch selects the nearest plotted observation; arrow keys, Home and End provide the same inspection. Tooltips display up to four decimal places and the source unit. Treasury dates are calendar dates without timezone conversion; commodity timestamps use the provider's exchange timezone. Older cache entries with only an undated series retain a static curve until refreshed.

Treasury data is fetched from the official daily yield XML feed. Time-series observations include dates. Exchange calendars account for scheduled holidays, DST and breaks. Unknown/out-of-range calendars return an explicit unknown state. Regular-session status does not imply live executable prices.

## News and AI

News topics are derived from held company names, watchlist names and industry keywords. Entries are deduplicated by URL and stripped of HTML. Retention applies both count and age limits per user. Article bodies are fetched on expansion or when selected for research and cached in a per-article table with cascading retention. Google News resolution handles legacy encoded links, redirects and framed RPC responses. Extraction combines main-article JSON-LD, Trafilatura's standard/recall fallbacks and explicit article paragraphs. If needed, it follows up to two declared AMP/canonical alternatives. Access declarations are matched to the main article, avoiding false subscription detection from related stories.

Every redirect is revalidated and DNS-pinned to a public address, with no browser credentials. Response size is capped at 4 MB and per-article acquisition at 60 seconds. Temporary transport and server failures get up to three attempts with backoff. Failed cache entries expire sooner than successful text and can be manually retried, with a five-second retry throttle. Subscription/blocked pages retain the resolved original-article link and a specific reason.

Analysis uses a securities-only projection of the portfolio: account total value, cash, reserved cash and interest-bearing deposits are omitted, and weights use securities market value. The raw account cache and funds UI retain these balances.

News selection scores every cached headline/excerpt against held companies, security weights, watchlist companies and configured industry terms. Recency is a secondary signal. Coverage is reserved for relevant holdings/industries before filling up to 30 slots; repeated headlines are deduplicated and source diversity is considered. Selected stories enter body acquisition under a 90-second total budget with three concurrent downloads. Retrieved text has a shared 30,000-character input budget; remaining relevant excerpts stay in context. The portfolio, watchlist and selected stories are captured together; concurrent retention or row-ID reuse cannot replace a selected story. Selection reasons and content type are archived with the evidence.

Default prompts request explicit OPEN/ADD/REDUCE/CLOSE/HOLD/WATCH plans with securities-based target weights, reference sizes and triggers, using concise direct wording. Users can replace the shared prompt and each style prompt. All inputs, resolved prompts, provider, model, effort and output are archived together. React Markdown plus GFM renders brief structure while raw HTML and remote images remain disabled.

`holding_horizon` is an independent setting (`ultra_short`, `short`, `medium_long`), defaulting to `medium_long` when upgrading old settings. `ai_horizon_prompts` stores optional overrides for each horizon. Prompt resolution combines the base, selected risk style and selected holding-horizon text for both providers. Jobs snapshot the choice; report evidence stores the horizon and resolved prompt. Existing reports without the field return null and receive no inferred horizon label.

OpenAI-compatible providers receive Chat Completions requests. `reasoning_effort` is omitted for Auto and passed without silent fallback otherwise. Provider rejection is surfaced. Codex models and allowed efforts come from app-server `model/list`; selected combinations are validated before inference. Codex uses an administrator-managed shared `CODEX_HOME`, per-user `HOME` and research workspace, and ephemeral runs with tools disabled. Neither broker keys nor OpenAI keys enter the research context. Only administrators can initiate device login or logout; model discovery and inference are available to all authenticated users. Login changes invalidate every user's Codex model cache.

`POST /api/ai/analyze` returns a job with HTTP 202 immediately. SQLite `analysis_jobs` stores owner, captured settings, phase, terminal status and report ID, with a unique active-job constraint per user. A process-level asyncio task runs independently of the HTTP connection. The browser polls `/api/ai/jobs/current` from a provider above page navigation; individual job lookup and cancellation are owner-scoped. Model inference has no application timeout. Cancellation closes the OpenAI request or signals a thread watcher to terminate the Codex process tree and wait for cleanup. Only completed output is stored as a report. Shutdown and restart mark unfinished jobs interrupted, without automatically rerunning a provider call.

Report discussions use `analysis_followups`, linked to the original report and an `analysis_jobs` entry with kind `followup`. Schema version 4 adds the job-kind field without rewriting existing reports. `POST /api/ai/analyses/{id}/followups` atomically stores the question and queues a task; a report-scoped request key makes retries idempotent. The shared active-job constraint covers research and follow-ups. Ownership is checked for report access, conversation pages and cancellation.

`Intelligence.prepare/complete` supplies a common provider path for research and replies. Follow-up context contains the saved report, archived prompts/evidence and complete successful question/answer pairs, followed by the current question. Legacy portfolio evidence is projected to securities-only data again. Failed/cancelled questions are retained in the UI but omitted from model history. Recent complete pairs have an 80,000-character/100-turn budget; used turn IDs, omitted count and resolved system prompt are recorded for each reply. The reply and successful job state are committed together. The original report is immutable.

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
