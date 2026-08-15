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
          product_items: [],
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
  let tasks: Array<Record<string, unknown>> = [];
  let quoteDrafts: Array<Record<string, unknown>> = [];
  let emailDrafts: Array<Record<string, unknown>> = [];
  const websiteInquiries: Array<Record<string, unknown>> = [];
  await page.route(/\/discovery\/organizations\/org-1\/follow-ups/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(followUps) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/website-inquiries(?:\?.*)?$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(websiteInquiries) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/follow-up-tasks(?:\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    const statusFilter = url.searchParams.get("status_filter");
    const filteredTasks = statusFilter ? tasks.filter((task) => task.status === statusFilter) : tasks;
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(filteredTasks) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/leads\/lead-manual-1\/detail$/, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ...leads[0],
        contacts,
        follow_ups: followUps,
        follow_up_tasks: tasks.filter((task) => task.lead_id === "lead-manual-1"),
        quote_drafts: quoteDrafts.filter((draft) => draft.lead_id === "lead-manual-1"),
      }),
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
      social_profiles: [
        { platform: "Facebook", url: "https://facebook.com/berlin-lighting" },
        { platform: "Instagram", url: "https://instagram.com/berlin-lighting" },
      ],
      source_url: "https://maps.google.com/?cid=berlin-lighting",
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
        social_profiles: payload.social_profiles,
        source_url: payload.source_url,
        email_verification_provider: "",
        email_verification_status: "",
        email_verification_sub_status: "",
        email_verified_at: null,
        is_primary: payload.is_primary,
        created_at: "2026-08-01T08:00:00Z",
      },
    ];
    await route.fulfill({ contentType: "application/json", status: 201, body: JSON.stringify(contacts[0]) });
  });
  await page.route(
    /\/discovery\/organizations\/org-1\/leads\/lead-manual-1\/contacts\/contact-1\/verify-email$/,
    async (route) => {
      expect(route.request().method()).toBe("POST");
      contacts = contacts.map((contact) =>
        contact.id === "contact-1"
          ? {
              ...contact,
              email_verification_provider: "ZeroBounce",
              email_verification_status: "valid",
              email_verification_sub_status: "",
              email_verified_at: "2026-08-01T08:01:00Z",
            }
          : contact
      );
      followUps = [
        {
          id: "follow-up-email-verified-1",
          lead_id: "lead-manual-1",
          actor_user_id: "user-1",
          activity_type: "email_verified",
          content: "Email verification for Anna Weber <anna@berlin-lighting.example>: valid via ZeroBounce.",
          next_follow_up_at: null,
          created_at: "2026-08-01T08:01:00Z",
          lead_company_name: "Berlin Lighting GmbH",
          lead_status: "to_contact",
        },
        ...followUps,
      ];
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(contacts[0]) });
    }
  );
  await page.route(/\/discovery\/organizations\/org-1\/leads\/lead-manual-1\/contacts\/contact-1$/, async (route) => {
    expect(route.request().method()).toBe("DELETE");
    contacts = [];
    await route.fulfill({ status: 204 });
  });
  await page.route(/\/discovery\/organizations\/org-1\/leads\/lead-manual-1\/contacts\/discover$/, async (route) => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().postDataJSON()).toMatchObject({ limit: 10 });
    const discoveredContact = {
      id: "contact-2",
      lead_id: "lead-manual-1",
      name: "Buyer Desk",
      title: "Procurement (Hunter confidence 77, verification accept_all)",
      email: "buyer@berlin-lighting.example",
      phone: "",
      linkedin_url: "",
      whatsapp: "",
      email_verification_provider: "Hunter",
      email_verification_status: "accept_all",
      email_verification_sub_status: "",
      email_verified_at: null,
      is_primary: false,
      created_at: "2026-08-01T08:02:00Z",
    };
    if (!contacts.some((contact) => contact.id === discoveredContact.id)) {
      contacts = [...contacts, discoveredContact];
    }
    followUps = [
      {
        id: "follow-up-contact-discovery-1",
        lead_id: "lead-manual-1",
        actor_user_id: "user-1",
        activity_type: "contact_discovery",
        content: "Hunter found 1 new contact email(s) for Berlin Lighting GmbH.",
        next_follow_up_at: null,
        created_at: "2026-08-01T08:02:00Z",
        lead_company_name: "Berlin Lighting GmbH",
        lead_status: "to_contact",
      },
      ...followUps,
    ];
    await route.fulfill({ contentType: "application/json", status: 201, body: JSON.stringify([discoveredContact]) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/leads\/lead-manual-1\/email-drafts$/, async (route) => {
    const payload = route.request().postDataJSON();
    expect(["contact-1", "contact-2"]).toContain(payload.contact_id);
    const isBatchDraft = payload.contact_id === "contact-2";
    const draft = {
      id: isBatchDraft ? "draft-batch-1" : "draft-1",
      organization_id: "org-1",
      lead_id: "lead-manual-1",
      contact_id: payload.contact_id,
      product_line_id: "product-1",
      created_by_user_id: "user-1",
      reviewed_by_user_id: null,
      sent_by_user_id: null,
      status: "pending_approval",
      subject: "Industrial LED supply discussion for Berlin Lighting GmbH",
      body: isBatchDraft
        ? "Dear Buyer Desk,\\n\\nWe reviewed your public website and can share LED lighting details."
        : "Dear Anna Weber,\\n\\nWe reviewed your public website and can share LED lighting details.",
      provider_message_id: "",
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
      contact_name: isBatchDraft ? "Buyer Desk" : "Anna Weber",
      contact_email: isBatchDraft ? "buyer@berlin-lighting.example" : "anna@berlin-lighting.example",
      current_contact_email: isBatchDraft ? "buyer@berlin-lighting.example" : "anna@berlin-lighting.example",
      contact_email_verification_provider: isBatchDraft ? "Hunter" : "ZeroBounce",
      contact_email_verification_status: isBatchDraft ? "accept_all" : "valid",
      contact_email_verification_sub_status: "",
      contact_email_verified_at: isBatchDraft ? null : "2026-08-01T08:01:00Z",
      contact_source_url: "https://berlin-lighting.example/contact",
      send_blocked: false,
      send_risk_level: isBatchDraft ? "caution" : "safe",
      send_risk_message: isBatchDraft
        ? "邮箱验证结果为 accept_all，建议人工确认后再发送。"
        : "邮箱已通过 ZeroBounce 验证，可以发送。",
    };
    emailDrafts = [
      draft,
      ...emailDrafts.filter((currentDraft) => currentDraft.id !== draft.id),
    ];
    await route.fulfill({ contentType: "application/json", status: 201, body: JSON.stringify(draft) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/email-drafts$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(emailDrafts) });
  });
  await page.route(/\/platform\/organizations\/org-1\/email-delivery$/, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        provider: "smtp",
        configured: true,
        from_email: "sales@example.com",
        from_name: "Trade Axis",
        missing: [],
      }),
    });
  });
  await page.route(/\/platform\/organizations\/org-1\/customer-development-connectors$/, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        connectors: [
          {
            connector_id: "email_finder",
            label: "邮箱查找",
            provider: "Hunter",
            purpose: "按公司域名查找可联系邮箱",
            configured: false,
            missing: ["HUNTER_API_KEY"],
          },
          {
            connector_id: "outbound_email",
            label: "开发信发送",
            provider: "SMTP",
            purpose: "人工确认后发送开发信",
            configured: true,
            missing: [],
          },
        ],
      }),
    });
  });
  let searchSources = [
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
    {
      source_id: "google_cse",
      label: "Google 可编程搜索",
      provider: "Google Programmable Search",
      category: "web_search",
      purpose: "补充全球网页搜索结果",
      base_url: "https://programmablesearchengine.google.com",
      enabled: false,
      configured: false,
      status: "needs_config",
      missing: ["GOOGLE_CSE_API_KEY", "GOOGLE_CSE_CX"],
    },
  ];
  await page.route(/\/platform\/organizations\/org-1\/search-sources$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ sources: searchSources }) });
  });
  await page.route(/\/platform\/organizations\/org-1\/search-sources\/google_cse$/, async (route) => {
    const payload = route.request().postDataJSON();
    searchSources = searchSources.map((source) =>
      source.source_id === "google_cse" ? { ...source, enabled: payload.enabled } : source
    );
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(searchSources.find((source) => source.source_id === "google_cse")),
    });
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
  await page.route(/\/discovery\/organizations\/org-1\/email-drafts\/draft-1\/contact-email$/, async (route) => {
    const payload = route.request().postDataJSON();
    expect(payload).toMatchObject({ email: "new-buyer@berlin-lighting.example" });
    contacts = contacts.map((contact) =>
      contact.id === "contact-1"
        ? {
            ...contact,
            email: payload.email,
            email_verification_provider: "",
            email_verification_status: "",
            email_verification_sub_status: "",
            email_verified_at: null,
          }
        : contact
    );
    emailDrafts = emailDrafts.map((draft) =>
      draft.id === "draft-1"
        ? {
            ...draft,
            contact_email: payload.email,
            current_contact_email: payload.email,
            contact_email_verification_provider: "",
            contact_email_verification_status: "",
            contact_email_verification_sub_status: "",
            contact_email_verified_at: null,
            send_risk_level: "warning",
            send_risk_message: "邮箱尚未验证，建议先验证邮箱再发送。",
          }
        : draft
    );
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(emailDrafts.find((draft) => draft.id === "draft-1")) });
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
      provider_message_id: "fake-provider-message-id",
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

  await page.route(/\/discovery\/organizations\/org-1\/leads\/lead-manual-1\/follow-up-tasks$/, async (route) => {
    const payload = route.request().postDataJSON();
    expect(payload).toMatchObject({
      title: "Prepare 500 sample FOB quote",
      task_type: "quote",
      quote_status: "preparing_quote",
    });
    leads = leads.map((lead) => ({ ...lead, status: "quoting" }));
    tasks = [
      {
        id: "task-1",
        lead_id: "lead-manual-1",
        actor_user_id: "user-1",
        title: payload.title,
        task_type: payload.task_type,
        quote_status: payload.quote_status,
        due_at: payload.due_at,
        status: "open",
        completed_at: null,
        created_at: "2026-08-01T09:30:00Z",
        updated_at: "2026-08-01T09:30:00Z",
        lead_company_name: "Berlin Lighting GmbH",
        lead_status: "quoting",
      },
      ...tasks,
    ];
    await route.fulfill({ contentType: "application/json", status: 201, body: JSON.stringify(tasks[0]) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/follow-up-tasks\/task-1\/complete$/, async (route) => {
    expect(route.request().method()).toBe("POST");
    tasks = tasks.map((task) =>
      task.id === "task-1"
        ? { ...task, status: "done", completed_at: "2026-08-01T10:00:00Z", updated_at: "2026-08-01T10:00:00Z" }
        : task
    );
    followUps = [
      {
        id: "follow-up-task-done-1",
        lead_id: "lead-manual-1",
        actor_user_id: "user-1",
        activity_type: "task_done",
        content: "Completed task: Prepare 500 sample FOB quote",
        next_follow_up_at: null,
        created_at: "2026-08-01T10:00:00Z",
        lead_company_name: "Berlin Lighting GmbH",
        lead_status: "quoting",
      },
      ...followUps,
    ];
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(tasks.find((task) => task.id === "task-1")) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/leads\/lead-manual-1\/quote-drafts$/, async (route) => {
    const payload = route.request().postDataJSON();
    expect(payload).toMatchObject({
      title: "FOB sample quotation",
      currency: "USD",
      incoterm: "FOB",
      line_items: [
        {
          item_name: "LED floodlight 200W",
          quantity: 500,
          unit_price: 12.5,
          unit: "pcs",
        },
      ],
    });
    leads = leads.map((lead) => ({ ...lead, status: "quoting" }));
    quoteDrafts = [
      {
        id: "quote-1",
        organization_id: "org-1",
        lead_id: "lead-manual-1",
        product_line_id: "product-1",
        created_by_user_id: "user-1",
        sent_by_user_id: null,
        status: "draft",
        title: payload.title,
        currency: payload.currency,
        incoterm: payload.incoterm,
        valid_until: payload.valid_until,
        line_items: payload.line_items,
        notes: payload.notes,
        total_amount: 6250,
        created_at: "2026-08-01T10:10:00Z",
        updated_at: "2026-08-01T10:10:00Z",
        sent_at: null,
        lead_company_name: "Berlin Lighting GmbH",
      },
      ...quoteDrafts,
    ];
    await route.fulfill({ contentType: "application/json", status: 201, body: JSON.stringify(quoteDrafts[0]) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/quote-drafts\/quote-1$/, async (route) => {
    const payload = route.request().postDataJSON();
    expect(payload).toMatchObject({
      title: "FOB sample quotation v2",
      line_items: [
        {
          item_name: "LED floodlight 200W",
          quantity: 500,
          unit_price: 11.8,
          unit: "pcs",
        },
      ],
    });
    quoteDrafts = quoteDrafts.map((draft) =>
      draft.id === "quote-1"
        ? { ...draft, ...payload, total_amount: 5900, updated_at: "2026-08-01T10:20:00Z" }
        : draft
    );
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(quoteDrafts.find((draft) => draft.id === "quote-1")) });
  });
  await page.route(/\/discovery\/organizations\/org-1\/quote-drafts\/quote-1\/send$/, async (route) => {
    expect(route.request().method()).toBe("POST");
    quoteDrafts = quoteDrafts.map((draft) =>
      draft.id === "quote-1"
        ? { ...draft, status: "sent", sent_by_user_id: "user-1", sent_at: "2026-08-01T10:30:00Z", updated_at: "2026-08-01T10:30:00Z" }
        : draft
    );
    followUps = [
      {
        id: "follow-up-quote-sent-1",
        lead_id: "lead-manual-1",
        actor_user_id: "user-1",
        activity_type: "quote_sent",
        content: "已人工发送报价给 Berlin Lighting GmbH：FOB sample quotation v2，金额 USD 5900.00",
        next_follow_up_at: "2026-08-04T10:30:00Z",
        created_at: "2026-08-01T10:30:00Z",
        lead_company_name: "Berlin Lighting GmbH",
        lead_status: "quoting",
      },
      ...followUps,
    ];
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(quoteDrafts.find((draft) => draft.id === "quote-1")) });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "CRM 客户" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "客户搜索源" })).toBeVisible();
  await expect(page.getByText("Google Programmable Search")).toBeVisible();
  const sourcePanel = page.getByRole("region", { name: "客户搜索源" });
  await sourcePanel.locator(".connectorItem").filter({ hasText: "Google 可编程搜索" }).getByRole("checkbox").click();
  await expect(sourcePanel.locator(".connectorItem").filter({ hasText: "Google 可编程搜索" }).getByText("已启用")).toBeVisible();

  const crmForm = page.locator(".crmForm");
  await crmForm.getByLabel("所属产品线").selectOption("product-1");
  await crmForm.getByLabel("公司名称").fill("Berlin Lighting GmbH");
  await crmForm.getByLabel("官网").fill("berlin-lighting.example");
  await crmForm.getByLabel("目标市场").fill("德国");
  await crmForm.getByRole("textbox", { name: "客户类型" }).fill("经销商");
  await crmForm.getByLabel("备注 / 来源").fill("展会名片来源");
  await page.getByRole("button", { name: "添加客户" }).click();

  await expect(page.locator(".crmItem").getByText("Berlin Lighting GmbH")).toBeVisible();
  await page.getByLabel("选择 CRM 客户 Berlin Lighting GmbH").check();
  await page.getByRole("button", { name: "批量开发 1 个客户" }).click();
  await expect(page.getByText("批量完成：新增或更新联系方式 1 个")).toBeVisible();
  await expect(page.getByLabel("批量开发处理结果").getByText("已生成待审核草稿：buyer@berlin-lighting.example")).toBeVisible();
  await expect(page.getByLabel("邮件审核队列").getByText("谨慎发送")).toBeVisible();
  await expect(page.getByLabel("邮件审核队列").getByText("邮箱验证：Hunter / accept_all")).toBeVisible();
  await page.getByLabel("关闭审核队列").click();
  await page.getByLabel("搜索 CRM 客户").fill("berlin");
  await expect(page.locator(".crmItem").getByText("Berlin Lighting GmbH")).toBeVisible();
  await page.getByLabel("搜索 CRM 客户").fill("munich");
  await expect(page.locator(".crmItem").getByText("Berlin Lighting GmbH")).toHaveCount(0);
  await page.getByLabel("搜索 CRM 客户").fill("");
  await page.getByLabel("CRM 客户列表").getByRole("button", { name: "详情", exact: true }).click();
  await expect(page.getByLabel("客户详情").getByRole("heading", { name: "Berlin Lighting GmbH" })).toBeVisible();

  await page.locator(".contactForm input[name='name']").fill("Anna Weber");
  await page.locator(".contactForm input[name='title']").fill("Purchasing Manager");
  await page.locator(".contactForm input[name='email']").fill("anna@berlin-lighting.example");
  await page.locator(".contactForm input[name='phone']").fill("+49 30 123456");
  await page.locator(".contactForm input[name='linkedin_url']").fill("https://linkedin.com/in/anna-weber");
  await page.locator(".contactForm input[name='whatsapp']").fill("+49 171 123456");
  await page.locator(".contactForm input[name='facebook_url']").fill("https://facebook.com/berlin-lighting");
  await page.locator(".contactForm input[name='instagram_url']").fill("https://instagram.com/berlin-lighting");
  await page.locator(".contactForm input[name='source_url']").fill("https://maps.google.com/?cid=berlin-lighting");
  await page.locator(".contactForm input[name='is_primary']").check();
  await page.locator(".contactForm button[type='submit']").click();
  await expect(page.locator(".contactList").getByText("Anna Weber")).toBeVisible();
  await expect(page.locator(".contactList").getByText("主要联系人")).toBeVisible();
  await expect(page.locator(".contactList").getByRole("link", { name: "Facebook" })).toBeVisible();
  await expect(page.locator(".contactList").getByRole("link", { name: "Instagram" })).toBeVisible();
  await expect(page.locator(".contactList").getByRole("link", { name: "来源页" })).toBeVisible();
  await expect(page.locator(".contactList").getByText("邮箱验证：未验证")).toBeVisible();
  await page.locator(".contactList li").filter({ hasText: "Anna Weber" }).getByRole("button", { name: "验证邮箱" }).click();
  await expect(page.locator(".contactList").getByText("邮箱验证：ZeroBounce / valid")).toBeVisible();
  await page.getByRole("button", { name: "扫描公开联系方式" }).click();
  await expect(page.locator(".contactList").getByText("Buyer Desk")).toBeVisible();
  await page.locator(".contactList li").filter({ hasText: "Anna Weber" }).getByRole("button", { name: "生成开发信草稿" }).click();
  await expect(page.getByLabel("邮件审核队列").getByText("Berlin Lighting GmbH")).toBeVisible();
  await expect(page.getByLabel("邮件审核队列").getByText("可发送")).toBeVisible();
  await expect(page.getByLabel("邮件审核队列").getByText("邮箱验证：ZeroBounce / valid")).toBeVisible();
  await expect(page.getByLabel("客户邮箱地址")).toHaveValue("anna@berlin-lighting.example");
  await page.getByLabel("客户邮箱地址").fill("new-buyer@berlin-lighting.example");
  await page.getByRole("button", { name: "保存邮箱" }).click();
  await expect(page.getByLabel("客户邮箱地址")).toHaveValue("new-buyer@berlin-lighting.example");
  await expect(page.getByLabel("邮件审核队列").getByText("邮箱验证：未验证")).toBeVisible();
  await page.getByLabel("邮件主题").fill("Updated LED introduction");
  await page.getByLabel("邮件正文").fill("Updated approved body.");
  await page.getByRole("button", { name: "保存修改" }).click();
  await expect(page.getByLabel("邮件主题")).toHaveValue("Updated LED introduction");
  await page.getByRole("button", { name: "批准为待发送" }).click();
  await expect(page.locator(".draftCard .status", { hasText: "待发送" })).toBeVisible();
  await page.getByRole("button", { name: "发送开发信" }).click();
  await expect(page.locator(".draftCard .status", { hasText: "已发送" })).toBeVisible();
  await page.getByLabel("关闭审核队列").click();
  await expect(page.locator(".detailSummary strong").filter({ hasText: "已联系" })).toBeVisible();
  await expect(page.locator(".followUpList").getByText("已人工发送开发信给 Anna Weber")).toBeVisible();
  await expect(page.getByRole("heading", { name: "跟进控制" })).toBeVisible();
  await expect(page.locator(".timeline").getByText("Berlin Lighting GmbH / 已人工发送开发信给 Anna Weber")).toBeVisible();

  await page.locator(".detailForm select[name='status']").selectOption("interested");
  await page.getByLabel("客户备注").fill("客户要求下周提供 FOB 报价。");
  await page.getByRole("button", { name: "保存客户详情" }).click();
  await expect(page.locator(".detailSummary strong").filter({ hasText: "有意向" })).toBeVisible();

  await page.locator(".taskForm select[name='task_type']").selectOption("quote");
  await page.locator(".taskForm select[name='quote_status']").selectOption("preparing_quote");
  await page.locator(".taskForm textarea[name='title']").fill("Prepare 500 sample FOB quote");
  await page.locator(".taskForm button[type='submit']").click();
  const customerDrawer = page.getByLabel("客户详情", { exact: true });
  await expect(customerDrawer.locator(".taskList").getByText("Prepare 500 sample FOB quote")).toBeVisible();
  await expect(page.locator(".detailSummary strong").filter({ hasText: "报价中" })).toBeVisible();
  await expect(
    page.getByLabel("客户阶段漏斗").locator(".funnelStage").filter({ hasText: "报价中" }).getByText("1 个 / 100%")
  ).toBeVisible();
  await expect(page.getByLabel("待处理动作").locator(".actionSignal").filter({ hasText: "待办任务" }).locator("strong")).toHaveText("1");
  await customerDrawer.locator(".taskList").getByRole("button", { name: "标记完成" }).click();
  await expect(customerDrawer.locator(".taskList").getByRole("button", { name: "已完成" })).toBeVisible();
  await expect(page.getByLabel("待处理动作").locator(".actionSignal").filter({ hasText: "待办任务" }).locator("strong")).toHaveText("0");
  await expect(page.locator(".followUpList").getByText("Completed task: Prepare 500 sample FOB quote")).toBeVisible();

  await page.locator(".quoteForm input[name='title']").fill("FOB sample quotation");
  await page.locator(".quoteForm input[name='item_name']").fill("LED floodlight 200W");
  await page.locator(".quoteForm input[name='quantity']").fill("500");
  await page.locator(".quoteForm input[name='unit_price']").fill("12.5");
  await page.locator(".quoteForm input[name='line_notes']").fill("Sample batch");
  await page.locator(".quoteForm textarea[name='notes']").fill("Manual quotation draft. Review before sending.");
  await page.locator(".quoteForm button[type='submit']").click();
  await expect(customerDrawer.locator(".quoteDraftList").getByText("USD 6250.00")).toBeVisible();
  await page.locator(".quoteDraftItem input[name='title']").fill("FOB sample quotation v2");
  await page.locator(".quoteDraftItem input[name='unit_price']").fill("11.8");
  await page.locator(".quoteDraftItem textarea[name='notes']").fill("Updated after margin review.");
  await page.locator(".quoteDraftItem").getByRole("button", { name: "保存报价草稿" }).click();
  await expect(customerDrawer.locator(".quoteDraftList").getByText("USD 5900.00")).toBeVisible();
  await page.locator(".quoteDraftItem").getByRole("button", { name: "标记已发送报价" }).click();
  await expect(customerDrawer.locator(".quoteDraftHeader span").filter({ hasText: "已发送报价" })).toBeVisible();
  await expect(page.locator(".followUpList").getByText("已人工发送报价给 Berlin Lighting GmbH")).toBeVisible();

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

  await page.getByLabel("客户状态筛选").selectOption("interested");
  await expect(page.locator(".crmItem").getByText("Berlin Lighting GmbH")).toBeVisible();
  await page.getByLabel("客户状态筛选").selectOption("quoting");
  await expect(page.locator(".crmItem").getByText("Berlin Lighting GmbH")).toHaveCount(0);
  await page.getByLabel("客户状态筛选").selectOption("all");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByLabel("CRM 客户列表").getByRole("button", { name: "删除" }).click();
  await expect(page.locator(".crmItem").getByText("Berlin Lighting GmbH")).toHaveCount(0);
});
