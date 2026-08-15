import { expect, test } from "@playwright/test";

test("inbox list, filter, manual sync, and mark-done flow", async ({ page }) => {
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

  let done = false;
  const dueAt = new Date(Date.now() + 3 * 86400000).toISOString();

  const interested = {
    id: "msg-1",
    provider_message_id: "pm-1",
    sender_email: "anna@buyer.example",
    sender_name: "Anna Buyer",
    subject: "Re: LED Floodlight quotation",
    received_at: "2026-08-03T08:00:00Z",
    intent: "interested",
    intent_confidence: 0.8,
    suggested_reply: "Thank you for your interest in our products. Could you let me know your target quantity?",
    follow_up_task_id: "task-1",
    due_at: dueAt,
    created_at: "2026-08-03T08:00:00Z",
  };
  const outOfOffice = {
    id: "msg-2",
    provider_message_id: "pm-2",
    sender_email: "ben@buyer.example",
    sender_name: "Ben Lee",
    subject: "Automatic reply: Out of office",
    received_at: "2026-08-03T09:00:00Z",
    intent: "out_of_office",
    intent_confidence: 0.95,
    suggested_reply: "",
    follow_up_task_id: null,
    due_at: null,
    created_at: "2026-08-03T09:00:00Z",
  };
  const messages = [interested, outOfOffice];
  const detail = {
    ...interested,
    thread_id: "thread-1",
    body_text: "Hello, we are interested in your LED Floodlight 200W.\n\nPlease send a quotation for 300 units to Hamburg.",
    analysis_rationale: "Body expresses buying interest and requests a quote.",
    linked_company_name: "Website Buyer Ltd",
  };

  // Workbench startup endpoints (mirror the existing e2e mocks so the page loads cleanly).
  await page.route(/\/platform\/organizations\/org-1\/product-lines$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/leads$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/follow-ups/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/follow-up-tasks(?:\?.*)?$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
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
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ connectors: [] }) });
  });
  await page.route(/\/platform\/organizations\/org-1\/search-sources$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ sources: [] }) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/website-inquiries(?:\?.*)?$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route(/\/knowledge\/organizations\/org-1\/documents$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });

  // Inbox endpoints.
  await page.route(/\/organizations\/org-1\/inbox(?:\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    const intent = url.searchParams.get("intent");
    const hasFollowUp = url.searchParams.get("has_follow_up");
    const items = messages.filter((message) => {
      if (intent && message.intent !== intent) return false;
      if (hasFollowUp === "true" && !message.follow_up_task_id) return false;
      return true;
    });
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(items) });
  });
  await page.route(/\/organizations\/org-1\/inbox\/msg-1$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(detail) });
  });
  await page.route(/\/organizations\/org-1\/inbox\/sync$/, async (route) => {
    expect(route.request().method()).toBe("POST");
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ organization_id: "org-1", synced: 0 }),
    });
  });
  await page.route(/\/organizations\/org-1\/inbox\/msg-1\/follow-up\/done$/, async (route) => {
    expect(route.request().method()).toBe("POST");
    done = true;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ message_id: "msg-1", follow_up_status: "done" }),
    });
  });

  await page.goto("/");

  // List render: sender, subject, intent badge, follow-up state.
  const list = page.getByLabel("收件箱列表");
  await expect(page.getByRole("heading", { name: "收件箱" })).toBeVisible();
  await expect(list.getByText("Anna Buyer")).toBeVisible();
  await expect(list.getByText("Re: LED Floodlight quotation")).toBeVisible();
  await expect(list.getByText("有兴趣 80%")).toBeVisible();
  await expect(list.getByText("待跟进")).toBeVisible();
  await expect(list.getByText("自动回复 95%")).toBeVisible();
  await expect(list.getByText("无需跟进")).toBeVisible();

  // Filter by intent: only the out-of-office message remains.
  await page.locator(".inquiryPanel").getByLabel("意向").selectOption("out_of_office");
  await expect(list.getByText("Automatic reply: Out of office")).toBeVisible();
  await expect(list.getByText("Re: LED Floodlight quotation")).toHaveCount(0);

  // Reset filter and open the interested message detail.
  await page.locator(".inquiryPanel").getByLabel("意向").selectOption("all");
  await expect(list.getByText("Re: LED Floodlight quotation")).toBeVisible();
  await list.getByRole("button", { name: "查看详情" }).first().click();

  const drawer = page.getByLabel("收件箱详情");
  await expect(drawer.getByText("300 units to Hamburg")).toBeVisible();
  await expect(drawer.getByText("Website Buyer Ltd")).toBeVisible();

  // Mark the follow-up as done.
  await drawer.getByRole("button", { name: "标记完成" }).click();
  await expect(drawer.getByText("已完成")).toBeVisible();
  expect(done).toBe(true);

  // Close the drawer: the list now reflects the done state (client-side tracking).
  await drawer.getByRole("button", { name: "关闭邮件详情" }).click();
  await expect(list.getByText("已完成")).toBeVisible();

  // Admin-only manual sync.
  await page.getByRole("button", { name: "立即同步" }).click();
  await expect(page.getByText("同步完成，新增 0 封邮件")).toBeVisible();
});
