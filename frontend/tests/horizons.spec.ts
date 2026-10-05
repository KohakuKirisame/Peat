import { test, expect } from "@playwright/test";

test("holding horizon is independent of style and archived briefs retain their original horizon", async ({
  page,
}) => {
  const user = {
    id: 1,
    username: "horizon-fixture",
    role: "user",
    active: true,
    settings: {
      theme: "dark",
      accent: "#8a9aff",
      language: "zh",
      style: "aggressive",
      holding_horizon: "medium_long",
      ai_provider: "openai",
      ai_model: "fixture",
      reasoning_effort: "high",
      ai_base_prompt: "",
      ai_style_prompts: {},
      ai_horizon_prompts: {},
    },
  };
  const reports = [
    {
      id: 2,
      holding_horizon: "ultra_short",
      style: "balanced",
      model: "fixture",
      reasoning_effort: "high",
      created_at: "2026-10-05T12:00:00Z",
      content: "## 周期测试简报",
      evidence: {
        prompts: {
          base: "BASE",
          style: "STYLE",
          horizon: "ORIGINAL HORIZON PROMPT",
        },
      },
    },
    {
      id: 1,
      holding_horizon: null,
      style: "balanced",
      model: "fixture",
      reasoning_effort: "high",
      created_at: "2026-10-01T12:00:00Z",
      content: "## 旧版简报",
      evidence: {},
    },
  ];
  await page.route("**/api/**", (route) => {
    const payload: Record<string, unknown> = {
      "/api/me": user,
      "/api/ai/jobs/current": null,
      "/api/ai/analyses": reports,
      "/api/ai/prompts": { base: "BASE", styles: {}, horizons: {} },
    };
    return route.fulfill({
      json: payload[new URL(route.request().url()).pathname] ?? {},
    });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#intelligence");
  await expect(
    page.getByRole("button", { name: "中长线", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "短线", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "短线", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("button", { name: "激进", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".brief-meta")).toContainText("超短线");
  await page.getByRole("button", { name: "查看依据与当时提示词" }).click();
  await page.getByText("本次简报使用的提示词", { exact: true }).click();
  await expect(page.locator(".evidence pre")).toContainText(
    "ORIGINAL HORIZON PROMPT",
  );
  await page.locator(".archive-list button").last().click();
  await expect(page.locator(".brief-content")).toContainText("旧版简报");
  await expect(page.locator(".brief-meta .tag")).toHaveCount(1);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "超短线", exact: true })
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: "../.cache/screenshots/horizon-mobile-fixture.png",
    animations: "disabled",
  });
});
