import { expect, test } from "@playwright/test";

test("serves a stable Simplified Chinese document language", async ({ page }) => {
  await page.goto("/login");

  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
});
