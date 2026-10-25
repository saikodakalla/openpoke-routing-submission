import { test, expect } from "@playwright/test";
import { systemState } from "../components/routing/system-state";
import type { Activity, Trace } from "../components/routing/types";

async function send(page: import("@playwright/test").Page, text: string) {
  await page.getByRole("textbox", { name: "Message", exact: true }).fill(text);
  await page.getByRole("button", { name: "Send message" }).click();
}

test("system view follows actual direct ownership, vector retrieval, past prompts and clarification continuation", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "System view", exact: true }).click();
  const panel = page.getByRole("complementary", {
    name: "System view",
    exact: true,
  });
  await expect(panel).toContainText("Ready for your request");
  await send(page, "Draft a follow-up in thread-0001");
  await expect(
    panel.getByRole("region", { name: "Selected task and agent" }),
  ).toContainText("task-0001");
  await expect(panel.locator('[data-layer="vector"]')).toHaveAttribute(
    "data-state",
    "skipped",
  );
  await expect(
    panel.getByRole("region", { name: "Request retrieval", exact: true }),
  ).toHaveCount(0);
  await page.screenshot({ path: "../../artifacts/ui-system-direct.png" });
  // Fresh conversation avoids the deliberately preserved pending context of the first prompt.
  await send(page, "Draft an email to Alice about the Hawaii trip");
  await expect(panel).toContainText("Waiting for your answer");
  await expect(
    panel.getByRole("group", { name: "PCA projection of stored task vectors" }),
  ).toBeVisible();
  await expect(
    panel.getByLabel("Projected request", { exact: true }),
  ).toHaveCount(1);
  await expect(panel.locator('[data-layer="vector"]')).toHaveAttribute(
    "data-state",
    "complete",
  );
  await expect(panel.getByRole("table")).toContainText(/Alice/i);
  await expect(panel.getByRole("table")).toContainText("Insufficient evidence");
  await page.screenshot({ path: "../../artifacts/ui-system-overview.png" });
  await panel.getByRole("button", { name: "View vector retrieval" }).click();
  await page.screenshot({ path: "../../artifacts/ui-system-vector.png" });
  const picker = panel.getByRole("combobox", {
    name: "Inspect request",
    exact: true,
  });
  const ids = await picker
    .locator("option")
    .evaluateAll((options) =>
      options.map((option) => (option as HTMLOptionElement).value),
    );
  await picker.selectOption(ids[0]);
  await expect(
    panel.getByRole("region", { name: "Selected task and agent" }),
  ).toContainText("task-0001");
  await expect(
    panel.getByRole("region", { name: "Request retrieval", exact: true }),
  ).toHaveCount(0);
  await send(page, "task-0003");
  await expect(
    panel.getByRole("region", { name: "Selected task and agent" }),
  ).toContainText("task-0003");
  await expect(picker).not.toHaveValue(ids[0]);
  await page.reload();
  await page.getByRole("button", { name: "System view", exact: true }).click();
  await expect(
    panel.getByRole("region", { name: "Selected task and agent" }),
  ).toContainText("task-0003");
  await panel
    .getByRole("combobox", { name: "Inspect request", exact: true })
    .selectOption(ids[1]);
  await expect(panel).toContainText("Clarification answered");
  await expect(
    panel.getByLabel("Projected request", { exact: true }),
  ).toHaveCount(1);
});

