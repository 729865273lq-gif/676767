import { expect, test } from "@playwright/test";

test("renders the sales workbench shell", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Sales workspace" })).toBeVisible();
});
