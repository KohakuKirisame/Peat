import { test, expect } from "@playwright/test";

test("registration, responsive UI, preferences, prompts, chart controls and local console", async ({
  page,
}, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Make yourself at home." }),
  ).toBeVisible();
  await page.screenshot({
    path: "../.cache/screenshots/auth.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByLabel("Username", { exact: true }).fill("browser-test-owner");
  await page
    .getByLabel("Password", { exact: true })
    .fill("disposable-fixture-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "A clearer view of your investments." }),
  ).toBeVisible();
  await expect(page.getByText("Your holdings will live here")).toBeVisible();
  await page.screenshot({
    path: "../.cache/screenshots/overview.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Dark", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByLabel("Interface language").selectOption("zh");
  await expect(
    page.getByRole("heading", { name: "设置", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "浅色", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByLabel("界面语言").selectOption("en");
  await page
    .getByRole("button", { name: "Intelligence", exact: false })
    .first()
    .click();
  await page
    .getByPlaceholder("Choose or enter a model ID")
    .fill("fixture-model");
  await page
    .getByLabel("Reasoning effort", { exact: true })
    .selectOption("high");
  await page.getByRole("button", { name: "Aggressive", exact: true }).click();
  await page.getByRole("button", { name: "Edit research prompts" }).click();
  await page
    .getByLabel("Base research prompt")
    .fill(
      "Custom test research prompt. Review yields, energy and portfolio evidence.",
    );
  await page.getByRole("button", { name: "Save prompts", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Prompts saved");
  await page.reload();
  await expect(page.getByPlaceholder("Choose or enter a model ID")).toHaveValue(
    "fixture-model",
  );
  await expect(
    page.getByLabel("Reasoning effort", { exact: true }),
  ).toHaveValue("high");
  await page.getByRole("button", { name: "Edit research prompts" }).click();
  await expect(page.getByLabel("Base research prompt")).toHaveValue(
    /Custom test research/,
  );
  await page.screenshot({
    path: "../.cache/screenshots/intelligence.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Watchlist", exact: true }).click();
  await page.getByLabel("Symbol", { exact: true }).fill("AAPL");
  await page.getByLabel("Company", { exact: true }).fill("Apple");
  await page
    .getByLabel("Industry", { exact: true })
    .fill("Consumer electronics");
  await page.getByRole("button", { name: "Add company", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Apple", exact: true }),
  ).toBeVisible();
  // Deterministic OHLC fixture is confined to this test; no product demo data exists.
  await page.route("**/api/charts?**", (route) =>
    route.fulfill({
      json: {
        data: {
          symbol: "AAPL",
          name: "Apple",
          currency: "USD",
          timezone: "America/New_York",
          status: "delayed",
          source: "TEST FIXTURE",
          as_of: "2026-10-02T00:00:00Z",
          candles: Array.from({ length: 40 }, (_, i) => ({
            time: 1750000000 + i * 86400,
            open: 100 + i,
            high: 103 + i,
            low: 98 + i,
            close: 102 + i,
            volume: 1000 + i,
          })),
        },
      },
    }),
  );
  await page.getByRole("button", { name: "Explore price history" }).click();
  await expect(
    page.getByRole("img", { name: "AAPL candlestick price history" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "1m", exact: true }).click();
  await expect(page.getByLabel("Chart range")).toHaveValue("1d");
  await page.getByRole("button", { name: "1W", exact: true }).click();
  await expect(page.getByLabel("Chart range")).toHaveValue("1y");
  await page.screenshot({
    path: "../.cache/screenshots/chart-test-fixture.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Console", exact: true }).click();
  await page.getByLabel("Shell command").fill("echo peat-console-ok");
  await page.getByRole("button", { name: "Run", exact: true }).click();
  await expect(page.locator(".job-output pre")).toContainText(
    "peat-console-ok",
    { timeout: 15000 },
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "A clearer view of your investments." }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../.cache/screenshots/mobile.png",
    fullPage: true,
    animations: "disabled",
  });
  expect(errors).toEqual([]);
});
