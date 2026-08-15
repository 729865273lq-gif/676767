import { expect, test } from "@playwright/test";

const productLine = {
  id: "product-1",
  name: "工业 LED 照明",
  description: "商业与工业改造照明方案",
  product_keywords: ["LED 投光灯", "仓库照明"],
  buyer_profiles: ["经销商", "工程采购商"],
  target_regions: ["欧洲", "北美"],
  is_active: true,
  suppliers: [],
  product_items: [],
};

const leads = [
  {
    id: "lead-1",
    workflow_run_id: "run-1",
    product_line_id: "product-1",
    company_name: "LumenHaus GmbH",
    website: "https://lumenhaus.example",
    target_market: "德国 柏林",
    buyer_profile: "经销商",
    score: 86,
    bucket: "priority_recommendation",
    status: "new",
    owner_user_id: null,
    notes: "",
    reasons: ["产品与市场匹配"],
    missing_signals: [],
    evidence: [{ source_url: "https://www.openstreetmap.org/node/1", source_excerpt: "Commercial lighting distributor with project services", signal_name: "map_place" }],
  },
  {
    id: "lead-2",
    workflow_run_id: "run-1",
    product_line_id: "product-1",
    company_name: "Nordlicht Technik AG",
    website: "https://nordlicht.example",
    target_market: "德国 汉堡",
    buyer_profile: "工程采购商",
    score: 71,
    bucket: "needs_enrichment",
    status: "new",
    owner_user_id: null,
    notes: "",
    reasons: ["工业照明关键词匹配"],
    missing_signals: ["联系人邮箱"],
    evidence: [{ source_url: "https://www.tomtom.com/maps", source_excerpt: "Industrial lighting supplier serving Northern Germany", signal_name: "map_place" }],
  },
];

