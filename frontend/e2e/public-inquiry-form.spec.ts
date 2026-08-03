import { expect, test } from "@playwright/test";

test("submits the public inquiry form without an authenticated session", async ({ page }) => {
  await page.route(/\/discovery\/public\/organizations\/org-1\/website-inquiries$/, async (route) => {
    const payload = route.request().postDataJSON();
    expect(route.request().method()).toBe("POST");
    expect(payload).toMatchObject({
      product_line_id: "product-1",
      company_name: "Website Buyer Ltd",
      contact_name: "Mina Lee",
      email: "mina@buyer.example",
      phone: "+82 10 5555 1234",
      website: "https://buyer.example",
      target_market: "Korea",
      message: "Need quotation for 300 sample units and lead time.",
    });
    expect(payload.source_url).toContain("/inquiry?");
    await route.fulfill({
      contentType: "application/json",
      status: 201,
      body: JSON.stringify({
        id: "inquiry-1",
        organization_id: "org-1",
        product_line_id: "product-1",
        lead_id: null,
        status: "new",
        company_name: payload.company_name,
        contact_name: payload.contact_name,
        email: payload.email,
        phone: payload.phone,
        website: payload.website,
        target_market: payload.target_market,
        message: payload.message,
        source_url: payload.source_url,
        created_at: "2026-08-03T08:00:00Z",
        converted_at: null,
      }),
    });
  });

  await page.goto("/inquiry?organization_id=org-1&product_line_id=product-1&product=Industrial%20LED%20Lighting");
  await expect(page.getByRole("heading", { name: "Industrial LED Lighting" })).toBeVisible();

  await page.getByLabel("Company name").fill("Website Buyer Ltd");
  await page.getByLabel("Contact name").fill("Mina Lee");
  await page.getByLabel("Email").fill("mina@buyer.example");
  await page.getByLabel("Phone / WhatsApp").fill("+82 10 5555 1234");
  await page.getByLabel("Company website").fill("https://buyer.example");
  await page.getByLabel("Target market").fill("Korea");
  await page.getByLabel("Sourcing request").fill("Need quotation for 300 sample units and lead time.");
  await page.getByRole("button", { name: "Submit inquiry" }).click();

  await expect(page.getByText("Inquiry received.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Submit another inquiry" })).toBeVisible();
});

test("shows configuration guidance for an incomplete inquiry link", async ({ page }) => {
  await page.goto("/inquiry");

  await expect(page.getByText("missing organization or product configuration")).toBeVisible();
});
