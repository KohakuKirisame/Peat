# <img src="frontend/public/peat-logo.png" width="48" alt="Peat logo"> Peat

**Your portfolio, the wider market, and what matters next.**

Self-hosted investment research with Trading 212, local news and configurable AI. React + FastAPI + SQLite. Peat contains no trading or order-submission functionality.

[简体中文](README.zh-CN.md) · [Deployment](docs/deployment.md) · [Data & architecture](docs/architecture.md) · [AGPL-3.0](LICENSE)

## Features

- Responsive desktop/mobile workspace, English/Chinese, a night-sky default theme, light/dark/system options and a custom accent color.
- Interface zoom from 80% to 200% in the top bar and Settings → Appearance, with a 100% reset. Saved per account in the current browser, with responsive layouts adjusted to the zoom level.
- Username/password registration. The first account is the administrator; administrators can edit usernames, roles, activation and passwords.
- Trading 212 Invest/Stocks ISA account value, current holding cost, cash, realized/unrealized P&L, positions, executions, dividends and cash movements. Live and demo environments are separate.
- Pies appear as collapsed portfolio groups with securities value and P&L. Expand a Pie to inspect its holdings or open a constituent's candlestick chart. Search includes Pie names and constituent stocks.
- Interactive OHLC candlesticks: 1/5/15 minutes, hourly, daily, weekly and monthly; selectable history ranges, candle hover values, volume and historical navigation. Per-user symbol mappings handle broker/quote-provider differences.
- Exchange sessions with holiday/DST/lunch-break calendars; US 2Y/10Y/30Y Treasury yields, WTI/Brent, natural gas, gold, silver and platinum.
- Company/industry RSS headlines, excerpts and expandable article bodies for holdings and a manual watchlist. Structured article text, readable-page and AMP fallbacks, retry controls, configurable count/age limits and manual clearing.
- OpenAI-compatible Chat Completions and locally installed Codex CLI. Model discovery, manual API model IDs and user-selected reasoning effort. Codex effort choices come from its model catalog.
- Five investment styles, shared and per-style editable prompts, reset-to-default controls and analysis archives containing the exact evidence, prompts, model and effort used.
- Independent holding horizons: ultra short term (intraday–3 trading days), short term (1–4 weeks), and medium/long term (1 month or longer). Each has an editable prompt; proposed actions include holding duration, review points and exit conditions.
- Background research tasks continue across navigation and page reloads, with progress, elapsed time and a manual Stop button. Model generation has no Peat timeout.
- Multi-turn follow-up discussions under each brief, using its saved evidence, style and holding horizon. Replies support Markdown, separate model/effort selection, background generation and manual cancellation.
- One administrator-managed Codex device login serves the whole workspace. Research workspaces remain per user. Admin-only local console and versioned Codex/calendar dependency updates.
- Encrypted API credentials, hashed passwords, persistent Docker storage, CI checks and multi-architecture Docker releases.

## Docker

Requires Docker Engine with Compose. Release images are published to `ghcr.io/kohakukirisame/peat` for `linux/amd64` and `linux/arm64` by the tag-triggered workflow.

```sh
git clone https://github.com/KohakuKirisame/Peat.git
cd Peat
docker compose up -d
```

Open **http://localhost:8787** and create the first account. Data, the encryption key, Codex logins and dependency overrides live in the `peat-data` volume.

To build from source:

```sh
docker compose -f compose.yaml -f compose.build.yaml up -d --build
```

To update the application:

```sh
docker compose pull
docker compose up -d
```

Keep the data volume when updating. In Settings → Runtime, you can install an exact Codex or exchange-calendar version from the official registry. Codex switches after version validation; calendar changes take effect after `docker compose restart peat`. Python/FastAPI and frontend updates are delivered with the application image.

## Source deployment

Use **Python 3.13** and **Node.js 24 LTS**. Python dependencies are hash-pinned in `requirements.lock`; frontend dependencies are pinned in `frontend/package-lock.json`.

Windows PowerShell:

```powershell
git clone https://github.com/KohakuKirisame/Peat.git
cd Peat
Copy-Item .env.example .env
.\scripts\start.ps1
```

Linux/macOS:

```sh
git clone https://github.com/KohakuKirisame/Peat.git
cd Peat
cp .env.example .env
sh scripts/start.sh
```

For subsequent launches, activate the virtual environment and run `python -m peat`. Install Codex from Settings → Runtime, or use an existing `codex` installation. The Docker image already bundles Node, npm, Codex, Python, exchange calendars, Git and ripgrep.

## First setup

