import { test, expect } from "@playwright/test";

const user = {
  id: 1,
  username: "background-fixture",
  role: "user",
  active: true,
  settings: {
    theme: "dark",
    accent: "#8a9aff",
    language: "en",
    portfolio_interval: 60,
    news_days: 30,
    news_limit: 500,
    news_interval: 900,
    news_language: "en",
    style: "balanced",
    ai_provider: "openai",
    ai_model: "fixture-max",
    reasoning_effort: "max",
    ai_base_prompt: "",
    ai_style_prompts: {},
  },
};

test("report continues across navigation and reload, can be stopped, and delivers in background", async ({
  page,
}) => {
  let job: any = null,
    count = 0,
    cancels = 0;
  const reports: any[] = [];
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/ai/analyze") {
      job = {
        id: `background-${++count}`,
        status: "running",
        phase: "generating",
        model: "fixture-max",
        reasoning_effort: "max",
        style: "balanced",
        provider: "openai",
        analysis_id: null,
        error: null,
        created_at: new Date(Date.now() - 7200000).toISOString(),
        updated_at: new Date().toISOString(),
        finished_at: null,
      };
      return route.fulfill({ status: 202, json: job });
    }
    if (path.endsWith("/cancel")) {
      cancels++;
      job = {
        ...job,
        status: "cancelled",
        phase: "finished",
        finished_at: new Date().toISOString(),
      };
      return route.fulfill({ json: job });
    }
    const data: Record<string, unknown> = {
      "/api/me": user,
      "/api/settings": {},
      "/api/ai/jobs/current": job,
      "/api/ai/analyses": reports,
      "/api/ai/prompts": { base: "Fixture", styles: {} },
      "/api/watchlist": [],
      "/api/news": { items: [], total: 0 },
    };
    return route.fulfill({ json: data[path] ?? {} });
  });
  await page.goto("/#intelligence");
  await page
    .getByRole("button", { name: "Generate brief", exact: true })
    .click();
  await expect(page.locator(".analysis-task-banner")).toContainText(
    "Generating brief",
  );
  await expect(page.locator(".analysis-task-banner")).toContainText("2h");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("button", { name: "Stop generation", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../.cache/background-task-mobile.png",
    animations: "disabled",
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "Watchlist", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Watchlist", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".analysis-task-banner")).toBeVisible();
  await page.reload();
  await expect(page.locator(".analysis-task-banner")).toContainText(
    "Generating brief",
  );
  await page
    .getByRole("button", { name: "Stop generation", exact: true })
    .click();
  await expect(page.locator(".analysis-task-banner")).toContainText(
    "Generation stopped",
  );
  expect(cancels).toBe(1);
  expect(reports).toHaveLength(0);
  await page
    .getByRole("button", { name: "Intelligence AI", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Generate brief", exact: true })
    .click();
  await page.getByRole("button", { name: "Newsroom", exact: true }).click();
  reports.push({
    id: 7,
    model: "fixture-max",
    reasoning_effort: "max",
    style: "balanced",
    created_at: new Date().toISOString(),
    content: "## Completed background brief\n\n**Fixture research result.**",
    evidence: {},
  });
  job = {
    ...job,
    status: "completed",
    phase: "finished",
    analysis_id: 7,
    finished_at: new Date().toISOString(),
  };
  await expect(page.locator(".analysis-task-banner")).toContainText(
    "Research brief is ready",
    { timeout: 10000 },
  );
  await page.getByRole("button", { name: "View brief", exact: true }).click();
  await expect(
    page.getByRole("heading", {
      name: "Completed background brief",
      exact: true,
    }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("regular users can use shared Codex models but cannot manage the administrator login", async ({
  page,
}) => {
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const data: Record<string, unknown> = {
      "/api/me": user,
      "/api/ai/jobs/current": null,
      "/api/settings": {},
      "/api/codex/status": { logged_in: true, shared: true, can_manage: false },
      "/api/connections": {
        trading212: { configured: false, environment: "live" },
        openai: { configured: false, base_url: "https://api.openai.com/v1" },
      },
      "/api/ai/analyses": [],
      "/api/ai/prompts": { base: "Fixture", styles: {} },
      "/api/ai/models": [
        {
          id: "shared-model",
          name: "Shared model",
          efforts: ["max"],
          default_effort: "max",
        },
      ],
    };
    return route.fulfill({ json: data[path] ?? {} });
  });
  await page.goto("/#settings");
  await expect(
    page.getByText("Administrator connection · shared across the workspace"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Start device login", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Disconnect shared Codex", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Intelligence AI", exact: true })
    .click();
  await page.getByLabel("Provider", { exact: true }).selectOption("codex");
  await page
    .getByRole("button", { name: "Load model list", exact: true })
    .click();
  await expect(
    page.locator('datalist option[value="shared-model"]'),
  ).toHaveCount(1);
});
