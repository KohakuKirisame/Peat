import { test, expect } from "@playwright/test";

test("interface zoom enlarges 4K layout, persists per browser account and preserves responsive navigation", async ({
  page,
}) => {
  let uid = 1;
  let writes = 0;
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method === "PUT") writes++;
    const payload: Record<string, unknown> = {
      "/api/me": {
        id: uid,
        username: "zoom-fixture",
        role: "user",
        active: true,
        settings: {
          language: "en",
          theme: "dark",
          accent: "#8a9aff",
          style: "balanced",
          holding_horizon: "medium_long",
          ai_provider: "openai",
          ai_model: "fixture",
          reasoning_effort: "high",
          ai_base_prompt: "",
          ai_style_prompts: {},
          ai_horizon_prompts: {},
        },
      },
      "/api/ai/jobs/current": null,
      "/api/ai/analyses": [],
      "/api/ai/prompts": {},
      "/api/connections": {
        trading212: { configured: false },
        openai: { configured: false },
      },
    };
    return route.fulfill({ json: payload[path] ?? {} });
  });
  await page.setViewportSize({ width: 3840, height: 2160 });
  await page.goto("/#intelligence");
  const title = page.getByRole("heading", {
    name: "Peat intelligence",
    exact: true,
  });
  const initial = await title.boundingBox();
  const zoom = page.getByRole("combobox", {
    name: "Interface zoom",
    exact: true,
  });
  await zoom.selectOption("200");
  await expect(zoom).toHaveValue("200");
  expect((await title.boundingBox())!.height).toBeGreaterThan(
    initial!.height * 1.8,
  );
  expect(
    await page.evaluate(() => getComputedStyle(document.documentElement).zoom),
  ).toBe("2");
  const sidebar = await page.locator(".sidebar").boundingBox();
  expect(sidebar!.height).toBeLessThanOrEqual(2161);
  await page.screenshot({
    path: "../.cache/screenshots/zoom-4k-fixture.png",
    animations: "disabled",
  });
  await page.reload();
  await expect(zoom).toHaveValue("200");
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.locator("#interface-scale")).toHaveValue("200");
  await page.locator("#interface-scale").focus();
  await page.locator("#interface-scale").press("Home");
  await expect(zoom).toHaveValue("80");
  await page
    .getByRole("button", { name: "Reset interface zoom", exact: true })
    .click();
  await expect(zoom).toHaveValue("100");
  expect(writes).toBe(0);

  await page.goto("/#intelligence");
  await page.setViewportSize({ width: 1280, height: 900 });
  await zoom.selectOption("200");
  await expect(
    page.getByRole("button", { name: "Open navigation", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth + 1,
    ),
  ).toBe(true);
  await zoom.selectOption("125");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(zoom).toHaveValue("125");
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth + 1,
    ),
  ).toBe(true);
  await zoom.selectOption("200");
  await expect(
    page.getByRole("button", { name: "Open navigation", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth + 1,
    ),
  ).toBe(true);

  await page.screenshot({
    path: "../.cache/screenshots/zoom-mobile-fixture.png",
    animations: "disabled",
  });
  uid = 2;
  await page.reload();
  await expect(zoom).toHaveValue("100");
  uid = 1;
  await page.reload();
  await expect(zoom).toHaveValue("200");
});
