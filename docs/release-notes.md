Peat 0.1.1 introduces a self-hosted investment research workspace.

- Trading 212 portfolio, history and CSV statements.
- Multi-timeframe candlesticks, Treasury yields, commodities and exchange sessions.
- Local RSS news with retention controls.
- OpenAI-compatible APIs and per-user Codex device login.
- Selectable models and reasoning effort, five editable investment-style prompts and archived evidence.
- English/Chinese, responsive layout, light/dark/system themes and custom accents.
- Admin users, local command console, encrypted credentials and dependency version controls.

Run with `docker compose up -d` using the attached Compose file, or build from source using the build override. Persistent data is stored in `peat-data`.

Peat 0.1.1 提供持仓、K 线、宏观行情、本地新闻和可配置 AI 研究。支持中英文、自定义主题、管理员控制台、模型及思考强度选择，以及五档可编辑提示词。

Image: `ghcr.io/kohakukirisame/peat:0.1.1` (`linux/amd64`, `linux/arm64`). See the bilingual README for setup and data semantics.

This patch also validates the HTTP host before account bootstrap and administrative routes.
