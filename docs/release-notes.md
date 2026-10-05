Peat 0.5.0 adds follow-up discussions for research briefs.

- Ask multi-turn questions directly under any saved brief. Each discussion uses that report's original portfolio, macro/news evidence, strategy and holding horizon.
- OpenAI-compatible providers and Codex share the same follow-up flow. Choose a reply model and reasoning effort independently.
- Replies run in the background without a generation timeout, with manual Stop, saved history and Markdown rendering.
- Questions survive cancellation, failure and reloads; request retries are deduplicated. View reply opens the correct report, with user/report isolation throughout.
- The original report remains unchanged. Long conversations retain complete recent pairs within a bounded context and expose omissions in the reply metadata/UI.

Peat 0.5.0 新增分析报告追问。

- 在已保存报告下直接进行多轮追问，沿用该报告的持仓、宏观与新闻证据、投资风格及持有周期。
- 支持 OpenAI 兼容接口与 Codex，回复模型和思考强度可单独选择。
- 回复后台生成、不设生成超时，支持手动中止、历史记录与 Markdown 展示。
- 失败、中止或刷新后保留问题；重复请求自动去重。“查看回复”可返回对应报告，对话按用户与报告隔离。
- 原报告保持原样。较长对话按上下文预算保留最近完整问答，省略更早轮次时在界面中说明。

Keep the existing data volume when upgrading. The discussion table and job-kind migration are applied automatically at startup. Existing briefs can be followed up immediately; no regeneration or new API registration is required.

升级时保留现有数据卷，启动时自动建立对话表并迁移任务类型字段。已有报告可直接追问，无需重新生成或注册新 API。

Image: `ghcr.io/kohakukirisame/peat:0.5.0` (`linux/amd64`, `linux/arm64`).

```sh
docker compose pull
docker compose up -d
```
