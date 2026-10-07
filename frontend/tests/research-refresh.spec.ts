import { test, expect } from "@playwright/test";

const settings = {
  language: "en",
  theme: "dark",
  accent: "#8a9aff",
  style: "balanced",
  holding_horizon: "ultra_short",
  ai_provider: "codex",
  ai_model: "fixture",
  reasoning_effort: "high",
  ai_base_prompt: "",
  ai_style_prompts: {},
  ai_horizon_prompts: {},
  ai_live_data: true,
  ai_web_search: true,
  ai_market_tools: true,
  analysis_limit: 0,
};
const user = {
  id: 1,
  username: "fresh-fixture",
  role: "user",
  active: true,
  settings,
};

test("US intraday charts toggle pre/post sessions and show the hovered session", async ({
  page,
}) => {
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/charts") {
      const extended = url.searchParams.get("extended") === "true";
      const intraday = url.searchParams.get("interval") !== "1d";
      const candles = ["pre", "regular", "post"].map((session, i) => ({
        time: 1791190800 + i * 21600,
        open: 100 + i,
        high: 104 + i,
        low: 99 + i,
        close: 102 + i,
        volume: 500,
        session,
      }));
      return route.fulfill({
        json: {
          data: {
            symbol: "AAPL",
            name: "Apple",
            currency: "USD",
            timezone: "America/New_York",
            status: "delayed",
            source: "TEST FIXTURE",
            extended_supported: intraday,
            has_extended: extended,
            candles: extended ? candles : [candles[1]],
          },
        },
      });
    }
    const payload: Record<string, unknown> = {
      "/api/me": user,
      "/api/ai/jobs/current": null,
      "/api/watchlist": [{ id: 1, name: "Apple", symbol: "AAPL" }],
    };
    return route.fulfill({ json: payload[url.pathname] ?? {} });
  });
  await page.goto("/#watchlist");
  await page
    .getByRole("button", { name: "Explore price history", exact: true })
    .click();
  await page.getByRole("button", { name: "15m", exact: true }).click();
  const checkbox = page.getByRole("checkbox", {
    name: "US pre/post market",
    exact: true,
  });
  await expect(checkbox).toBeChecked();
  await expect(page.locator(".session-band")).toHaveCount(2);
  const plot = page.locator("svg.candles");
  const rect = await plot.boundingBox();
  await plot.hover({
    position: { x: rect!.width * 0.17, y: rect!.height * 0.5 },
  });
  await expect(page.locator(".ohlc .session-label")).toHaveText("Pre-market");
  await checkbox.uncheck();
  await expect(page.locator(".session-band")).toHaveCount(0);
  await expect(page.locator(".ohlc .session-label")).toHaveText(
    "Regular session",
  );
  await checkbox.check();
  await page.locator(".price-chart").screenshot({
    path: "../.cache/screenshots/extended-sessions-fixture.png",
    animations: "disabled",
  });
});

test("follow-ups refresh by default and expose the new price timestamps and source evidence", async ({
  page,
}) => {
  const stamp = new Date().toISOString();
  const report = {
    id: 1,
    provider: "codex",
    model: "fixture",
    reasoning_effort: "high",
    style: "balanced",
    holding_horizon: "ultra_short",
    created_at: "2026-10-01T12:00:00Z",
    content: "## Original view\nReference price was 100.",
    evidence: {},
  };
  const evidence = {
    freshness: { mode: "live_refresh", collected_at: stamp },
    price_histories: [
      {
        symbol: "AAPL",
        quote: {
          price: 321.25,
          as_of: stamp,
          currency: "USD",
          session: "post",
        },
      },
    ],
    news: [
      {
        id: 7,
        title: "Historical earnings event",
        url: "https://publisher.example/story",
        effective_published_at: "2023-01-02T10:00:00Z",
        timing_class: "background",
        publication_precision: "time",
      },
    ],
  };
  const turns: any[] = [];
  const requests: any[] = [];
  let job: any = null;
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/followups") && route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      requests.push(body);
      turns.push({
        id: turns.length + 1,
        question: body.question,
        answer: "## Rechecked plan\nThe latest quote is **321.25**.",
        model: body.model,
        provider: body.provider,
        reasoning_effort: body.reasoning_effort,
        status: "completed",
        created_at: stamp,
        context_mode: body.refresh_context ? "live" : "saved",
        freshness: body.refresh_context ? evidence.freshness : null,
      });
      job = {
        id: `reply-${turns.length}`,
        kind: "followup",
        analysis_id: 1,
        status: "completed",
        phase: "finished",
        model: body.model,
        reasoning_effort: body.reasoning_effort,
        created_at: stamp,
        finished_at: stamp,
      };
      return route.fulfill({ status: 202, json: job });
    }
    const payload: Record<string, unknown> = {
      "/api/me": user,
      "/api/ai/jobs/current": job,
      "/api/ai/analyses": [
        { ...report, content: undefined, evidence: undefined },
      ],
      "/api/ai/analyses/1": report,
      "/api/ai/prompts": {},
      "/api/ai/analyses/1/followups": { items: turns, next_before: null },
      "/api/ai/analyses/1/followups/1/evidence": {
        evidence,
        research_activity: {
          web_searches: [{ query: "issuer original event date" }],
          market_calls: [],
        },
      },
    };
    return route.fulfill({ json: payload[path] ?? {} });
  });
  await page.goto("/#intelligence");
  const panel = page.locator(".followup-panel");
  await expect(
    panel.getByRole("checkbox", {
      name: "Refresh data for this reply",
      exact: true,
    }),
  ).toBeChecked();
  await expect(
    panel.getByRole("checkbox", {
      name: "Codex live web research",
      exact: true,
    }),
  ).toBeChecked();
  await page
    .getByLabel("Follow-up question", { exact: true })
    .fill("Is the original trigger still valid?");
  await panel
    .getByRole("button", { name: "Send question", exact: true })
    .click();
  await expect(panel.locator(".followup-answer")).toContainText("321.25");
  expect(requests[0].refresh_context).toBe(true);
  expect(requests[0].web_search).toBe(true);
  await expect(page.locator(".brief-content")).toContainText(
    "Reference price was 100",
  );
  await panel.locator(".reply-evidence summary").click();
  await expect(panel.locator(".research-sources table")).toContainText(
    "321.25 USD",
  );
  await expect(panel.locator(".research-sources time")).toHaveAttribute(
    "datetime",
    stamp,
  );
  await expect(panel.locator(".news-timing")).toContainText(
    "Historical background",
  );
  await panel
    .getByRole("checkbox", { name: "Refresh data for this reply", exact: true })
    .uncheck();
  await expect(
    panel.getByRole("checkbox", {
      name: "Codex live web research",
      exact: true,
    }),
  ).toBeDisabled();
  await page
    .getByLabel("Follow-up question", { exact: true })
    .fill("Explain the original reasoning only.");
  await panel
    .getByRole("button", { name: "Send question", exact: true })
    .click();
  await expect(panel.locator(".followup-turn")).toHaveCount(2);
  expect(requests[1].refresh_context).toBe(false);
});

