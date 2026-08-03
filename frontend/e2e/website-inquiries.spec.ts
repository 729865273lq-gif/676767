import { expect, test } from "@playwright/test";

const productLine = {
  id: "product-1",
  name: "Industrial LED Lighting",
  description: "Commercial and industrial lighting.",
  product_keywords: ["LED floodlight"],
  buyer_profiles: ["Distributor"],
  target_regions: ["Europe"],
  is_active: true,
  suppliers: [],
  product_items: [
    {
      id: "item-1",
      product_line_id: "product-1",
      name: "LED Floodlight 200W",
      sku: "FL-200W",
      summary: "High-output LED floodlight for industrial projects.",
      specs: ["200W", "IP66"],
      image_url: "",
      is_published: true,
    },
  ],
};

const convertedLead = {
  id: "lead-inquiry-1",
  workflow_run_id: "manual-run-1",
  product_line_id: "product-1",
  company_name: "Website Buyer Ltd",
  website: "https://buyer.example",
  target_market: "Korea",
  buyer_profile: "Website inquiry",
  score: 70,
  bucket: "needs_enrichment",
  status: "interested",
  owner_user_id: null,
  notes: "Product inquiry: LED Floodlight 200W\n\nNeed quotation for 300 sample units and lead time.",
  reasons: ["manual customer"],
  missing_signals: ["public evidence pending"],
  evidence: [
    {
      source_url: "https://buyer.example",
      source_excerpt: "Need quotation for 300 sample units and lead time.",
      signal_name: "manual_entry",
    },
  ],
  contacts: [
    {
      id: "contact-1",
      lead_id: "lead-inquiry-1",
      name: "Mina Lee",
      title: "",
      email: "mina@buyer.example",
      phone: "+82 10 5555 1234",
      linkedin_url: "",
      whatsapp: "",
      is_primary: true,
      created_at: "2026-08-03T08:00:00Z",
    },
  ],
  follow_ups: [
    {
      id: "follow-up-inquiry-1",
      lead_id: "lead-inquiry-1",
      actor_user_id: "user-1",
      activity_type: "inquiry",
      content: "Website inquiry for LED Floodlight 200W: Need quotation for 300 sample units and lead time.",
      next_follow_up_at: null,
      created_at: "2026-08-03T08:00:00Z",
    },
  ],
  follow_up_tasks: [],
};

test("converts a website inquiry into a CRM customer", async ({ page }) => {
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

  let converted = false;
  const inquiry = {
    id: "inquiry-1",
    organization_id: "org-1",
    product_line_id: "product-1",
    product_item_id: "item-1",
    lead_id: converted ? "lead-inquiry-1" : null,
    status: converted ? "converted" : "new",
    product_item_name: "LED Floodlight 200W",
    company_name: "Website Buyer Ltd",
    contact_name: "Mina Lee",
    email: "mina@buyer.example",
    phone: "+82 10 5555 1234",
    website: "",
    target_market: "Korea",
    message: "Need quotation for 300 sample units and lead time.",
    source_url: "https://brand.example/products/lighting",
    created_at: "2026-08-03T08:00:00Z",
    converted_at: converted ? "2026-08-03T08:10:00Z" : null,
  };

  await page.route(/\/platform\/organizations\/org-1\/product-lines$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([productLine]) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/leads$/, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(converted ? [convertedLead] : []),
    });
  });
  await page.route(/\/discovery\/organizations\/org-1\/email-drafts$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/follow-ups/, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(
        converted
          ? convertedLead.follow_ups.map((record) => ({
              ...record,
              lead_company_name: convertedLead.company_name,
              lead_status: convertedLead.status,
            }))
          : []
      ),
    });
  });
  await page.route(/\/discovery\/organizations\/org-1\/follow-up-tasks(?:\?.*)?$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/website-inquiries(?:\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    const statusFilter = url.searchParams.get("status_filter");
    const currentInquiry = {
      ...inquiry,
      lead_id: converted ? "lead-inquiry-1" : null,
      status: converted ? "converted" : "new",
      converted_at: converted ? "2026-08-03T08:10:00Z" : null,
    };
    const items = !statusFilter || statusFilter === currentInquiry.status ? [currentInquiry] : [];
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(items) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/website-inquiries\/inquiry-1\/convert$/, async (route) => {
    expect(route.request().method()).toBe("POST");
    converted = true;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        inquiry: {
          ...inquiry,
          lead_id: "lead-inquiry-1",
          status: "converted",
          converted_at: "2026-08-03T08:10:00Z",
        },
        lead: convertedLead,
      }),
    });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "独立站询盘" })).toBeVisible();
  await expect(page.getByLabel("独立站表单链接").getByText("LED Floodlight 200W")).toBeVisible();
  await expect(page.getByLabel("独立站表单链接").getByText("product_item_id=item-1")).toBeVisible();
  await expect(page.getByLabel("独立站询盘列表").getByText("Website Buyer Ltd")).toBeVisible();
  await expect(page.getByLabel("独立站询盘列表").getByText("LED Floodlight 200W")).toBeVisible();
  await expect(page.getByLabel("独立站询盘列表").getByText("Need quotation for 300 sample units")).toBeVisible();

  await page.getByRole("button", { name: "转为 CRM 客户" }).click();

  await expect(page.getByLabel("客户详情").getByText("Website Buyer Ltd")).toBeVisible();
  await expect(page.locator(".contactList").getByText("Mina Lee")).toBeVisible();
  await expect(page.locator(".followUpList").getByText("Website inquiry for LED Floodlight 200W")).toBeVisible();
  await expect(page.getByLabel("CRM 客户列表").getByText("Website Buyer Ltd")).toBeVisible();

  await page.locator(".customerDrawer .closeButton").click();
  await page.locator(".inquiryPanel").getByLabel("状态").selectOption("converted");
  await expect(page.getByLabel("独立站询盘列表").getByText("已转客户")).toBeVisible();
});
