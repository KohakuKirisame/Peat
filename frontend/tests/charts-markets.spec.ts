import { test, expect } from "@playwright/test";

const user = {
  id: 1,
  username: "chart-fixture",
  role: "user",
  active: true,
  settings: {
    language: "zh",
    theme: "light",
    accent: "#8a9aff",
    portfolio_interval: 60,
  },
};

test("switching from Apple to Airbus uses its Paris listing and clears obsolete chart metadata", async ({
  page,
}) => {
  const requests: string[] = [];
  const holding = (
    ticker: string,
    name: string,
    currency: string,
    chart_symbol: string,
  ) => ({
    ticker,
    name,
    currency,
    chart_symbol,
    account_currency: "EUR",
    quantity: 1,
    price: 100,
    value: 100,
    pnl: 0,
  });
  let failAirbus = false;
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/charts") {
      const symbol = url.searchParams.get("symbol")!;
      requests.push(symbol);
      if (symbol === "AIR.PA" && failAirbus)
        return route.fulfill({
          status: 502,
          json: { detail: "chart_unavailable" },
        });
      return route.fulfill({
        json: {
          data: {
            symbol,
            name: symbol === "AAPL" ? "Apple Inc." : "Airbus SE",
            currency: symbol === "AAPL" ? "USD" : "EUR",
            timezone: symbol === "AAPL" ? "America/New_York" : "Europe/Paris",
            source: "TEST FIXTURE",
            status: "delayed",
            candles: [0, 1, 2].map((i) => ({
              time: 1791190800 + i * 900,
              open: 100,
              high: 104,
              low: 99,
              close: 102,
              volume: 50,
            })),
          },
        },
      });
    }
    const payload: Record<string, unknown> = {
      "/api/me": user,
      "/api/ai/jobs/current": null,
      "/api/news": { items: [] },
      "/api/ai/analyses": [],
      "/api/markets": { data: { quotes: [] }, exchanges: [] },
      "/api/portfolio": {
        snapshot: {
          data: {
            currency: "EUR",
            market_value: 200,
            positions: [
              holding("AAPL_US_EQ", "Apple", "USD", "AAPL"),
              holding("AIRp_EQ", "Airbus", "EUR", "AIR.PA"),
            ],
          },
        },
        timeline: [],
        statement: { rows: 0 },
      },
    };
    return route.fulfill({ json: payload[url.pathname] ?? {} });
  });
  await page.goto("/#portfolio");
  await page.getByRole("button", { name: /Apple.*1 股/ }).click();
  await expect(page.locator(".symbol-form")).toContainText("Apple Inc.");
  failAirbus = true;
  await page.getByRole("button", { name: /Airbus.*1 股/ }).click();
  await expect(page.getByLabel("行情代码", { exact: true })).toHaveValue(
    "AIR.PA",
  );
  await expect(page.locator(".price-chart [role=alert]")).toBeVisible();
  await expect(page.locator(".price-chart")).not.toContainText("Apple Inc.");
  await expect(page.locator(".price-chart")).not.toContainText(
    "America/New_York",
  );
  failAirbus = false;
  await page
    .locator(".price-chart")
    .getByRole("button", { name: "重试", exact: true })
    .click();
  await expect(
    page.getByRole("img", { name: "AIR.PA K 线历史行情" }),
  ).toBeVisible();
  await expect(page.locator(".symbol-form")).toContainText(
    "Airbus SE · AIR.PA · EUR · Europe/Paris",
  );
  await page.getByRole("button", { name: "15分", exact: true }).click();
  await expect(page.getByLabel("行情范围")).toHaveValue("5d");
  await expect(
    page.getByRole("img", { name: "AIR.PA K 线历史行情" }),
  ).toBeVisible();
  expect(requests).not.toContain("AIRp_EQ");
  await page
    .locator(".price-chart")
    .screenshot({ path: "../.cache/screenshots/airbus-chart-fixture.png" });
});

test("market pulse shows dated precise yield and commodity values on hover, keyboard and touch", async ({
  page,
}) => {
  const quotes = [
    {
      symbol: "UST10",
      name: "US 10Y Treasury",
      kind: "yield",
      unit: "%",
      observations: [
        { date: "2026-10-01T00:00:00", value: 4.0123 },
        { date: "2026-10-02T00:00:00", value: 4.0825 },
      ],
    },
    {
      symbol: "NG=F",
      name: "Natural gas",
      kind: "futures",
      unit: "USD/MMBtu",
      timezone: "America/New_York",
      observations: [
        { date: "2026-10-01T12:00:00Z", value: 3.0012 },
        { date: "2026-10-02T12:00:00Z", value: 3.1234 },
      ],
    },
    {
      symbol: "GC=F",
      name: "Gold",
      kind: "futures",
      unit: "USD/oz",
      timezone: "America/New_York",
      observations: [
        { date: "2026-10-01T12:00:00Z", value: 2500.125 },
        { date: "2026-10-02T12:00:00Z", value: 2510.375 },
      ],
    },
  ].map((q) => ({
    ...q,
    value: q.observations[1].value,
    status: "daily",
    series: [999, 999],
  }));
  await page.route("**/api/**", (route) => {
    const payload: Record<string, unknown> = {
      "/api/me": user,
      "/api/ai/jobs/current": null,
      "/api/markets": { data: { quotes }, exchanges: [] },
    };
    return route.fulfill({
      json: payload[new URL(route.request().url()).pathname] ?? {},
    });
  });
  await page.goto("/#markets");
  for (const quote of quotes) {
    const curve = page.getByRole("slider", {
      name: `${quote.name} · 历史曲线`,
    });
    const rect = await curve.boundingBox();
    await curve.hover({
      position: { x: rect!.width - 2, y: rect!.height / 2 },
    });
    const tooltip = page.getByRole("tooltip");
    await expect(tooltip.locator("time")).toHaveAttribute(
      "datetime",
      quote.observations[1].date,
    );
    await expect(tooltip).toContainText(quote.unit);
    await expect(tooltip).not.toContainText("999");
    await expect(curve).toHaveAttribute(
      "aria-valuetext",
      new RegExp(
        quote.observations[1].value
          .toLocaleString("en-GB", { maximumFractionDigits: 4 })
          .replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
      ),
    );
    await page.mouse.move(0, 0);
    await curve.focus();
    await curve.press("Home");
    await expect(page.getByRole("tooltip").locator("time")).toHaveAttribute(
      "datetime",
      quote.observations[0].date,
    );
    await curve.press("ArrowRight");
    await expect(page.getByRole("tooltip").locator("time")).toHaveAttribute(
      "datetime",
      quote.observations[1].date,
    );
    await curve.press("Escape");
    await expect(page.getByRole("tooltip")).toHaveCount(0);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  const gold = page.getByRole("slider", { name: "Gold · 历史曲线" });
  await gold.scrollIntoViewIfNeeded();
  const rect = await gold.boundingBox();
  await gold.dispatchEvent("pointerdown", {
    pointerType: "touch",
    clientX: rect!.x + 1,
    clientY: rect!.y + 10,
  });
  await expect(page.getByRole("tooltip")).toContainText("2,500.125");
  await expect(page.getByRole("tooltip").locator("time")).toContainText(
    "08:00",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../.cache/screenshots/market-tooltip-mobile-fixture.png",
    animations: "disabled",
  });
});
