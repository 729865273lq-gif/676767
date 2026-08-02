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
  await page.route(/http:\/\/(localhost|127\.0\.0\.1):8000\/discovery\/organizations\/org-1\/leads/, async (route) => {
    expect(route.request().headers().authorization).toBe("Bearer local-session-token");
    await route.fulfill({
      contentType: "application/json",
      status: 200,
      body: JSON.stringify([]),
    });
  });
  await page.route(/http:\/\/(localhost|127\.0\.0\.1):8000\/discovery\/organizations\/org-1\/email-drafts/, async (route) => {
    expect(route.request().headers().authorization).toBe("Bearer local-session-token");
    await route.fulfill({
      contentType: "application/json",
      status: 200,
      body: JSON.stringify([]),
    });
  });

  await page.goto("/login");
  await page.getByRole("button", { name: "第一次使用？创建工作区" }).click();
  await page.getByLabel("组织名称").fill("Nova Export");
  await page.getByLabel("姓名").fill("Mia Chen");
  await page.getByLabel("邮箱").fill("mia@example.com");
  await page.getByLabel("密码").fill("a-long-local-password");
  await page.getByRole("button", { name: "创建账号" }).click();

  await expect(page.getByRole("heading", { name: "外贸客户开发工作台" })).toBeVisible();
  expect(membershipRequested).toBe(true);
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("trade-axis-session")))
    .toContain('"organization_role":"admin"');
});
