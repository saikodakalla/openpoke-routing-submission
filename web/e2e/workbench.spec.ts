import { test, expect } from "@playwright/test";

async function send(page: import("@playwright/test").Page, text: string) {
  await page.getByRole("textbox", { name: "Message", exact: true }).fill(text);
  await page.getByRole("button", { name: "Send message" }).click();
}

test("plain chat has no branding, seed counters or scenario controls; typed work still needs approval", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "How can I help?" }),
  ).toBeVisible();
  await expect(page.locator("body")).not.toContainText(
    /OpenPoke|Routing lab|Try a scenario|durable tasks|600/,
  );
  await expect(page.getByRole("navigation")).toHaveCount(0);
  await page.screenshot({
    path: "../../artifacts/ui-chat-empty.png",
    fullPage: true,
  });
  await send(page, "Draft a follow-up in thread-0001");
  await expect(page.getByRole("region", { name: "Email draft" })).toContainText(
    "alice.chen@example.test",
  );
  await expect(page.getByText("Awaiting your approval")).toBeVisible();
  await page.locator(".activity-log > summary").click();
  await expect(
    page.getByRole("list", { name: "Request activity" }),
  ).toContainText("Creating an email draft");
  await expect(
    page.getByRole("list", { name: "Request activity" }),
  ).not.toContainText("Searching task memory");
  await page.screenshot({
    path: "../../artifacts/ui-desktop.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Approve and send", exact: true })
    .click();
  await expect(
    page
      .locator(".assistant-text")
      .filter({ hasText: "Synthetic draft sent with your approval." }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve and send", exact: true }),
  ).toHaveCount(0);
});

test("real vector activity is inline, details open on demand, and clarification survives reload", async ({
  page,
}) => {
  await page.goto("/");
  await send(page, "Draft an email to Alice about the Hawaii trip");
  await expect(
    page
      .locator(".assistant-text")
      .filter({ hasText: "Do you mean Alice Chen or Alice Morgan?" }),
  ).toBeVisible();
  await expect(
    page.getByRole("complementary", { name: "Routing evidence" }),
  ).toHaveCount(0);
  await page.locator(".activity-log > summary").click();
  await expect(
    page.getByRole("list", { name: "Request activity" }),
  ).toContainText("Embedding the request");
  await expect(
    page.getByRole("list", { name: "Request activity" }),
  ).toContainText("Searching task memory");
  await page.getByRole("button", { name: "View memory search" }).click();
  await page.getByRole("button", { name: "Explore vector database" }).click();
  await expect(
    page.getByRole("group", { name: "PCA projection of stored task vectors" }),
  ).toBeVisible();
  await page
    .getByLabel("Inspect a stored task", { exact: true })
    .selectOption("task-0005");
  await expect(page.locator(".point-detail")).toContainText(
    "Kyoto autumn reunion",
  );
  await page.screenshot({ path: "../../artifacts/ui-vector.png", fullPage: true });
  await page.reload();
  await expect(
    page
      .locator(".assistant-text")
      .filter({ hasText: "Do you mean Alice Chen or Alice Morgan?" }),
  ).toBeVisible();
  await send(page, "task-0003");
  await expect(page.getByRole("region", { name: "Email draft" })).toContainText(
    "alice.morgan@example.test",
  );
});

test("new chat clears conversation scope without deleting task data or sending hidden metadata", async ({
  page,
}) => {
  await page.goto("/");
  await send(page, "Draft an email to Alice about the Hawaii trip");
  await expect(
    page
      .locator(".assistant-text")
      .filter({ hasText: "Do you mean Alice Chen or Alice Morgan?" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "New chat" }).click();
  await expect(
    page.getByRole("heading", { name: "How can I help?" }),
  ).toBeVisible();
  const sent = page.waitForRequest(
    (request) =>
      request.url().endsWith("/api/chat/stream") && request.method() === "POST",
  );
  await send(page, "Unidentified telescope adjustment");
  const payload = (await sent).postDataJSON();
  expect(payload.thread_id).toBeUndefined();
  expect(payload.task_id).toBeUndefined();
  expect(payload.new_work).toBeUndefined();
  await expect(page.getByRole("checkbox")).toHaveCount(0);
  await expect(page.locator(".assistant-text")).toContainText(
    "What would you like me to do",
  );
});

test("mobile chat has no horizontal overflow and supports multiline messages", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const input = page.getByRole("textbox", { name: "Message", exact: true });
  await expect(input).toBeVisible();
  await input.fill("First line");
  await input.press("Shift+Enter");
  await input.pressSequentially("Second line");
  await expect(input).toHaveValue("First line\nSecond line");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    ),
  ).toBeFalsy();
  await page.screenshot({ path: "../../artifacts/ui-mobile.png", fullPage: true });
});

test("a failed history refresh after success never marks the action failed or restores its request", async ({
  page,
}) => {
  let failRefresh = false;
  await page.route("**/api/chat/history?*", (route) =>
    failRefresh ? route.fulfill({ status: 503, body: "{}" }) : route.continue(),
  );
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "How can I help?" }),
  ).toBeVisible();
  failRefresh = true;
  await send(page, "Draft a follow-up in thread-0001");
  await expect(page.getByRole("region", { name: "Email draft" })).toBeVisible();
  await expect(page.locator(".chat-error[role=alert]")).toContainText(
    "Your request completed",
  );
  await expect(
    page.getByRole("textbox", { name: "Message", exact: true }),
  ).toHaveValue("");
  await expect(page.getByText("Couldn’t complete the request")).toHaveCount(0);
});
