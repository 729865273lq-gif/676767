import { expect, test } from "@playwright/test";

test("creates a product line and displays discovered leads", async ({ page }) => {
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
    if (route.request().method() === "GET") {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
      return;
    }

    const payload = route.request().postDataJSON();
    expect(payload).toMatchObject({
      name: "Industrial LED lighting",
      product_keywords: ["LED floodlight", "warehouse lighting"],
      buyer_profiles: ["Distributor", "Project buyer"],
      target_regions: ["Europe", "North America"],
    });
    await route.fulfill({
      contentType: "application/json",
      status: 201,
      body: JSON.stringify({
        id: "product-1",
        name: payload.name,
        description: payload.description,
        product_keywords: payload.product_keywords,
        buyer_profiles: payload.buyer_profiles,
        target_regions: payload.target_regions,
        is_active: true,
        suppliers: [],
      }),
    });
  });

  await page.route(/\/discovery\/organizations\/org-1\/runs$/, async (route) => {
    const payload = route.request().postDataJSON();
    expect(payload).toMatchObject({
      product_line_id: "product-1",
      target_market: "Germany",
      buyer_profile: "Distributor",
      limit: 20,
    });
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

  let discoveryCompleted = false;
  let discoveredLead = {
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
  };
  await page.route(/\/discovery\/organizations\/org-1\/leads$/, async (route) => {
    if (!discoveryCompleted) {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([discoveredLead]),
    });
  });
  await page.route(/\/discovery\/organizations\/org-1\/leads\/lead-1$/, async (route) => {
    const payload = route.request().postDataJSON();
    expect(payload).toMatchObject({ status: "to_contact", notes: "" });
    discoveredLead = { ...discoveredLead, status: "to_contact", owner_user_id: payload.owner_user_id };
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(discoveredLead) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/email-drafts$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });

  await page.goto("/");
  const productForm = page.locator(".productForm");
  await productForm.getByLabel("产品线名称").fill("Industrial LED lighting");
  await productForm.getByLabel("产品关键词").fill("LED floodlight, warehouse lighting");
  await productForm.getByRole("textbox", { name: "客户类型" }).fill("Distributor, Project buyer");
  await productForm.getByLabel("目标区域").fill("Europe, North America");
  await page.getByRole("button", { name: "创建产品线" }).click();

  await expect(
    page.getByLabel("已配置产品线").getByText("Industrial LED lighting")
  ).toBeVisible();
  await page.getByLabel("搜索产品线").selectOption("product-1");
  await page.getByLabel("搜索目标市场").fill("Germany");
  await page.getByLabel("搜索客户类型").selectOption("Distributor");
  discoveryCompleted = true;
  await page.getByRole("button", { name: "开始搜索客户" }).click();

  await expect(page.getByText("搜索完成")).toBeVisible();
  await expect(page.locator("tbody").getByText("LumenHaus GmbH")).toBeVisible();
  await expect(page.getByText("Commercial lighting distributor")).toBeVisible();
  await expect(page.getByText("待补充信息")).toBeVisible();
  await page.getByLabel("选择 LumenHaus GmbH").check();
  await page.getByRole("button", { name: "保存 1 个到 CRM" }).click();
  await expect(page.getByLabel("CRM 客户列表").getByText("LumenHaus GmbH")).toBeVisible();
  await expect(page.getByText("已保存 1 个客户到 CRM")).toBeVisible();
});