test("reports paginate, delete with confirmation, and apply a confirmed retention limit", async ({
  page,
}) => {
  let preferences = { ...settings };
  let reports = Array.from({ length: 23 }, (_, i) => ({
    id: i + 1,
    provider: "openai",
    model: "fixture",
    reasoning_effort: "high",
    style: "balanced",
    holding_horizon: "short",
    created_at: "2026-10-01T12:00:00Z",
    content: `## Report ${i + 1}`,
    evidence: {},
  })).reverse();
  let deleted = 0,
    saved = 0;
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url()),
      path = url.pathname;
    if (path === "/api/ai/analyses")
      return route.fulfill({
        json: reports
          .filter(
            (r) =>
              !url.searchParams.get("before") ||
              r.id < Number(url.searchParams.get("before")),
          )
          .slice(0, 20)
          .map(({ content, evidence, ...r }) => r),
      });
    const single = path.match(/^\/api\/ai\/analyses\/(\d+)$/);
    if (single) {
      const id = Number(single[1]);
      if (route.request().method() === "DELETE") {
        deleted++;
        reports = reports.filter((r) => r.id !== id);
        return route.fulfill({ json: { ok: true } });
      }
      return route.fulfill({ json: reports.find((r) => r.id === id) });
    }
    if (path === "/api/settings" && route.request().method() === "PUT") {
      saved++;
      preferences = route.request().postDataJSON();
      if (preferences.analysis_limit)
        reports = reports.slice(0, preferences.analysis_limit);
      return route.fulfill({ json: preferences });
    }
    const payload: Record<string, unknown> = {
      "/api/me": { ...user, settings: preferences },
      "/api/ai/jobs/current": null,
      "/api/ai/prompts": {},
      "/api/ai/storage": {
        count: reports.length,
        limit: preferences.analysis_limit,
      },
      "/api/connections": {
        trading212: { configured: false },
        openai: { configured: false },
      },
      "/api/codex/status": { logged_in: false },
    };
    return route.fulfill({
      json: payload[path] ?? { items: [], next_before: null },
    });
  });
  async function confirmAction(label: string, accept: boolean) {
    const button = page.getByRole("button", { name: label, exact: true });
    const dialogPromise = page.waitForEvent("dialog");
    const clicked = button.click();
    const dialog = await dialogPromise;
    if (accept) await dialog.accept();
    else await dialog.dismiss();
    await clicked;
    await expect(button).toBeEnabled();
  }
  await page.goto("/#intelligence");
  await page
    .getByRole("button", { name: "Load older reports", exact: true })
    .click();
  await expect(page.locator(".archive-list button")).toHaveCount(23);
  await page.locator(".archive-list button").last().click();
  await expect(page.locator(".brief-content")).toContainText("Report 1");
  await confirmAction("Delete report", false);
  expect(deleted).toBe(0);
  await confirmAction("Delete report", true);
  await expect(page.locator(".brief-content")).toContainText("Report 23");
  expect(deleted).toBe(1);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByLabel("Maximum saved reports", { exact: true }).fill("1");
  await confirmAction("Save report limit", false);
  expect(saved).toBe(0);
  await expect(
    page.getByText("Report storage updated", { exact: true }),
  ).toHaveCount(0);
  await confirmAction("Save report limit", true);
  await expect(
    page.getByText("Report storage updated", { exact: true }),
  ).toBeVisible();
  expect(saved).toBe(1);
  expect(reports).toHaveLength(1);
});
