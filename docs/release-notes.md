Peat 0.6.0 adds time-aware live research, extended-hours candles and report management.

- US intraday charts include pre/post-market bars with session shading and a regular-hours toggle.
- Analysis and follow-ups refresh holdings, quotes and news by default. Original reports remain intact; each reply saves its new evidence and data timestamps.
- News uses original publication/update dates and horizon-aware recency. Price context matches completed bars to the relevant publication window and keeps out-of-range events explicit.
- Codex can use live web search and bundled read-only quote, historical-price, news-search and article tools. Compatible API models can call the same research functions. Model/effort settings are preserved.
- Delete reports with their discussions, load older archives, and set a per-user retention limit based on recent activity. Active discussions are protected, and deleted report IDs are never reused.

Peat 0.6.0 新增按时间核验的实时研究、美股盘前盘后 K 线与报告管理。

- 美股分钟/小时图支持盘前、盘后 K 线，标注时段并可切回常规交易时段。
- 分析与追问默认刷新持仓、行情和新闻；原报告保持原样，每次回复保存新证据及数据时间。
- 新闻区分原始发表、更新和获取时间，按持有周期调整时效权重，并匹配对应价格窗口；超出窗口时保留缺口。
- Codex 支持实时联网检索及内置只读报价、历史走势、新闻搜索和文章读取工具；兼容 API 模型可调用相同研究能力，保留用户的模型与思考强度。
- 支持删除报告及其追问、加载更早档案和设置数量上限；按最近活动保留，保护正在追问的报告，删除后不复用编号。

Keep the existing data volume. Schema updates are automatic. Source deployments must reinstall requirements.lock for the bundled MCP SDK. No new data API registration is required. Existing custom prompts remain saved; the updated timing/tool rules are applied alongside them. Report retention defaults to unlimited (0), preserving existing archives.

升级时保留原数据卷，数据库结构自动更新。源码部署需重新安装 requirements.lock 中的依赖，以包含 MCP SDK。无需注册新的数据 API。原有自定义提示词继续保留，新时间核验与工具规则一并生效。报告数量默认 0（不限），保留现有档案。

Image: `ghcr.io/kohakukirisame/peat:0.6.0` (`linux/amd64`, `linux/arm64`).

```sh
docker compose pull
docker compose up -d
```