1. **Account:** Register a username (3–32 letters/digits/`_.-`) and password (10–128 characters). The first account becomes administrator. Set `PEAT_REGISTRATION_OPEN=false` after creating your intended accounts if desired.
2. **Trading 212:** In Settings, enter API Key + API Secret with account, portfolio, history and `pies:read` permissions. Choose the correct live/demo environment. Open Overview and sync. The API applies to Invest and Stocks ISA accounts.
3. **History:** Activity → Sync history imports one provider page at a time; Load older history continues the cursor. The interface reports whether all provider pages have been read. Import English-column Trading 212 CSV statements to summarize deposits, withdrawals, dividends and stated realized P&L by currency.
4. **News:** Add companies and industry names to Watchlist, then Collect news. Google News RSS requires no API registration. Retention settings remove the oldest saved items.
5. **AI API:** Save a base URL including `/v1` and a key. For local servers, explicitly list their hostnames in `PEAT_LLM_ALLOWED_HOSTS`, e.g. `localhost,127.0.0.1,host.docker.internal`. The base URL must point to a trusted endpoint.
6. **Codex:** An administrator opens Settings → Start device login, follows the verification link and enters the one-time code. Enable device-code login in ChatGPT security settings if required. All Peat users can then use this shared connection; only administrators can connect or disconnect it. An existing active administrator's Peat login is adopted on upgrade. Host-machine credentials are never imported.
7. **Research:** Choose provider, model, reasoning effort, investment style and holding horizon in Intelligence. Refresh model discovery after login. Edit the shared, style and horizon prompts, save preferences, then Generate brief. The selected provider receives securities holdings, market data and relevant news for that analysis. You can continue using other pages while it runs; the global task bar shows progress and provides Stop generation and View brief controls.

## Data semantics

Portfolio **invested capital** means the cost of currently open positions, not lifetime deposits. Account totals use the broker's account currency; each quote retains its instrument currency. CSV results are grouped by currency and cover only imported rows. They are not added to broker totals. Account-value charts contain locally collected snapshots and include external cash flows.

Pie details are refreshed every five minutes, with detail requests spaced to respect Trading 212's rate limits. Pie value/P&L come from the Pie API in account currency; Pie cash is displayed in account funds, outside the holdings table. The original account totals stay unchanged. A stock held across multiple Pies and outside Pies is split by its actual quantities. The outside portion's market value is quantity-proportional; its P&L is left unavailable when its separate cost basis is absent. If quantities do not reconcile, Peat shows the original individual holdings until the next matching Pie snapshot. Permission/API failures keep holdings visible. Trading 212 currently documents its Pie API as operational but deprecated.

Trading 212 is polled at the configured interval (default 60 seconds), subject to provider limits. Public Yahoo quotes/candles can be delayed or unavailable; candles use provider OHLC rather than a reconstructed total-return series. Confirm the instrument, exchange and currency when setting a symbol. Treasury rates are published daily. Every dataset carries source/time information, and failed quote refreshes mark retained values stale. Exchange calendars describe scheduled regular sessions and cannot report unplanned halts.

Charts recognize international country-tagged and legacy Trading 212 IDs, including `AIRp_EQ → AIR.PA`. Unrecognized broker IDs use instrument/exchange metadata to find the listing; saved symbol mappings take priority. The chart displays its resolved symbol, currency and exchange timezone. Switching holdings clears the previous chart and its metadata immediately. Hover over Market pulse curves to inspect each observation's date/time and precise value with units; keyboard arrows and touch are supported. Treasury observations retain their publication date; commodity timestamps use the exchange timezone.

News cards expand to fetch and cache the readable publisher article, including Google News link resolution. Extraction checks the main article's structured metadata, readable page text and declared AMP/canonical alternatives. Temporary network failures are retried, and failed cards offer Retry article with the original-article link. Successful bodies are kept with their source URL and timestamp and removed with the news retention policy. Subscription and access restrictions are identified in the card. Up to 30 company/industry queries are fetched per cycle; no paid news account is required.

Research ranks cached news by held companies, position weights, watchlist companies, industry terms and recency, then balances coverage and sources and removes repeated headlines. Up to 30 relevant stories enter a brief. Body retrieval runs for that selected set with a bounded time budget; text budgets are shared across the retrieved bodies. The evidence panel records the associated companies/industries and whether article text or an RSS excerpt was used.

