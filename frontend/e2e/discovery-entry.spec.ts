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

  await page.route(/\/discovery\/organizations\/org-1\/leads\?workflow_run_id=run-1$/, async (route) => {
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
      ]),
    });
  });

  await page.goto("/");
  await page.getByLabel("Product line name").fill("Industrial LED lighting");
  await page.getByLabel("Product keywords").fill("LED floodlight, warehouse lighting");
  await page.getByLabel("Buyer profiles").fill("Distributor, Project buyer");
  await page.getByLabel("Target regions").fill("Europe, North America");
  await page.getByRole("button", { name: "Create product line" }).click();

  await expect(
    page.getByLabel("Configured product lines").getByText("Industrial LED lighting")
  ).toBeVisible();
  await page.getByLabel("Discovery product line").selectOption("product-1");
  await page.getByLabel("Discovery target market").fill("Germany");
  await page.getByLabel("Discovery buyer profile").selectOption("Distributor");
  await page.getByRole("button", { name: "Start discovery" }).click();

  await expect(page.getByText("Discovery complete")).toBeVisible();
  await expect(page.getByRole("cell", { name: "LumenHaus GmbH" })).toBeVisible();
  await expect(page.getByText("Commercial lighting distributor")).toBeVisible();
  await expect(page.getByText("Needs enrichment")).toBeVisible();
});
