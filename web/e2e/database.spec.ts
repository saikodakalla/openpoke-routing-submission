import { test, expect } from "@playwright/test";
async function send(page: import("@playwright/test").Page, text: string) {
  await page.getByRole("textbox", { name: "Message", exact: true }).fill(text);
  await page.getByRole("button", { name: "Send message" }).click();
}
test("SQLite image opens real rows and schema with navigable owner foreign keys", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "System view", exact: true }).click();
  await page.getByRole("button", { name: "Open SQLite database" }).click();
  await expect(
    page.getByRole("region", { name: "SQLite database inspector" }),
  ).toBeVisible();
  await expect(page.getByRole("table")).toContainText("owner_id");
  await page
    .getByRole("button", { name: "agent-0004 ↗", exact: true })
    .click();
  await expect(
    page.getByRole("combobox", { name: "Database table" }),
  ).toHaveValue("agents");
  await expect(page.getByRole("table")).toContainText(
    "Execution: Hawaii · Alice Chen · June",
  );
  await page.getByRole("button", { name: "Schema & keys" }).click();
  await expect(page.getByRole("table")).toContainText("PK 1");
  await page.screenshot({
    path: "../../artifacts/ui-sqlite-inspector.png",
    fullPage: true,
  });
});
test("usual pizza tie asks a factual question and a natural answer prepares the saved order", async ({
  page,
}) => {
  await page.goto("/");
  await send(page, "Order pizza from my usual spot");
  await expect(page.locator(".assistant-text")).toContainText("equally often");
  await page.reload();
  await send(page, "dominoes");
  await expect(
    page.getByRole("region", { name: "Prepared order" }),
  ).toContainText("Domino's");
  await expect(
    page.getByRole("region", { name: "Prepared order" }),
  ).toContainText("Medium thin-crust margherita");
  await page.screenshot({
    path: "../../artifacts/ui-pizza-clarification.png",
    fullPage: true,
  });
});
test("mobile database inspection scrolls records without overflowing the page", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "System view", exact: true }).click();
  await page.getByRole("button", { name: "Database", exact: true }).click();
  await expect(page.getByRole("table")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    ),
  ).toBeFalsy();
});
