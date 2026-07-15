import { expect, test } from "@playwright/test";

test("registers a workspace, stores the session, and opens the dashboard", async ({ page }) => {
  let membershipRequested = false;

  await page.route(/http:\/\/(localhost|127\.0\.0\.1):8000\/platform\/auth\/register/, async (route) => {
    const payload = route.request().postDataJSON();
    expect(payload).toMatchObject({
      organization_name: "Nova Export",
      display_name: "Mia Chen",
      email: "mia@example.com",
      password: "a-long-local-password",
    });
    await route.fulfill({
      contentType: "application/json",
      status: 201,
      body: JSON.stringify({
        access_token: "local-session-token",
        user_id: "user-1",
        organization_id: "org-1",
      }),
    });
  });

  await page.route(/http:\/\/(localhost|127\.0\.0\.1):8000\/platform\/organizations\/org-1\/membership/, async (route) => {
    membershipRequested = true;
    expect(route.request().headers().authorization).toBe("Bearer local-session-token");
    await route.fulfill({
      contentType: "application/json",
      status: 200,
      body: JSON.stringify({ organization_id: "org-1", role: "admin" }),
    });
  });
  await page.route(/http:\/\/(localhost|127\.0\.0\.1):8000\/platform\/organizations\/org-1\/product-lines/, async (route) => {
    expect(route.request().headers().authorization).toBe("Bearer local-session-token");
    await route.fulfill({
      contentType: "application/json",
      status: 200,
      body: JSON.stringify([]),
    });
  });

  await page.goto("/login");
  await page.getByRole("button", { name: "New here? Create workspace" }).click();
  await page.getByLabel("Organization").fill("Nova Export");
  await page.getByLabel("Name").fill("Mia Chen");
  await page.getByLabel("Email").fill("mia@example.com");
  await page.getByLabel("Password").fill("a-long-local-password");
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page.getByRole("heading", { name: "Sales command center" })).toBeVisible();
  expect(membershipRequested).toBe(true);
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("trade-axis-session")))
    .toContain('"organization_role":"admin"');
});