test("mobile system view is readable, closes with focus restored, and leaves the composer usable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await send(page, "Draft an email to Alice about the Hawaii trip");
  await expect(
    page
      .locator(".assistant-text")
      .filter({ hasText: "Do you mean Alice Chen or Alice Morgan?" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "System view", exact: true }).click();
  const panel = page.getByRole("complementary", {
    name: "System view",
    exact: true,
  });
  await expect(
    panel.getByRole("group", { name: "PCA projection of stored task vectors" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
  ).toBeFalsy();
  await page.screenshot({
    path: "../../artifacts/ui-system-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Close system view" }).click();
  await expect(
    page.getByRole("button", { name: "System view", exact: true }),
  ).toBeFocused();
  await expect(
    page.getByRole("textbox", { name: "Message", exact: true }),
  ).toBeVisible();
});

test("a controlled stream proves layer changes before a final response and errors do not claim success", async ({
  page,
}) => {
  // Gate delivery at the browser boundary so this covers real pending rendering deterministically.
  // Actual SQLite/Chroma payloads and SSE delivery are independently covered by integration tests.
  await page.addInitScript(() => {
    const original = window.fetch;
    window.fetch = async (input, init) => {
      if (String(input) !== "/api/chat/stream") return original(input, init);
      const id = JSON.parse(String(init?.body)).request_id;
      const stream = new ReadableStream({
        start(controller) {
          let count = 0;
          (window as any).emitTestOperation = (
            kind: string,
            status: string,
          ) => {
            const activity = {
              id: ++count,
              request_id: id,
              operation_id: kind,
              kind,
              label: `${kind} operation`,
              status,
              detail: null,
            };
            controller.enqueue(
              new TextEncoder().encode(
                `event: activity\ndata: ${JSON.stringify(activity)}\n\n`,
              ),
            );
          };
          (window as any).endTestStream = () => controller.close();
        },
      });
      return new Response(stream, {
        headers: { "Content-Type": "text/event-stream" },
      });
    };
  });
  await page.goto("/");
  await page.getByRole("button", { name: "System view", exact: true }).click();
  await send(page, "Follow this request live");
  await page.evaluate(() =>
    (window as any).emitTestOperation("lookup", "started"),
  );
  const panel = page.getByRole("complementary", {
    name: "System view",
    exact: true,
  });
  await expect(panel.locator('[data-layer="lookup"]')).toHaveAttribute(
    "data-state",
    "active",
  );
  await page.evaluate(() => {
    (window as any).emitTestOperation("lookup", "completed");
    (window as any).emitTestOperation("embedding", "started");
  });
  await expect(panel.locator('[data-layer="embedding"]')).toHaveAttribute(
    "data-state",
    "active",
  );
  await expect(panel.locator('[data-layer="lookup"]')).toHaveAttribute(
    "data-state",
    "complete",
  );
  await page.evaluate(() => {
    (window as any).emitTestOperation("embedding", "failed");
    (window as any).endTestStream();
  });
  await expect(panel.locator('[data-layer="embedding"]')).toHaveAttribute(
    "data-state",
    "failed",
  );
  await expect(panel).toContainText("Request interrupted");
});

test("layer reducer keeps failed tools visible and does not confuse earlier operations with current work", () => {
  const event = (
    kind: string,
    status: Activity["status"],
    id: string,
  ): Activity => ({
    id: 1,
    request_id: "r",
    operation_id: id,
    kind,
    label: kind,
    status,
    detail: null,
    created_at: "",
  });
  const state = systemState(
    [event("tool", "failed", "a"), event("model", "completed", "b")],
    false,
  );
  expect(state.states.execution).toBe("failed");
  expect(state.states.vector).toBe("waiting");
});

test("final execution state distinguishes blocked, running and recovered tool failures", () => {
  const trace = (status: string) =>
    ({
      path: "direct",
      task_id: "task-example",
      decision: "reuse",
      execution: { status },
    }) as Trace;
  expect(systemState([], false, trace("blocked")).states.execution).toBe(
    "blocked",
  );
  expect(systemState([], false, trace("running")).states.execution).toBe(
    "active",
  );
  expect(systemState([], false, trace("not_dispatched")).states.execution).toBe(
    "waiting",
  );
  expect(
    systemState([], false, trace("awaiting_approval")).states.execution,
  ).toBe("complete");
  const failed: Activity = {
    id: 1,
    request_id: "r",
    operation_id: "failed-tool",
    kind: "tool",
    label: "Tool failed",
    status: "failed",
    detail: null,
    created_at: "",
  };
  expect(
    systemState([failed], false, trace("completed")).states.execution,
  ).toBe("failed");
});

test("an ordinary email resolves a person naturally and dispatches without asking for internal identifiers", async ({
  page,
}) => {
  await page.goto("/");
  await send(
    page,
    "Send an email to alice about meeting up on Wednesday for drinks",
  );
  await expect(page.locator(".assistant-text")).toBeVisible();
  const needsPerson = (
    await page.locator(".assistant-text").innerText()
  ).includes("Do you mean Alice Chen or Alice Morgan?");
  // A repeated request may already have a verified social plan; do not require re-asking.
  if (needsPerson)
    await page.screenshot({ path: "../../artifacts/ui-natural-question.png" });
  await page.getByRole("button", { name: "System view", exact: true }).click();
  const panel = page.getByRole("complementary", {
    name: "System view",
    exact: true,
  });
  await panel
    .locator(".system-flow")
    .screenshot({ path: "../../artifacts/ui-flow-arrows.png" });
  if (needsPerson) await send(page, "Alice Chen");
  await expect(page.getByRole("region", { name: "Email draft" })).toContainText(
    "alice.chen@example.test",
  );
  await expect(page.locator(".assistant-text").last()).toContainText(
    "I drafted the email",
  );
  await expect(page.locator(".assistant-text").last()).not.toContainText(
    /task-|thread-|provide.*ID/i,
  );
  await expect(
    panel.getByRole("region", { name: "Selected task and agent" }),
  ).toContainText("drinks");
  await page.screenshot({ path: "../../artifacts/ui-natural-dispatch.png" });
});

test("a full saved name and a natural month identify the existing trip without a clarification", async ({
  page,
}) => {
  await page.goto("/");
  await send(page, "Write an email to Alice Chen about the June Hawaii trip");
  await expect(page.getByRole("region", { name: "Email draft" })).toContainText(
    "alice.chen@example.test",
  );
  await expect(page.locator(".assistant-text")).not.toContainText(
    /which|provide|task ID|contact email/i,
  );
  await page.getByRole("button", { name: "System view", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Selected task and agent" }),
  ).toContainText("task-0004");
});

test("keyword verification stays in the lookup layer without lighting up vector fallback", () => {
  const before: Activity = {
    id: 10,
    request_id: "r",
    operation_id: "v",
    kind: "verify",
    label: "Verify keyword matches",
    status: "started",
    detail: null,
    created_at: "",
  };
  const state = systemState([before], true);
  expect(state.states.lookup).toBe("active");
  expect(state.states.verify).toBe("waiting");
  const after: Activity = {
    ...before,
    id: 30,
    operation_id: "after",
    label: "Verify vector candidates",
  };
  const vector: Activity = {
    ...before,
    id: 20,
    operation_id: "search",
    kind: "vector",
    status: "completed",
  };
  expect(
    systemState([{ ...before, status: "completed" }, vector, after], true)
      .states.verify,
  ).toBe("active");
});
