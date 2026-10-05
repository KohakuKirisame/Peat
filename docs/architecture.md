# Architecture and data contracts

```text
Browser (React, TypeScript)
          │ same-origin session cookie / JSON API
FastAPI ──┼── SQLite: users, settings, encrypted API credentials
          ├── Trading212 adapter (GET allowlist only)
          ├── Markets + Charts: Treasury XML / Yahoo chart feed
          ├── News: Google RSS → plain text → per-user retention
          ├── Intelligence: OpenAI-compatible API / isolated Codex CLI
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

Treasury data is fetched from the official daily yield XML feed. Time-series observations include dates. Exchange calendars account for scheduled holidays, DST and breaks. Unknown/out-of-range calendars return an explicit unknown state. Regular-session status does not imply live executable prices.

## News and AI

News topics are derived from held company names, watchlist names and industry keywords. Entries are deduplicated by URL and stripped of HTML. Retention applies both count and age limits per user. Article bodies are fetched on expansion or when selected for research, extracted as plain text with Trafilatura and cached in a per-article table with cascading retention. Every redirect is revalidated and DNS-pinned to a public address, with no browser credentials. Response size and fetch duration are bounded. Subscription/blocked pages retain an original-article link.

Analysis uses a securities-only projection of the portfolio: account total value, cash, reserved cash and interest-bearing deposits are omitted, and weights use securities market value. The raw account cache and funds UI retain these balances.

News selection scores every cached headline/excerpt against held companies, security weights, watchlist companies and configured industry terms. Recency is a secondary signal. Coverage is reserved for relevant holdings/industries before filling up to 30 slots; repeated headlines are deduplicated and source diversity is considered. These selected stories, rather than the latest N rows, are passed to body acquisition under a 45-second total budget. Retrieved text has a shared 30,000-character input budget; remaining relevant excerpts stay in context. Selection reasons and content type are archived with the evidence.

Default prompts request explicit OPEN/ADD/REDUCE/CLOSE/HOLD/WATCH plans with securities-based target weights, reference sizes and triggers, using concise direct wording. Users can replace the shared prompt and each style prompt. All inputs, resolved prompts, provider, model, effort and output are archived together. React Markdown plus GFM renders brief structure while raw HTML and remote images remain disabled.

OpenAI-compatible providers receive Chat Completions requests. `reasoning_effort` is omitted for Auto and passed without silent fallback otherwise. Provider rejection is surfaced. Codex models and allowed efforts come from app-server `model/list`; selected combinations are validated before inference. Codex processes use their own per-user HOME/CODEX_HOME and research workspace with tools disabled. Neither broker keys nor OpenAI keys enter the research context.

## Operations

The background loop updates configured portfolios and news at each user's interval. Market data is shared and cached. Manual refreshes use the same locks and throttles. Long-running AI calls run asynchronously; subprocess work is delegated to threads. Runtime jobs keep bounded output in memory and expire completed job metadata.

The app is single-process, suited to a local or small self-hosted workspace. Administrators have service-level trust because the console can run local commands. Normal users cannot reach administrative routes or other users' jobs.

## Extending

- Add brokers by implementing `Broker`, normalizing money with explicit currencies and exposing only authorized read operations.
- Add market/news providers behind their service classes, preserving timestamps, provenance and error states.
- Add LLM providers inside `Intelligence`; keep model/effort selection and immutable evidence records.
- Keep credentials in `Vault` and runtime files under the data directory.

## 中文要点

SQLite 是本地事实存储；外部数据保留来源、时间与币种。Broker 抽象负责未来平台扩展，Trading212 适配器仅允许明确列出的 GET 路径。当前持仓成本、净入金、已实现收益按各自来源分开处理。

新闻保存 RSS 摘要并支持按需读取正文；研究按持仓与行业相关性选材，记录关联对象和正文来源。现金及计息 deposit 仅保留在账户资金中，简报使用证券持仓市值作为仓位基数。AI 分析保存完整输入证据和当时使用的提示词。用户选择的思考强度会传给平台，失败时不会自动切换成其他档位。Codex 模型能力来自运行实例的模型列表。

数据、凭据和任务按用户隔离；管理员控制台属于实例运维权限。Git 与容器构建都排除运行数据。应用使用单进程轮询与进程内任务管理。
