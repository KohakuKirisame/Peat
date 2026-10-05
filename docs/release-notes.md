Peat 0.2.0 improves portfolio grouping and research quality.

- Trading 212 Pies are grouped with expand/collapse controls, constituent charts and quantity-aware outside-Pie holdings.
- Research briefs render Markdown headings, emphasis, lists and tables, including archived briefs.
- News cards fetch and cache expandable publisher article bodies. Retention clears their cached text as well.
- Research selects news by held companies, security weights, watchlist and industry relevance, with coverage, recency and duplicate controls.
- Cash and interest-bearing deposits remain in account funds and are excluded from research context and portfolio allocation analysis.
- Revised bilingual prompts request concrete OPEN/ADD/REDUCE/CLOSE/HOLD/WATCH actions, target weights and triggers with concise wording.

Peat 0.2.0 新增 Pie 合并与展开、简报 Markdown 渲染、新闻正文缓存和基于持仓/行业相关性的选材。现金与计息 deposit 仅作为账户资金显示。新提示词给出明确的开仓、增持、减持、平仓等操作、目标仓位与触发条件，减少反复声明。

Existing data volumes are retained. The article-body table is created automatically on startup. Existing reports render as Markdown; generate a new brief to use the updated research rules. Pie grouping requires Trading 212 `pies:read` permission.

Image: `ghcr.io/kohakukirisame/peat:0.2.0` (`linux/amd64`, `linux/arm64`).
