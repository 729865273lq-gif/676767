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
    const isTemporaryLine = payload.name === "Temporary Product Line";
    if (isTemporaryLine) {
      expect(payload).toMatchObject({ name: "Temporary Product Line" });
    } else {
      expect(payload).toMatchObject({
        name: "Industrial LED lighting",
        product_keywords: ["LED floodlight", "warehouse lighting"],
        buyer_profiles: ["Distributor", "Project buyer"],
        target_regions: ["Europe", "North America"],
        excluded_keywords: ["manufacturer", "factory"],
      });
    }
    await route.fulfill({
      contentType: "application/json",
      status: 201,
      body: JSON.stringify({
        id: isTemporaryLine ? "product-2" : "product-1",
        name: payload.name,
        description: payload.description,
        product_keywords: payload.product_keywords,
        buyer_profiles: payload.buyer_profiles,
        target_regions: payload.target_regions,
        excluded_keywords: payload.excluded_keywords,
        is_active: true,
        suppliers: [],
        product_items: [],
      }),
    });
  });

  await page.route(/\/platform\/organizations\/org-1\/product-lines\/product-2$/, async (route) => {
    expect(route.request().method()).toBe("DELETE");
    await route.fulfill({ status: 204 });
  });

  await page.route(/\/platform\/organizations\/org-1\/product-lines\/product-1\/items$/, async (route) => {
    const payload = route.request().postDataJSON();
    expect(route.request().method()).toBe("POST");
    expect(payload).toMatchObject({
      name: "LED Floodlight 200W",
      sku: "FL-200W",
      summary: "High-output model for warehouse projects.",
      specs: ["200W", "IP66", "CE"],
      image_url: "https://brand.example/floodlight.jpg",
      is_published: true,
    });
    await route.fulfill({
      contentType: "application/json",
      status: 201,
      body: JSON.stringify({
        id: "item-1",
        product_line_id: "product-1",
        name: payload.name,
        sku: payload.sku,
        summary: payload.summary,
        specs: payload.specs,
        image_url: payload.image_url,
        is_published: payload.is_published,
      }),
    });
  });

  await page.route(/\/discovery\/organizations\/org-1\/runs$/, async (route) => {
    const payload = route.request().postDataJSON();
    expect(payload).toMatchObject({
      product_line_id: "product-1",
      target_market: "Germany",
      location_scope_id: "germany-place",
      location_country_code: "DE",
      buyer_profile: "Distributor",
      excluded_keywords: ["manufacturer", "factory"],
      limit: 50,
    });
    await route.fulfill({
      contentType: "application/json",
      status: 201,
      body: JSON.stringify({
        workflow_run_id: "run-1",
        query: "Industrial LED lighting Distributor Germany",
        lead_count: 2,
        lead_ids: ["lead-1"],
        filtered_count: 3,
        query_count: 6,
        queries: [
          "industrial LED lighting distributor Germany",
          "industrial lighting wholesaler Germany",
          "LED lighting importer Germany",
          "industrial lighting wholesaler Berlin Germany",
          "LED lighting importer Hamburg Germany",
          "commercial lighting industrial supplier Munich Germany",
        ],
        candidate_count: 9,
        duplicate_count: 5,
        overflow_count: 0,
        failed_query_count: 0,
        state: "completed",
      }),
    });
  });
  await page.route(/\/discovery\/organizations\/org-1\/locations\/resolve$/, async (route) => {
    expect(route.request().postDataJSON()).toMatchObject({ query: "Germany", product_line_id: "product-1" });
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        area: { scope_id: "germany-place", name: "Germany", formatted: "Germany", search_label: "Germany", country_code: "DE", level: "country", search_count: 0, last_searched_at: null },
        subdivisions: [],
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
    last_discovered_at: "2026-08-13T09:00:00Z",
    created_at: "2026-08-13T09:00:00Z",
    evidence: [
      {
        source_url: "https://lumenhaus.example",
        source_excerpt: "Commercial lighting distributor",
        signal_name: "search_result",
      },
    ],
  };
  const olderCrmLead = {
    ...discoveredLead,
    id: "lead-older",
    company_name: "Older Customer GmbH",
    website: "https://older-customer.example",
    status: "to_contact",
    last_discovered_at: "2026-08-12T09:00:00Z",
    created_at: "2026-08-12T09:00:00Z",
  };
  await page.route(/\/discovery\/organizations\/org-1\/leads$/, async (route) => {
    if (!discoveryCompleted) {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([olderCrmLead, discoveredLead]),
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
  await page.route(/\/platform\/organizations\/org-1\/email-delivery$/, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        provider: "smtp",
        configured: false,
        from_email: null,
        from_name: "Trade Axis",
        missing: ["SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_EMAIL"],
      }),
    });
  });
  await page.route(/\/platform\/organizations\/org-1\/customer-development-connectors$/, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        connectors: [
          {
            connector_id: "public_search",
            label: "公开客户搜索",
            provider: "Bocha",
            purpose: "按产品和市场搜索潜在客户官网",
            configured: true,
            missing: [],
          },
        ],
      }),
    });
  });
  await page.route(/\/platform\/organizations\/org-1\/search-sources$/, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        sources: [
          {
            source_id: "bocha",
            label: "公开网页搜索",
            provider: "Bocha",
            category: "web_search",
            purpose: "按产品和市场搜索潜在客户官网",
            base_url: "https://bochaai.com",
            enabled: true,
            configured: true,
            status: "ready",
            missing: [],
          },
        ],
      }),
    });
  });
  await page.route(/\/discovery\/organizations\/org-1\/follow-ups/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/follow-up-tasks(?:\?.*)?$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/website-inquiries(?:\?.*)?$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });

  await page.goto("/");
  const productForm = page.locator(".productForm");
  await productForm.getByLabel("产品线名称").fill("Industrial LED lighting");
  await productForm.getByLabel("产品关键词").fill("LED floodlight, warehouse lighting");
  await productForm.getByRole("textbox", { name: "客户类型" }).fill("Distributor, Project buyer");
  await productForm.getByLabel("目标区域").fill("Europe, North America");
  await productForm.getByLabel("排除关键词").fill("manufacturer, factory");
  await page.getByRole("button", { name: "创建产品线" }).click();

  await expect(
    page.getByLabel("已配置产品线").getByText("Industrial LED lighting")
  ).toBeVisible();

  const catalogForm = page.locator(".catalogForm");
  await catalogForm.getByLabel("所属产品线").selectOption("product-1");
  await catalogForm.getByLabel("产品名称").fill("LED Floodlight 200W");
  await catalogForm.getByLabel("SKU / 型号").fill("FL-200W");
  await catalogForm.getByLabel("图片 URL").fill("https://brand.example/floodlight.jpg");
  await catalogForm.getByLabel("简短卖点").fill("High-output model for warehouse projects.");
  await catalogForm.getByLabel("规格参数").fill("200W, IP66, CE");
  await page.getByRole("button", { name: "保存产品" }).click();
  await expect(page.getByText("公开产品 API")).toBeVisible();
  await expect(page.getByText("1 个已发布产品会进入独立站数据出口")).toBeVisible();
  await expect(page.getByText("/platform/public/organizations/org-1/product-catalog")).toBeVisible();
  await expect(page.getByLabel("产品目录列表").getByText("LED Floodlight 200W")).toBeVisible();
  await expect(page.getByLabel("产品目录列表").getByText("product_item_id=item-1")).toBeVisible();

  await page.getByLabel("搜索产品线").selectOption("product-1");
  await page.getByLabel("搜索目标市场").fill("Germany");
  await page.getByRole("button", { name: "识别行政区" }).click();
  await expect(page.getByLabel("行政区选择").locator("strong").getByText("Germany", { exact: true })).toBeVisible();
  await page.getByLabel("搜索客户类型").selectOption("Distributor");
  await expect(page.getByLabel("搜索排除关键词")).toHaveValue("manufacturer, factory");
  discoveryCompleted = true;
  await page.getByRole("button", { name: "开始搜索客户" }).click();

  await expect(page.getByText("搜索完成")).toBeVisible();
  await expect(page.getByText("6 组查询获得 9 条候选")).toBeVisible();
  await expect(page.getByText("去重 5 条")).toBeVisible();
  await expect(page.getByText("过滤 3 条")).toBeVisible();
  await page.getByText("查看本次 6 组搜索词").click();
  await expect(page.getByText("industrial lighting wholesaler Berlin Germany")).toBeVisible();
  await expect(page.getByRole("region", { name: "地图客户搜索工作台" })).toBeVisible();
  await expect(page.getByText("本次搜索结果")).toBeVisible();
  await expect(page.getByLabel("客户搜索结果列表").getByText("LumenHaus GmbH")).toBeVisible();
  await expect(
    page.getByLabel("客户搜索结果列表").getByRole("button", { name: "删除", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Commercial lighting distributor")).toBeVisible();
  await expect(page.getByText("待补充信息")).toBeVisible();
  await page.getByRole("button", { name: "查看历史线索" }).click();
  await expect(page.locator(".leadResultRow").first()).toContainText("LumenHaus GmbH");
  await page.getByLabel("选择 LumenHaus GmbH").check();
  await page.getByRole("button", { name: "保存 1 个到 CRM" }).click();
  await expect(page.getByLabel("CRM 客户列表").getByText("LumenHaus GmbH")).toBeVisible();
  await expect(page.locator(".crmItem").first()).toContainText("LumenHaus GmbH");
  await expect(page.getByText("已保存 1 个客户到 CRM")).toBeVisible();

  await productForm.getByLabel("产品线名称").fill("Temporary Product Line");
  await productForm.getByLabel("产品关键词").fill("temporary product");
  await productForm.getByRole("textbox", { name: "客户类型" }).fill("Distributor");
  await productForm.getByLabel("目标区域").fill("Malaysia");
  await productForm.getByLabel("排除关键词").fill("");
  await page.getByRole("button", { name: "创建产品线" }).click();
  const temporaryLine = page.locator(".productItem").filter({ hasText: "Temporary Product Line" });
  await expect(temporaryLine).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await temporaryLine.getByRole("button", { name: "删除产品线 Temporary Product Line" }).click();
  await expect(temporaryLine).toBeHidden();
});