Each user can run one research task at a time. Settings are captured when the task starts; selected holdings and news stay attached to that run. Browser navigation, reloads and disconnects do not stop it. OpenAI-compatible generation and Codex inference have no application time limit; Stop cancels the request or Codex process tree without saving a partial brief. Article acquisition and model discovery keep separate network limits. A server restart marks unfinished tasks as interrupted; generate a new brief to resume research.

Holding horizon is independent of risk style. The default is medium/long term; the three default timing windows can be adjusted in Prompt studio. Both LLM providers receive the selected horizon template alongside the base and style prompts. The job and saved brief retain that choice and its resolved text even if settings later change. Earlier briefs without a recorded horizon keep their original metadata.

Open a brief in Intelligence and use **Discuss this brief** to ask follow-up questions. Replies default to that report's provider, model and reasoning effort; expand Reply model & reasoning to change them for the discussion. Both providers receive the saved report, its original evidence/prompts and recent completed conversation turns. Follow-ups use the report's dated data. Answers and questions are stored separately from the original report and remain available after navigation or reload. Ctrl/⌘ + Enter sends a question; Stop reply cancels generation. Failed or cancelled questions remain available for asking again.

One research or reply task can run per user. Each question accepts up to 8,000 characters. Long conversations use up to the latest 100 completed turns within an 80,000-character history budget; full question/answer pairs are preserved, and the UI indicates when older turns were omitted from a reply's context. Earlier stored questions can be loaded in pages of 50.

Cash and interest-bearing deposits remain account funds. They are excluded from research inputs, position weights, concentration analysis and suggested funding. Research weights and reference amounts use invested securities market value. The five editable default prompts request concrete OPEN/ADD/REDUCE/CLOSE/HOLD/WATCH recommendations, target weights, staged sizes and triggers, in concise Markdown. Headings, emphasis, lists and GFM tables render directly in archived and new briefs. Historical brief content remains unchanged; generate a new brief to use the new research rules.

## Development and validation

```sh
python -m venv .venv
# Activate .venv first.
pip install --require-hashes -r requirements.lock
pip install pytest pytest-asyncio ruff
python -m pytest -q
ruff check peat tests
python scripts/check_secrets.py
cd frontend
npm ci
npm run build
npx playwright install chromium
npm run test:e2e
```

Backend tests cover registration/admin permissions, tenant isolation, encrypted credentials, CSRF, currency semantics, CSV deduplication, article extraction/retries, news retention, exchange holidays/breaks, candle gaps, background task cancellation/recovery, shared Codex authorization and AI model/effort/prompt provenance. Browser tests use a disposable database and mocked provider responses. `npm run dev` proxies `/api` to a separately running backend on port 8787.

## Storage and source hygiene

Runtime storage is under `PEAT_DATA_DIR` (default `./data`). API keys are encrypted with a generated Fernet key in `data/master.key`, or `PEAT_ENCRYPTION_KEY` supplied by the operator. Passwords use Argon2id; session tokens are stored as hashes. Codex manages its shared file credentials under the private data directory; `codex-shared.json` selects the new `shared/codex` directory or an adopted administrator login. Per-user portfolios, API keys, settings and reports remain separate.

Back up the **whole data directory/volume**, including its master key, while Peat is stopped. The Git ignore rules exclude runtime data and credentials. Docker uses an explicit build-context allowlist and never copies a local `.env`, data directory or Codex login. CI checks source candidates for credential patterns and private runtime paths. Never add your keys to fixtures or source code.

The administrator console executes commands as the Peat server account and is intended for the instance operator. Administrators are trusted operators. The default Compose configuration binds to loopback, runs without root and does not mount a Docker socket. For remote deployment, use HTTPS, secure cookies and an explicit origin; see [deployment](docs/deployment.md).

## License and artwork

Copyright © 2026 KohakuKirisame. Licensed under **GNU Affero General Public License v3.0 only**. Source must remain available to users of modified network deployments under the license's terms. Dependencies retain their own licenses.

The Peat mark is an original AI-generated Islay peat block in dark earth, coastal sage and salt tones. The PNG and generation prompt are included in [brand notes](docs/brand.md).

## Provider references

- [Trading 212 official API](https://docs.trading212.com/) — read-only account, position and history endpoints.
- [US Treasury XML feed](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed) — daily yield data.
- [Codex authentication](https://learn.chatgpt.com/docs/auth) and [model discovery](https://learn.chatgpt.com/docs/app-server#models).
- [exchange_calendars](https://github.com/gerrymanoim/exchange_calendars) — regular exchange schedules.

Yahoo Finance's public chart endpoint and Google News RSS are external public feeds without an application-specific availability guarantee. Their availability and terms can change; the provider modules are replaceable.
