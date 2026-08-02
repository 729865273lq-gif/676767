import { expect, test } from "@playwright/test";

test("manually adds and deletes a CRM customer", async ({ page }) => {
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
          name: "工业 LED 照明",
          description: "商业与工业改造照明方案",
          product_keywords: ["LED 投光灯", "仓库照明"],
          buyer_profiles: ["经销商", "工程采购商"],
          target_regions: ["欧洲", "北美"],
          is_active: true,
          suppliers: [],
        },
      ]),
    });
  });

  let leads: Array<Record<string, unknown>> = [];
  await page.route(/\/discovery\/organizations\/org-1\/leads$/, async (route) => {
    if (route.request().method() === "POST") {
      const payload = route.request().postDataJSON();
      expect(payload).toMatchObject({
        product_line_id: "product-1",
        company_name: "Berlin Lighting GmbH",
        website: "berlin-lighting.example",
        target_market: "德国",
        buyer_profile: "经销商",
      });
      leads = [
        {
          id: "lead-manual-1",
          workflow_run_id: "manual-run-1",
          product_line_id: "product-1",
          company_name: payload.company_name,
          website: "https://berlin-lighting.example",
          target_market: payload.target_market,
          buyer_profile: payload.buyer_profile,
          score: 70,
          bucket: "needs_enrichment",
          status: "to_contact",
          owner_user_id: null,
          notes: "",
          reasons: ["人工添加客户"],
          missing_signals: ["公开证据待补充"],
          evidence: [
            {
              source_url: "https://berlin-lighting.example",
              source_excerpt: payload.notes,
              signal_name: "manual_entry",
            },
          ],
        },
      ];
      await route.fulfill({ contentType: "application/json", status: 201, body: JSON.stringify(leads[0]) });
      return;
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(leads) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/leads\/lead-manual-1$/, async (route) => {
    if (route.request().method() === "PATCH") {
      const payload = route.request().postDataJSON();
      expect(payload).toMatchObject({ status: "interested", notes: "客户要求下周提供 FOB 报价。" });
      leads = leads.map((lead) => ({ ...lead, status: payload.status, notes: payload.notes }));
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(leads[0]) });
      return;
    }
    expect(route.request().method()).toBe("DELETE");
    leads = [];
    await route.fulfill({ status: 204 });
  });
  let contacts: Array<Record<string, unknown>> = [];
  let followUps: Array<Record<string, unknown>> = [];
  let emailDrafts: Array<Record<string, unknown>> = [];
  await page.route(/\/discovery\/organizations\/org-1\/follow-ups/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(followUps) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/leads\/lead-manual-1\/detail$/, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ...leads[0], contacts, follow_ups: followUps }),
    });
  });
  await page.route(/\/discovery\/organizations\/org-1\/leads\/lead-manual-1\/contacts$/, async (route) => {
    const payload = route.request().postDataJSON();
    expect(payload).toMatchObject({
      name: "Anna Weber",
      title: "Purchasing Manager",
      email: "anna@berlin-lighting.example",
      phone: "+49 30 123456",
      linkedin_url: "https://linkedin.com/in/anna-weber",
      whatsapp: "+49 171 123456",
      is_primary: true,
    });
    contacts = [
      {
        id: "contact-1",
        lead_id: "lead-manual-1",
        name: payload.name,
        title: payload.title,
        email: payload.email,
        phone: payload.phone,
        linkedin_url: payload.linkedin_url,
        whatsapp: payload.whatsapp,
        is_primary: payload.is_primary,
        created_at: "2026-08-01T08:00:00Z",
      },
    ];
    await route.fulfill({ contentType: "application/json", status: 201, body: JSON.stringify(contacts[0]) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/leads\/lead-manual-1\/contacts\/contact-1$/, async (route) => {
    expect(route.request().method()).toBe("DELETE");
    contacts = [];
    await route.fulfill({ status: 204 });
  });
  await page.route(/\/discovery\/organizations\/org-1\/leads\/lead-manual-1\/email-drafts$/, async (route) => {
    const payload = route.request().postDataJSON();
    expect(payload).toMatchObject({ contact_id: "contact-1" });
    emailDrafts = [
      {
        id: "draft-1",
        organization_id: "org-1",
        lead_id: "lead-manual-1",
        contact_id: "contact-1",
        product_line_id: "product-1",
        created_by_user_id: "user-1",
        reviewed_by_user_id: null,
        sent_by_user_id: null,
        status: "pending_approval",
        subject: "Industrial LED supply discussion for Berlin Lighting GmbH",
        body: "Dear Anna Weber,\\n\\nWe reviewed your public website and can share LED lighting details.",
        evidence_snapshot: [
          {
            signal_name: "manual_entry",
            source_excerpt: "展会名片来源",
            source_url: "https://berlin-lighting.example",
          },
        ],
        rejection_reason: "",
        created_at: "2026-08-01T08:00:00Z",
        updated_at: "2026-08-01T08:00:00Z",
        reviewed_at: null,
        sent_at: null,
        lead_company_name: "Berlin Lighting GmbH",
        contact_name: "Anna Weber",
        contact_email: "anna@berlin-lighting.example",
      },
    ];
    await route.fulfill({ contentType: "application/json", status: 201, body: JSON.stringify(emailDrafts[0]) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/email-drafts$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(emailDrafts) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/email-drafts\/draft-1$/, async (route) => {
    const payload = route.request().postDataJSON();
    expect(payload).toMatchObject({
      subject: "Updated LED introduction",
      body: "Updated approved body.",
    });
    emailDrafts = emailDrafts.map((draft) => ({ ...draft, subject: payload.subject, body: payload.body }));
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(emailDrafts[0]) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/email-drafts\/draft-1\/review$/, async (route) => {
    const payload = route.request().postDataJSON();
    expect(payload).toMatchObject({ action: "approve" });
    emailDrafts = emailDrafts.map((draft) => ({
      ...draft,
      status: "ready_to_send",
      reviewed_by_user_id: "user-1",
      reviewed_at: "2026-08-01T08:10:00Z",
    }));
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(emailDrafts[0]) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/email-drafts\/draft-1\/send$/, async (route) => {
    expect(route.request().method()).toBe("POST");
    emailDrafts = emailDrafts.map((draft) => ({
      ...draft,
      status: "sent",
      sent_by_user_id: "user-1",
      sent_at: "2026-08-01T08:15:00Z",
    }));
    leads = leads.map((lead) => ({ ...lead, status: "contacted" }));
    followUps = [
      {
        id: "follow-up-sent-1",
        lead_id: "lead-manual-1",
        actor_user_id: "user-1",
        activity_type: "email_sent",
        content: "已人工发送开发信给 Anna Weber <anna@berlin-lighting.example>：Updated LED introduction",
        next_follow_up_at: "2026-08-04T08:15:00Z",
        created_at: "2026-08-01T08:15:00Z",
        lead_company_name: "Berlin Lighting GmbH",
        lead_status: "contacted",
      },
      ...followUps,
    ];
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(emailDrafts[0]) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/leads\/lead-manual-1\/follow-ups$/, async (route) => {
    const payload = route.request().postDataJSON();
    if (payload.activity_type === "reply") {
      expect(payload).toMatchObject({ content: "客户回复：请提供 500 套样品报价。" });
      leads = leads.map((lead) => ({ ...lead, status: "interested" }));
      followUps = [
        {
          id: "follow-up-reply-1",
          lead_id: "lead-manual-1",
          actor_user_id: "user-1",
          activity_type: payload.activity_type,
          content: payload.content,
          next_follow_up_at: payload.next_follow_up_at,
          created_at: "2026-08-01T09:00:00Z",
          lead_company_name: "Berlin Lighting GmbH",
          lead_status: "interested",
        },
        ...followUps,
      ];
      await route.fulfill({ contentType: "application/json", status: 201, body: JSON.stringify(followUps[0]) });
      return;
    }
    expect(payload).toMatchObject({ activity_type: "email", content: "已发送目录，等待客户确认采购数量。" });
    followUps = [
      {
        id: "follow-up-1",
        lead_id: "lead-manual-1",
        actor_user_id: "user-1",
        activity_type: payload.activity_type,
        content: payload.content,
        next_follow_up_at: payload.next_follow_up_at,
        created_at: "2026-08-01T08:00:00Z",
        lead_company_name: "Berlin Lighting GmbH",
        lead_status: "interested",
      },
      ...followUps,
    ];
    await route.fulfill({ contentType: "application/json", status: 201, body: JSON.stringify(followUps[0]) });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "CRM 客户" })).toBeVisible();

  const crmForm = page.locator(".crmForm");
  await crmForm.getByLabel("所属产品线").selectOption("product-1");
  await crmForm.getByLabel("公司名称").fill("Berlin Lighting GmbH");
  await crmForm.getByLabel("官网").fill("berlin-lighting.example");
  await crmForm.getByLabel("目标市场").fill("德国");
  await crmForm.getByRole("textbox", { name: "客户类型" }).fill("经销商");
  await crmForm.getByLabel("备注 / 来源").fill("展会名片来源");
  await page.getByRole("button", { name: "添加客户" }).click();

  await expect(page.getByLabel("CRM 客户列表").getByText("Berlin Lighting GmbH")).toBeVisible();
  await page.getByLabel("CRM 客户列表").getByRole("button", { name: "详情", exact: true }).click();
  await expect(page.getByLabel("客户详情").getByText("Berlin Lighting GmbH")).toBeVisible();

  await page.locator(".contactForm input[name='name']").fill("Anna Weber");
  await page.locator(".contactForm input[name='title']").fill("Purchasing Manager");
  await page.locator(".contactForm input[name='email']").fill("anna@berlin-lighting.example");
  await page.locator(".contactForm input[name='phone']").fill("+49 30 123456");
  await page.locator(".contactForm input[name='linkedin_url']").fill("https://linkedin.com/in/anna-weber");
  await page.locator(".contactForm input[name='whatsapp']").fill("+49 171 123456");
  await page.locator(".contactForm input[name='is_primary']").check();
  await page.locator(".contactForm button[type='submit']").click();
  await expect(page.locator(".contactList").getByText("Anna Weber")).toBeVisible();
  await expect(page.locator(".contactList").getByText("主要联系人")).toBeVisible();
  await page.locator(".contactList").getByRole("button", { name: "生成开发信草稿" }).click();
  await expect(page.getByLabel("邮件审核队列").getByText("Berlin Lighting GmbH")).toBeVisible();
  await page.getByLabel("邮件主题").fill("Updated LED introduction");
  await page.getByLabel("邮件正文").fill("Updated approved body.");
  await page.getByRole("button", { name: "保存修改" }).click();
  await expect(page.getByLabel("邮件主题")).toHaveValue("Updated LED introduction");
  await page.getByRole("button", { name: "批准为待发送" }).click();
  await expect(page.locator(".draftCard .status", { hasText: "待发送" })).toBeVisible();
  await page.getByRole("button", { name: "标记已发送" }).click();
  await expect(page.locator(".draftCard .status", { hasText: "已发送" })).toBeVisible();
  await page.getByLabel("关闭审核队列").click();
  await expect(page.locator(".detailSummary strong").filter({ hasText: "已联系" })).toBeVisible();
  await expect(page.locator(".followUpList").getByText("已人工发送开发信给 Anna Weber")).toBeVisible();
  await expect(page.getByRole("heading", { name: "跟进控制" })).toBeVisible();
  await expect(page.locator(".timeline").getByText("Berlin Lighting GmbH / 已人工发送开发信给 Anna Weber")).toBeVisible();

  await page.getByLabel("客户状态").selectOption("interested");
  await page.getByLabel("客户备注").fill("客户要求下周提供 FOB 报价。");
  await page.getByRole("button", { name: "保存客户详情" }).click();
  await expect(page.locator(".detailSummary strong").filter({ hasText: "有意向" })).toBeVisible();

  await page.getByLabel("跟进类型").selectOption("email");
  await page.getByLabel("跟进内容").fill("已发送目录，等待客户确认采购数量。");
  await page.getByRole("button", { name: "添加跟进记录" }).click();
  await expect(page.locator(".followUpList").getByText("已发送目录，等待客户确认采购数量。")).toBeVisible();

  await page.getByLabel("跟进类型").selectOption("reply");
  await page.getByLabel("跟进内容").fill("客户回复：请提供 500 套样品报价。");
  await page.getByRole("button", { name: "添加跟进记录" }).click();
  await expect(page.getByLabel("客户回复列表").getByText("Berlin Lighting GmbH")).toBeVisible();
  await expect(page.getByLabel("客户回复列表").getByText("客户回复：请提供 500 套样品报价。")).toBeVisible();
  await expect(page.getByLabel("销售指标").locator(".metricTile").filter({ hasText: "客户回复" }).getByText("1")).toBeVisible();
  await page.getByLabel("关闭客户详情").click();

  await page.getByRole("button", { name: "删除" }).click();
  await expect(page.getByLabel("CRM 客户列表").getByText("Berlin Lighting GmbH")).toHaveCount(0);
});