test("renders the customer search workbench for visual review", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("trade-axis-session", JSON.stringify({
      access_token: "test-token",
      organization_id: "org-1",
      organization_role: "owner",
      user_id: "user-1",
      email: "mia@example.com",
    }));
  });
  await page.route("http://localhost:8000/**", async (route) => {
    const url = route.request().url();
    let body: unknown = [];
    if (url.includes("/locations/resolve")) body = {
      area: { scope_id: "beijing-place", name: "北京市", formatted: "北京市, 中国", search_label: "北京市, 中国", country_code: "CN", level: "city", search_count: 0, last_searched_at: null },
      subdivisions: [
        { scope_id: "chaoyang-place", name: "朝阳区", formatted: "朝阳区, 中国", search_label: "朝阳区, 北京市, 中国", country_code: "CN", level: "district", search_count: 1, last_searched_at: "2026-08-13T10:00:00Z" },
        { scope_id: "fengtai-place", name: "丰台区", formatted: "丰台区, 中国", search_label: "丰台区, 北京市, 中国", country_code: "CN", level: "district", search_count: 0, last_searched_at: null },
        { scope_id: "shijingshan-place", name: "石景山区", formatted: "石景山区, 中国", search_label: "石景山区, 北京市, 中国", country_code: "CN", level: "district", search_count: 0, last_searched_at: null },
        { scope_id: "haidian-place", name: "海淀区", formatted: "海淀区, 中国", search_label: "海淀区, 北京市, 中国", country_code: "CN", level: "district", search_count: 0, last_searched_at: null },
      ],
    };
    else if (url.includes("/contacts/discover-batch")) body = {
      items: [
        { lead_id: "lead-1", company_name: "LumenHaus GmbH", website: "https://lumenhaus.example", status: "has_email", contact_count: 2, email_count: 1, checked_email_count: 1, phone_count: 1, social_count: 0, message: "新增或更新 2 条公开联系方式" },
        { lead_id: "lead-2", company_name: "Nordlicht Technik AG", website: "https://nordlicht.example", status: "needs_review", contact_count: 0, email_count: 0, checked_email_count: 0, phone_count: 0, social_count: 0, message: "官网访问或联系方式提取失败，可稍后重试" },
      ],
    };
    else if (url.includes("/product-lines") && !url.includes("/items")) body = [productLine];
    else if (url.includes("/leads")) body = leads;
    else if (url.includes("/search-sources")) body = { sources: [
      { source_id: "tomtom", label: "TomTom 地图客户搜索", provider: "TomTom Search API", category: "map_search", purpose: "搜索海外企业", base_url: "https://developer.tomtom.com", enabled: true, configured: true, status: "ready", missing: [] },
      { source_id: "geoapify", label: "Geoapify 地图客户搜索", provider: "Geoapify Places API", category: "map_search", purpose: "搜索海外企业", base_url: "https://geoapify.com", enabled: true, configured: true, status: "ready", missing: [] },
      { source_id: "foursquare", label: "Foursquare 地图客户搜索", provider: "Foursquare Places API", category: "map_search", purpose: "搜索海外企业", base_url: "https://foursquare.com", enabled: true, configured: false, status: "needs_config", missing: ["FOURSQUARE_API_KEY"] },
      { source_id: "openstreetmap", label: "OpenStreetMap 企业搜索", provider: "OpenStreetMap Nominatim + Overpass", category: "map_search", purpose: "搜索海外企业", base_url: "https://openstreetmap.org", enabled: true, configured: true, status: "ready", missing: [] },
    ] };
    else if (url.includes("/customer-development-connectors")) body = { connectors: [] };
    else if (url.includes("/email-delivery")) body = { provider: "smtp", configured: false, from_email: null, from_name: "Trade Axis", missing: [] };
    else if (url.includes("/activity-feed")) body = { activities: [], total: 0 };
    else if (url.includes("/funnel")) body = { stages: [] };
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "地图客户搜索工作台" })).toBeVisible();
  await page.getByLabel("搜索目标市场").fill("北京");
  await page.getByRole("button", { name: "识别行政区" }).click();
  await expect(page.getByLabel("行政区选择").getByText("丰台区", { exact: true })).toBeVisible();
  await expect(page.getByLabel("行政区选择").getByText("已搜索 1 次", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "提取当前 2 家" }).click();
  await expect(page.locator(".dailyContactSummary").getByText("有邮箱 1 家", { exact: true })).toBeVisible();
  await page.getByText("查看逐家公司联系方式").click();
  await expect(page.getByText("邮箱 1（已基础检查 1）")).toBeVisible();
  await expect(page.getByText("新增或更新 2 条公开联系方式")).toBeVisible();
  await page.getByRole("heading", { name: "地图客户搜索工作台" }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: "test-results/customer-search-workbench-desktop.png", fullPage: false });

  await page.getByRole("button", { name: "API 接口状态" }).click();
  await expect(page.getByRole("heading", { name: "API 接口状态" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "网站 API 接口链接状态" })).toBeVisible();
  await expect(page.getByLabel("网站 API 接口列表").getByText("TomTom Search API")).toBeVisible();
  await expect(page.getByRole("heading", { name: "地图客户搜索工作台" })).toHaveCount(0);
  await page.screenshot({ path: "test-results/api-status-desktop.png", fullPage: false });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await page.getByRole("button", { name: "API 接口状态" }).click();
  await expect(page.getByRole("heading", { name: "API 接口状态" })).toBeVisible();
  await page.screenshot({ path: "test-results/api-status-mobile.png", fullPage: false });
});

test("shows a clear API connection error instead of an empty status table", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("trade-axis-session", JSON.stringify({
      access_token: "test-token",
      organization_id: "org-1",
      organization_role: "owner",
      user_id: "user-1",
      email: "mia@example.com",
    }));
  });
  await page.route("http://localhost:8000/**", async (route) => route.abort("connectionfailed"));

  await page.goto("/");
  await page.getByRole("button", { name: "API 接口状态" }).click();
  await expect(page.locator(".apiErrorBanner")).toContainText("后端 API 未连接");
  await expect(page.getByText("未获取到接口目录")).toBeVisible();
  await expect(page.getByRole("button", { name: "重新检查" })).toBeVisible();
});
