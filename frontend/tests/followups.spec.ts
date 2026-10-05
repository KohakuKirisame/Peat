import { test, expect } from "@playwright/test";

test("report follow-ups keep their own conversation, run in background and reopen the right report", async ({
  page,
}) => {
  const user = {
    id: 1,
    username: "followup-fixture",
    role: "user",
    active: true,
    settings: {
      language: "en",
      theme: "dark",
      accent: "#8a9aff",
      style: "balanced",
      holding_horizon: "short",
      ai_provider: "openai",
      ai_model: "current-model",
      reasoning_effort: "high",
      ai_base_prompt: "",
      ai_style_prompts: {},
      ai_horizon_prompts: {},
    },
  };
  const reports = [2, 1].map((id) => ({
    id,
    provider: "openai",
    model: "report-model",
    reasoning_effort: "high",
    holding_horizon: "short",
    style: "balanced",
    created_at: `2026-10-0${id}T12:00:00Z`,
    content: id === 1 ? "## Original report" : "## Latest report",
    evidence: {},
  }));
  const discussions: Record<number, any[]> = {
    1: [],
    2: [
      {
        id: 99,
        status: "completed",
        question: "A separate report question",
        answer: "Separate report answer",
        model: "report-model",
        reasoning_effort: "high",
      },
    ],
  };
  let job: any = null;
  const sent: any[] = [];
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const discussion = path.match(/^\/api\/ai\/analyses\/(\d+)\/followups$/);
    if (discussion) {
      const id = Number(discussion[1]);
      if (route.request().method() === "POST") {
        const body = route.request().postDataJSON();
        sent.push(body);
        job = {
          id: `reply-${sent.length}`,
          kind: "followup",
          analysis_id: id,
          status: "running",
          phase: "replying",
          model: body.model,
          provider: body.provider,
          reasoning_effort: body.reasoning_effort,
          created_at: new Date().toISOString(),
        };
        discussions[id].push({
          id: sent.length,
          job_id: job.id,
          question: body.question,
          answer: null,
          status: "running",
          provider: body.provider,
          model: body.model,
          reasoning_effort: body.reasoning_effort,
          created_at: new Date().toISOString(),
        });
        return route.fulfill({ status: 202, json: job });
      }
      return route.fulfill({
        json: { items: discussions[id], next_before: null },
      });
    }
    if (path.endsWith("/cancel")) {
      job = {
        ...job,
        status: "cancelled",
        finished_at: new Date().toISOString(),
      };
      discussions[job.analysis_id].at(-1).status = "cancelled";
      return route.fulfill({ json: job });
    }
    const payload: Record<string, unknown> = {
      "/api/me": user,
      "/api/ai/jobs/current": job,
      "/api/ai/analyses": reports,
      "/api/ai/prompts": {},
      "/api/watchlist": [],
    };
    return route.fulfill({ json: payload[path] ?? {} });
  });
  await page.goto("/#intelligence");
  await page.locator(".archive-list button").last().click();
  await expect(page.locator(".brief-content")).toContainText("Original report");
  await page.locator(".followup-models summary").click();
  await page
    .locator(".followup-models")
    .getByPlaceholder("Choose or enter a model ID")
    .fill("followup-model");
  await page
    .locator(".followup-models")
    .getByLabel("Reasoning effort", { exact: true })
    .selectOption("max");
  await page
    .getByLabel("Follow-up question", { exact: true })
    .fill("Why should this holding be reduced?");
  await page
    .getByRole("button", { name: "Send question", exact: true })
    .click();
  await expect(page.locator(".analysis-task-banner")).toContainText(
    "Replying to your question",
  );
  await expect(
    page.getByRole("button", { name: "Stop reply", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Send question", exact: true }),
  ).toBeDisabled();
  expect(sent[0].model).toBe("followup-model");
  expect(sent[0].reasoning_effort).toBe("max");
  await page.getByRole("button", { name: "Watchlist", exact: true }).click();
  await page.reload();
  await expect(page.locator(".analysis-task-banner")).toContainText(
    "Replying to your question",
  );
  await page
    .getByRole("button", { name: "Stop generation", exact: true })
    .click();
  await expect(page.locator(".analysis-task-banner")).toContainText(
    "Generation stopped",
  );
  await page
    .getByRole("button", { name: "Intelligence AI", exact: true })
    .click();
  await page.locator(".archive-list button").last().click();
  await expect(page.locator(".followup-history")).toContainText(
    "Reply stopped",
  );
  await page.getByRole("button", { name: "Ask again", exact: true }).click();
  await expect(
    page.getByLabel("Follow-up question", { exact: true }),
  ).toHaveValue("Why should this holding be reduced?");
  await page
    .getByRole("button", { name: "Send question", exact: true })
    .click();
  expect(sent[0].request_id).not.toBe(sent[1].request_id);
  await page.locator(".archive-list button").first().click();
  await expect(page.locator(".followup-history")).toContainText(
    "A separate report question",
  );
  job = { ...job, status: "completed", finished_at: new Date().toISOString() };
  Object.assign(discussions[1].at(-1), {
    status: "completed",
    answer:
      "## Follow-up reasoning\n\n**Reduce in stages.**\n\n| Trigger | Action |\n| --- | --- |\n| Fixture condition | Review |\n\n<script>window.injected=true</script>",
  });
  await expect(page.locator(".analysis-task-banner")).toContainText(
    "Reply is ready",
    { timeout: 10000 },
  );
  // Completion leaves the report the user is reading in place until View reply is chosen.
  await expect(page.locator(".brief-content")).toContainText("Latest report");
  await page.getByRole("button", { name: "View reply", exact: true }).click();
  await expect(page.locator(".brief-content")).toContainText("Original report");
  await expect(
    page
      .locator(".followup-answer strong")
      .filter({ hasText: "Reduce in stages." }),
  ).toBeVisible();
  await expect(page.locator(".followup-answer table")).toContainText(
    "Fixture condition",
  );
  await expect(page.locator(".followup-answer script")).toHaveCount(0);
  await expect(page.locator(".followup-history")).not.toContainText(
    "A separate report question",
  );
  await page.reload();
  await page.locator(".archive-list button").last().click();
  await expect(page.locator(".followup-history")).toContainText(
    "Follow-up reasoning",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByLabel("Follow-up question", { exact: true })
    .scrollIntoViewIfNeeded();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../.cache/screenshots/followup-mobile-fixture.png",
    animations: "disabled",
  });
});
