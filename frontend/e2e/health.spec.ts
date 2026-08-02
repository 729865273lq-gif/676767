import { expect, test } from "@playwright/test";

test("runs a customer discovery task and surfaces review work", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      "trade-axis-session",
      JSON.stringify({
        access_token: "test-token",
        user_id: "user-1",
        organization_id: "org-1",
        organization_role: "admin",
      })
    );
  });
  await page.route(/\/platform\/organizations\/org-1\/product-lines$/, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "product-1",
          name: "Industrial LED lighting",
          description: "Commercial and industrial retrofit lighting.",
          product_keywords: ["LED floodlight", "warehouse lighting"],
          buyer_profiles: ["Distributor", "Project buyer"],
          target_regions: ["Europe", "North America"],
          is_active: true,
          suppliers: [],
        },
      ]),
    });
  });
  await page.route(/\/discovery\/organizations\/org-1\/runs$/, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      status: 201,
      body: JSON.stringify({
        workflow_run_id: "run-1",
        query: "Industrial LED lighting Distributor Germany",
        lead_count: 2,
        state: "completed",
      }),
    });
  });
  await page.route(/\/discovery\/organizations\/org-1\/leads$/, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "lead-1",
          workflow_run_id: "run-1",
          product_line_id: "product-1",
          company_name: "LumenHaus GmbH",
          website: "https://lumenhaus.example",
          target_market: "Germany",
          buyer_profile: "Distributor",
          score: 80,
          bucket: "needs_enrichment",
          status: "new",
          owner_user_id: null,
          notes: "",
          reasons: ["product or business fit evidence recorded"],
          missing_signals: ["decision-maker identification attempt"],
          evidence: [
            {
              source_url: "https://lumenhaus.example",
              source_excerpt: "Commercial lighting distributor",
              signal_name: "search_result",
            },
          ],
        },
        {
          id: "lead-2",
          workflow_run_id: "run-1",
          product_line_id: "product-1",
          company_name: "Rheinland Industriebedarf",
          website: "https://rheinland.example",
          target_market: "Germany",
          buyer_profile: "Project buyer",
          score: 92,
          bucket: "priority_recommendation",
          status: "new",
          owner_user_id: null,
          notes: "",
          reasons: ["verified website", "usable contact channel"],
          missing_signals: [],
          evidence: [
            {
              source_url: "https://rheinland.example",
              source_excerpt: "Lists warehouse lighting retrofit projects",
              signal_name: "search_result",
            },
          ],
        },
      ]),
    });
  });
  await page.route(/\/discovery\/organizations\/org-1\/email-drafts$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "外贸客户开发工作台" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "客户搜索 Agent" })).toBeVisible();

  await page.getByLabel("搜索产品线").selectOption("product-1");
  await page.getByLabel("搜索目标市场").fill("Germany");
  await page.getByLabel("搜索客户类型").selectOption("Distributor");
  await page.getByRole("button", { name: "开始搜索客户" }).click();

  await expect(page.getByText("搜索完成")).toBeVisible();
  await expect(page.locator("tbody").getByText("LumenHaus GmbH")).toBeVisible();
  await expect(page.getByRole("button", { name: "只看优先客户" })).toBeVisible();

  await page.getByRole("button", { name: "只看优先客户" }).click();
  await expect(page.locator("tbody").getByText("LumenHaus GmbH")).toHaveCount(0);

  await page.getByRole("button", { name: "审核 0 封草稿" }).click();
  await expect(page.getByText("邮件审核队列")).toBeVisible();
  await expect(page.getByText("暂无待审核草稿")).toBeVisible();
});
