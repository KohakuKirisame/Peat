import { test, expect } from "@playwright/test";

test("research renders Markdown safely and news expands cached full text on mobile", async ({
  page,
}) => {
  const user = {
    id: 1,
    username: "research-test-fixture",
    role: "user",
    active: true,
    settings: {
      theme: "light",
      accent: "#8a9aff",
      language: "zh",
      portfolio_interval: 60,
      news_days: 30,
      news_limit: 500,
      news_interval: 900,
      news_language: "zh",
      style: "aggressive",
      ai_provider: "openai",
      ai_model: "fixture-model",
      reasoning_effort: "high",
      ai_base_prompt: "",
      ai_style_prompts: {},
    },
  };
  const report = {
    id: 1,
    style: "aggressive",
    model: "fixture-model",
    reasoning_effort: "high",
    created_at: "2026-10-05T12:00:00Z",
    content:
      "## 简要判断\n\n**优先增持 ACME**，分批调整。\n\n- 第一个观察条件\n- 第二个观察条件\n\n## 操作建议\n\n| 标的 | 操作 | 目标仓位 |\n| --- | --- | --- |\n| ACME | 增持 | 20% → 25% |\n\n[原文](https://publisher.example/story)\n\n<script>window.__injected=true</script>\n\n[unsafe](javascript:alert(1))",
    evidence: {
      news_selection: { selected_count: 1, candidate_count: 9 },
      news: [
        {
          id: 1,
          title: "ACME 业绩提升",
          url: "https://publisher.example/story",
          related_entities: [{ name: "ACME" }],
          content_kind: "article_body",
        },
      ],
    },
  };
  const article = {
    id: 1,
    title: "ACME 业绩提升",
    content: "这是新闻摘要。",
    source: "Fixture Press",
    topic: "ACME",
    url: "https://publisher.example/story",
    published_at: "2026-10-05T12:00:00Z",
  };
  let bodyRequests = 0,
    retries = 0;
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/news/1/fulltext") {
      bodyRequests++;
      return route.fulfill({
        json: {
          status: "ready",
          content:
            "正文第一段：公司公布经营变化。\n\n正文第二段：提供行业与业务背景。",
          source_url: article.url,
          fetched_at: "2026-10-05T12:00:00Z",
          truncated: false,
        },
      });
    }
    if (
      path === "/api/news/2/fulltext" &&
      new URL(route.request().url()).searchParams.get("refresh") === "true"
    ) {
      retries++;
      return route.fulfill({
        json: {
          status: "ready",
          content: "Retry recovered the readable article body.",
          source_url: article.url,
          fetched_at: "2026-10-05T12:00:00Z",
        },
      });
    }
    if (path === "/api/news/2/fulltext")
      return route.fulfill({
        json: { status: "unavailable", source_url: article.url },
      });
    const payload: Record<string, unknown> = {
      "/api/me": user,
      "/api/ai/analyses": [report],
      "/api/ai/prompts": { base: "Fixture", styles: {} },
      "/api/news": {
        items: [article, { ...article, id: 2, title: "正文不可用测试" }],
        total: 2,
      },
      "/api/markets": { data: { quotes: [] }, exchanges: [] },
    };
    return route.fulfill({ json: payload[path] ?? {} });
  });
  await page.goto("/#intelligence");
  await expect(
    page.getByRole("heading", { name: "简要判断", level: 2 }),
  ).toBeVisible();
  await expect(page.locator(".brief-content strong")).toHaveText(
    "优先增持 ACME",
  );
  await expect(page.locator(".brief-content li")).toHaveCount(2);
  await expect(page.locator(".brief-content table")).toContainText("20% → 25%");
  await expect(
    page.locator(
      '.brief-content script, .brief-content a[href^="javascript:"]',
    ),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "查看依据与当时提示词" }).click();
  await expect(page.locator(".evidence")).toContainText("按持仓与行业筛选新闻");
  await expect(page.locator(".evidence-related")).toContainText(
    "关联 · ACME · 新闻正文",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../.cache/screenshots/research-markdown-fixture.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "打开导航" }).click();
  await page.getByRole("button", { name: "新闻室", exact: true }).click();
  const first = page
    .locator(".news-feed article")
    .filter({ hasText: "ACME 业绩提升" });
  await first.getByRole("button", { name: "展开全文" }).click();
  await expect(first.locator(".article-fulltext")).toContainText("正文第二段");
  await first.getByRole("button", { name: "收起正文" }).click();
  await first.getByRole("button", { name: "展开全文" }).click();
  expect(bodyRequests).toBe(1);
  const second = page
    .locator(".news-feed article")
    .filter({ hasText: "正文不可用测试" });
  await second.getByRole("button", { name: "展开全文" }).click();
  await expect(second.getByRole("link", { name: "打开原文" })).toBeVisible();
  await second.getByRole("button", { name: "重试获取", exact: true }).click();
  await expect(second.locator(".article-fulltext")).toContainText(
    "Retry recovered",
  );
  expect(retries).toBe(1);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "../.cache/screenshots/news-fulltext-fixture.png",
    fullPage: true,
    animations: "disabled",
  });
});
