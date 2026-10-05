Peat 0.3.0 adds background research and shared administrator Codex access.

- Research runs in a server-side background task. Navigate, reload or disconnect the browser while the global task bar tracks progress and elapsed time.
- OpenAI-compatible generation and Codex inference have no application timeout. Stop generation cancels the request or Codex process tree; completed briefs are archived automatically.
- An administrator's Codex device login is available to all Peat users. Only administrators manage login/logout. Existing administrator logins are adopted on upgrade; portfolios, API keys, settings and reports remain per user.
- News extraction handles more Google News links, retries temporary failures, and combines structured article text, readable-page extraction and declared AMP/canonical alternatives. Failed cards include Retry article and the original article link.
- Research preserves its selected holdings/news while other pages refresh or clear data. Cash and interest-bearing deposits stay excluded from allocation and research inputs.

Peat 0.3.0 新增后台研究与管理员共享 Codex 登录。

- 生成报告期间可切换页面、刷新或断开浏览器，全局任务栏显示进度与用时。
- OpenAI 兼容接口与 Codex 推理不设应用超时，支持手动中止；完整简报自动归档。
- 管理员完成一次 Codex 设备登录后全站可用，登录与退出仅限管理员。升级时沿用已有管理员登录；持仓、API Key、设置和简报仍按用户独立。
- 新闻全文增加 Google News 链接兼容、临时失败重试、结构化文章和 AMP 回退；失败卡片可重新获取并打开原文。
- 切换页面清理新闻时，本次研究仍保留选定的持仓与新闻。现金和计息 deposit 继续仅作为账户资金显示。

Keep the existing data volume when upgrading. The research-job table is created automatically. A server restart marks unfinished generation as interrupted; generate again after restarting. Back up the complete data volume, including `codex-shared.json` and its selected Codex directory.

升级时保留现有数据卷，研究任务表自动创建。服务重启后，未完成的生成标记为已中断，可重新生成。备份完整数据卷，包含 `codex-shared.json` 及其指向的 Codex 目录。

Image: `ghcr.io/kohakukirisame/peat:0.3.0` (`linux/amd64`, `linux/arm64`).

```sh
docker compose pull
docker compose up -d
```
