import { expect, test } from "@playwright/test";

test("runs a customer discovery task and surfaces review work", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Sales command center" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Customer Agent" })).toBeVisible();

  await page.getByLabel("Product").fill("Industrial LED lighting");
  await page.getByLabel("Target country").selectOption("Germany");
  await page.getByRole("button", { name: "Start discovery" }).click();

  await expect(page.getByText("Discovery complete")).toBeVisible();
  await expect(page.getByRole("cell", { name: "LumenHaus GmbH" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Show priority leads" })).toBeVisible();

  await page.getByRole("button", { name: "Show priority leads" }).click();
  await expect(page.getByRole("cell", { name: "Nordlicht Handel" })).toHaveCount(0);

  await page.getByRole("button", { name: "Review 8 drafts" }).click();
  await expect(page.getByText("Email review queue")).toBeVisible();
});
