import { test, expect } from "@playwright/test";

test("Pie groups expand, split holdings, search children and keep their charts on mobile", async ({
  page,
}) => {
  // Synthetic portfolio stays inside this test's intercepted responses.
  const holding = (
    ticker: string,
    name: string,
    quantity: number,
    value: number,
    pnl: number | null,
  ) => ({
    ticker,
    name,
    quantity,
    value,
    pnl,
    price: 100,
    currency: "USD",
    account_currency: "EUR",
    chart_symbol: ticker.split("_")[0],
  });
  const apple = holding("AAPL_US_EQ", "Apple", 10, 1000, 200);
  const microsoft = holding("MSFT_US_EQ", "Microsoft", 2, 400, 100);
  const user = {
    id: 1,
    username: "pie-test-fixture",
    role: "user",
    active: true,
    settings: {
      theme: "dark",
      accent: "#8a9aff",
      language: "en",
      portfolio_interval: 60,
    },
  };
  const portfolio = {
    snapshot: {
      updated_at: "2026-10-05T12:00:00Z",
      data: {
        provider: "trading212",
        environment: "demo",
        currency: "EUR",
        as_of: "2026-10-05T12:00:00Z",
        total_value: 1415,
        invested: 1100,
        unrealized: 300,
        realized: 0,
        cash: 0,
        market_value: 1400,
        positions: [apple, microsoft],
        pie_status: { state: "ready", error: null },
        ungrouped_positions: [
          {
            ...apple,
            quantity: 5,
            value: 500,
            pnl: null,
            partial_position: true,
          },
        ],
        pies: [
          {
            id: 1,
            name: "Growth",
            value: 700,
            pnl: 160,
            cash: 15,
            as_of: "2026-10-05T12:00:00Z",
            positions: [
              { ...apple, quantity: 3, value: 300, pnl: 60 },
              microsoft,
            ],
          },
          {
            id: 2,
            name: "Income",
            value: 200,
            pnl: 50,
            cash: 0,
            as_of: "2026-10-05T12:00:00Z",
            positions: [{ ...apple, quantity: 2, value: 200, pnl: 50 }],
          },
        ],
      },
    },
    timeline: [],
    statement: { rows: 0 },
  };
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const data: Record<string, unknown> = {
      "/api/me": user,
      "/api/portfolio": portfolio,
      "/api/markets": { data: { quotes: [] }, exchanges: [] },
      "/api/news": { items: [], total: 0 },
      "/api/ai/analyses": [],
      "/api/settings": {},
      "/api/charts": {
        data: {
          symbol: "AAPL",
          name: "Apple",
          currency: "USD",
          timezone: "America/New_York",
          source: "TEST FIXTURE",
          status: "delayed",
          candles: [
            {
              time: 1750000000,
              open: 100,
              high: 105,
              low: 99,
              close: 103,
              volume: 100,
            },
          ],
        },
      },
    };
    return route.fulfill({ json: data[path] ?? {} });
  });
  await page.goto("/#portfolio");
  await expect(
    page.getByRole("button", { name: "Expand pie Growth", exact: true }),
  ).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator("#pie-holdings-1")).toBeHidden();
  await expect(page.locator(".individual-holdings")).toContainText(
    "5 shares · outside pies",
  );
  await expect(page.locator(".individual-holdings")).not.toContainText(
    "10 shares",
  );
  await page
    .getByRole("button", { name: "Expand pie Growth", exact: true })
    .click();
  await expect(page.locator("#pie-holdings-1")).toBeVisible();
  await expect(page.locator("#pie-holdings-1")).toContainText("3 shares");
  await expect(page.locator("#pie-holdings-1")).toContainText("Microsoft");
  await page
    .locator("#pie-holdings-1")
    .getByRole("button", { name: /Apple/ })
    .click();
  await expect(
    page.getByRole("heading", { name: "Apple · Price history" }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "AAPL candlestick price history" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Collapse pie Growth", exact: true })
    .click();
  await expect(page.locator("#pie-holdings-1")).toBeHidden();
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await page.getByLabel("Find a holding", { exact: true }).fill("MSFT");
  await expect(page.locator("#pie-holdings-1")).toBeVisible();
  await expect(page.locator("#pie-holdings-1")).toContainText("Microsoft");
  await expect(page.getByRole("button", { name: /pie Income/ })).toHaveCount(0);
  await page.getByLabel("Find a holding", { exact: true }).fill("");
  await page
    .getByRole("button", { name: "Expand pie Income", exact: true })
    .click();
  await expect(page.locator("#pie-holdings-2")).toContainText("2 shares");
  await page.screenshot({
    path: "../.cache/screenshots/pies-test-fixture.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Switch to Chinese" }).click();
  await expect(
    page.getByRole("button", { name: "展开 Pie Growth", exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole("button", { name: "展开 Pie Growth", exact: true })
    .click();
  await expect(page.locator("#pie-holdings-1")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "../.cache/screenshots/pies-mobile-test-fixture.png",
    fullPage: true,
    animations: "disabled",
  });
  expect(errors).toEqual([]);
});
