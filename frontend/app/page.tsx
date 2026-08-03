"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  convertWebsiteInquiry,
  createContact,
  createEmailDraft,
  createFollowUp,
  createProductLine,
  createManualLead,
  deleteContact,
  deleteLead,
  getLeadDetail,
  listEmailDrafts,
  listFollowUps,
  listLeads,
  listProductLines,
  listWebsiteInquiries,
  markEmailDraftSent,
  reviewEmailDraft,
  startDiscovery,
  updateEmailDraft,
  updateLeadDetail,
  type ContactRecord,
  type EmailDraft,
  type FollowUpRecord,
  type Lead,
  type LeadDetail,
  type LeadStatus,
  type ProductLine,
  type WebsiteInquiry,
  type WebsiteInquiryStatus,
} from "../lib/api";
import { clearSession, readSession, type Session } from "../lib/auth";

type Metric = {
  label: string;
  value: string;
  note: string;
  tone: "blue" | "cyan" | "orange" | "green";
};

const navItems = ["总览", "客户搜索 Agent", "CRM", "独立站询盘", "邮件审核", "收件箱", "知识库"];

const bucketLabel = {
  priority_recommendation: "优先推荐",
  needs_enrichment: "待补充信息",
  not_qualified: "暂不合格",
} as const;

const leadStatusLabel: Record<LeadStatus, string> = {
  new: "新客户",
  to_contact: "待联系",
  contacted: "已联系",
  interested: "有意向",
  quoting: "报价中",
  won: "已成交",
  not_fit: "暂不合适",
};

const emailDraftStatusLabel: Record<EmailDraft["status"], string> = {
  pending_approval: "待审批",
  ready_to_send: "待发送",
  sent: "已发送",
  rejected: "已驳回",
};

const websiteInquiryStatusLabel: Record<WebsiteInquiryStatus, string> = {
  new: "新询盘",
  converted: "已转客户",
  dismissed: "已忽略",
};

function isCrmLead(lead: Lead) {
  return lead.status !== "new";
}

function parseCsv(value: FormDataEntryValue | null) {
  return String(value ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function scoreClass(score: number) {
  if (score >= 90) return "score scoreHigh";
  if (score >= 70) return "score scoreMedium";
  return "score scoreLow";
}

function bucketClass(bucket: Lead["bucket"]) {
  if (bucket === "priority_recommendation") return "status statusPriority";
  if (bucket === "needs_enrichment") return "status statusResearch";
  return "status statusQualified";
}

function MetricTile({ label, value, note, tone }: Metric) {
  return (
    <article className="metricTile">
      <span className={`metricRail ${tone}`} aria-hidden="true" />
      <p>{label}</p>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  );
}

function buildMetrics(leads: Lead[], drafts: EmailDraft[], followUps: FollowUpRecord[]): Metric[] {
  const newLeads = leads.filter((lead) => lead.status === "new").length;
  const priorityLeads = leads.filter((lead) => lead.bucket === "priority_recommendation").length;
  const pendingDrafts = drafts.filter((draft) => draft.status === "pending_approval").length;
  const replies = followUps.filter((record) => record.activity_type === "reply").length;
  return [
    { label: "新增线索", value: String(newLeads), note: "未入库客户线索", tone: "blue" },
    { label: "优先客户", value: String(priorityLeads), note: "证据评分优先推荐", tone: "cyan" },
    { label: "待审核邮件", value: String(pendingDrafts), note: "坚持人工审批", tone: "orange" },
    { label: "客户回复", value: String(replies), note: "人工记录或邮箱同步", tone: "green" },
  ];
}

function csvCell(value: string | number | null | undefined) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function buildActivityCsv(
  leads: Lead[],
  drafts: EmailDraft[],
  followUps: FollowUpRecord[]
) {
  const rows = [
    ["type", "company", "status", "subject_or_activity", "detail", "next_follow_up_at", "created_or_updated_at"],
    ...leads.map((lead) => [
      "lead",
      lead.company_name,
      leadStatusLabel[lead.status],
      bucketLabel[lead.bucket],
      `${lead.target_market} / ${lead.buyer_profile ?? "不限类型"} / ${lead.website}`,
      "",
      "",
    ]),
    ...drafts.map((draft) => [
      "email_draft",
      draft.lead_company_name,
      emailDraftStatusLabel[draft.status],
      draft.subject,
      `${draft.contact_name} / ${draft.contact_email}`,
      "",
      draft.sent_at ?? draft.reviewed_at ?? draft.updated_at,
    ]),
    ...followUps.map((record) => [
      "follow_up",
      record.lead_company_name ?? "",
      record.lead_status ? leadStatusLabel[record.lead_status] : "",
      followUpActivityLabel(record.activity_type),
      record.content,
      record.next_follow_up_at ?? "",
      record.created_at,
    ]),
  ];
  return rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
}

function ProductLineSetup({
  productLines,
  loading,
  creating,
  onCreate,
}: {
  productLines: ProductLine[];
  loading: boolean;
  creating: boolean;
  onCreate: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <section className="productPanel" aria-labelledby="product-lines-title">
      <div className="sectionHeader">
        <div>
          <p className="sectionLabel">产品情报</p>
          <h2 id="product-lines-title">产品线</h2>
        </div>
        <span className="countBadge">{loading ? "加载中" : `已配置 ${productLines.length} 个`}</span>
      </div>
      <div className="productContent">
        <form className="productForm" onSubmit={onCreate}>
          <label>
            产品线名称
            <input name="name" required placeholder="工业 LED 照明" />
          </label>
          <label>
            产品关键词
            <input name="keywords" required placeholder="LED 投光灯, 仓库照明" />
          </label>
          <label>
            客户类型
            <input name="buyer_profiles" required placeholder="经销商, 工程采购商" />
          </label>
          <label>
            目标区域
            <input name="target_regions" required placeholder="欧洲, 北美" />
          </label>
          <label className="wideField">
            产品描述
            <input name="description" placeholder="商业与工业改造照明方案" />
          </label>
          <button className="primaryButton" type="submit" disabled={creating}>
            {creating ? "创建中..." : "创建产品线"}
          </button>
        </form>
        <div className="productList" aria-label="已配置产品线">
          {productLines.length === 0 ? (
            <div className="emptyState">请先创建第一个产品线，再开始客户搜索。</div>
          ) : (
            productLines.map((productLine) => (
              <article className="productItem" key={productLine.id}>
                <strong>{productLine.name}</strong>
                <span>{productLine.product_keywords.join(", ") || "暂无关键词"}</span>
                <small>
                  {productLine.buyer_profiles.join(", ") || "暂无客户类型"} /{" "}
                  {productLine.target_regions.join(", ") || "暂无目标区域"}
                </small>
              </article>
            ))
          )}
        </div>
      </div>
    </section>
  );
}

function CustomerAgent({
  productLines,
  selectedProductLineId,
  targetMarket,
  buyerProfile,
  running,
  runMessage,
  onProductLineChange,
  onTargetMarketChange,
  onBuyerProfileChange,
  onRun,
}: {
  productLines: ProductLine[];
  selectedProductLineId: string;
  targetMarket: string;
  buyerProfile: string;
  running: boolean;
  runMessage: string;
  onProductLineChange: (value: string) => void;
  onTargetMarketChange: (value: string) => void;
  onBuyerProfileChange: (value: string) => void;
  onRun: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const selectedProductLine = productLines.find((item) => item.id === selectedProductLineId);
  const buyerProfiles = selectedProductLine?.buyer_profiles ?? [];

  return (
    <section className="agentPanel" aria-labelledby="customer-agent-title">
      <div className="agentIntro">
        <p className="sectionLabel">Agent 01</p>
        <h2 id="customer-agent-title">客户搜索 Agent</h2>
        <p>按产品、国家和客户类型搜索公司，保留公开证据并给出优先级评分。</p>
        <div className="agentChecks" aria-label="搜索检查项">
          <span>网站已核验</span><span>业务证据</span><span>联系线索</span>
        </div>
      </div>
      <form className="agentForm" onSubmit={onRun}>
        <label>
          产品线
          <select
            aria-label="搜索产品线"
            name="product_line_id"
            required
            value={selectedProductLineId}
            onChange={(event) => onProductLineChange(event.target.value)}
          >
            <option value="">选择产品线</option>
            {productLines.map((productLine) => (
              <option key={productLine.id} value={productLine.id}>{productLine.name}</option>
            ))}
          </select>
        </label>
        <label>
          目标市场
          <input
            aria-label="搜索目标市场"
            name="target_market"
            required
            value={targetMarket}
            onChange={(event) => onTargetMarketChange(event.target.value)}
          />
        </label>
        <label>
          客户类型
          <select
            aria-label="搜索客户类型"
            name="buyer_profile"
            value={buyerProfile}
            onChange={(event) => onBuyerProfileChange(event.target.value)}
          >
            <option value="">不限客户类型</option>
            {buyerProfiles.map((profile) => (
              <option key={profile} value={profile}>{profile}</option>
            ))}
          </select>
        </label>
        <button className="primaryButton" type="submit" disabled={running || !selectedProductLineId}>
          {running ? "正在生成客户列表..." : "开始搜索客户"}
        </button>
        <div className={`runStatus ${runMessage.includes("完成") ? "runComplete" : ""}`} aria-live="polite">
          <span className="statusDot" aria-hidden="true" />
          {runMessage}
        </div>
      </form>
    </section>
  );
}

function LeadTable({
  leads,
  priorityOnly,
  selectedLeadIds,
  savingToCrm,
  onPriorityToggle,
  onSelectLead,
  onSelectAllVisible,
  onSaveToCrm,
  onOpenDetail,
}: {
  leads: Lead[];
  priorityOnly: boolean;
  selectedLeadIds: string[];
  savingToCrm: boolean;
  onPriorityToggle: () => void;
  onSelectLead: (leadId: string, selected: boolean) => void;
  onSelectAllVisible: (leadIds: string[], selected: boolean) => void;
  onSaveToCrm: () => void;
  onOpenDetail: (leadId: string) => void;
}) {
  const displayedLeads = priorityOnly
    ? leads.filter((lead) => lead.bucket === "priority_recommendation")
    : leads;
  const selectableLeadIds = displayedLeads
    .filter((lead) => !isCrmLead(lead))
    .map((lead) => lead.id);
  const selectedVisibleIds = selectableLeadIds.filter((leadId) => selectedLeadIds.includes(leadId));
  const allVisibleSelected =
    selectableLeadIds.length > 0 && selectedVisibleIds.length === selectableLeadIds.length;

  return (
    <section className="dataSection" aria-labelledby="lead-results-title">
      <div className="sectionHeader">
        <div>
          <p className="sectionLabel">客户搜索 Agent 输出</p>
          <h2 id="lead-results-title">已发现公司</h2>
        </div>
        <div className="tableActions">
          <button className="textButton" type="button" onClick={onPriorityToggle}>
            {priorityOnly ? "显示全部线索" : "只看优先客户"}
          </button>
          <button
            className="outlineButton"
            type="button"
            disabled={savingToCrm || selectedLeadIds.length === 0}
            onClick={onSaveToCrm}
          >
            {savingToCrm
              ? "保存中..."
              : selectedLeadIds.length > 0
                ? `保存 ${selectedLeadIds.length} 个到 CRM`
                : "保存到 CRM"}
          </button>
        </div>
      </div>
      <div className="tableWrap">
        {leads.length === 0 ? (
          <div className="emptyState tableEmpty">运行客户搜索后，这里会显示带证据的客户线索。</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th scope="col" className="selectColumn">
                  <input
                    type="checkbox"
                    aria-label="选择全部未入库线索"
                    checked={allVisibleSelected}
                    disabled={selectableLeadIds.length === 0}
                    onChange={(event) => onSelectAllVisible(selectableLeadIds, event.currentTarget.checked)}
                  />
                </th>
                <th scope="col">公司</th>
                <th scope="col">市场 / 客户类型</th>
                <th scope="col">证据</th>
                <th scope="col">评分原因</th>
                <th scope="col">分数</th>
                <th scope="col">分组</th>
                <th scope="col">CRM 状态</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {displayedLeads.map((lead) => (
                <tr key={lead.id}>
                  <td className="selectColumn">
                    <input
                      type="checkbox"
                      aria-label={`选择 ${lead.company_name}`}
                      checked={selectedLeadIds.includes(lead.id)}
                      disabled={isCrmLead(lead)}
                      onChange={(event) => onSelectLead(lead.id, event.currentTarget.checked)}
                    />
                  </td>
                  <td><strong>{lead.company_name}</strong><span>{lead.website}</span></td>
                  <td><strong className="contactName">{lead.target_market}</strong><span>{lead.buyer_profile ?? "不限类型"}</span></td>
                  <td className="evidence">
                    {lead.evidence.length > 0 ? lead.evidence[0].source_excerpt : "暂无来源摘要"}
                  </td>
                  <td className="evidence">
                    {lead.reasons.join("; ") || lead.missing_signals.join("; ") || "暂无评分细节"}
                  </td>
                  <td><span className={scoreClass(lead.score)}>{lead.score}</span></td>
                  <td><span className={bucketClass(lead.bucket)}>{bucketLabel[lead.bucket]}</span></td>
                  <td><span className={isCrmLead(lead) ? "status statusQualified" : "status statusNew"}>{leadStatusLabel[lead.status]}</span></td>
                  <td>
                    <button className="textButton" type="button" onClick={() => onOpenDetail(lead.id)}>
                      查看详情
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}

function CRMCustomerManager({
  leads,
  productLines,
  selectedProductLineId,
  creating,
  deletingLeadId,
  onCreate,
  onDelete,
  onOpenDetail,
}: {
  leads: Lead[];
  productLines: ProductLine[];
  selectedProductLineId: string;
  creating: boolean;
  deletingLeadId: string;
  onCreate: (event: FormEvent<HTMLFormElement>) => void;
  onDelete: (leadId: string) => void;
  onOpenDetail: (leadId: string) => void;
}) {
  const [crmSearch, setCrmSearch] = useState("");
  const [crmStatusFilter, setCrmStatusFilter] = useState<LeadStatus | "all">("all");
  const allCrmLeads = leads.filter(isCrmLead);
  const normalizedSearch = crmSearch.trim().toLowerCase();
  const crmLeads = allCrmLeads.filter((lead) => {
    const matchesStatus = crmStatusFilter === "all" || lead.status === crmStatusFilter;
    const matchesSearch =
      !normalizedSearch ||
      [
        lead.company_name,
        lead.website,
        lead.target_market,
        lead.buyer_profile ?? "",
      ].some((value) => value.toLowerCase().includes(normalizedSearch));
    return matchesStatus && matchesSearch;
  });

  return (
    <section className="crmPanel" aria-labelledby="crm-customers-title">
      <div className="sectionHeader">
        <div>
          <p className="sectionLabel">CRM 客户管理</p>
          <h2 id="crm-customers-title">CRM 客户</h2>
        </div>
        <span className="countBadge">{crmLeads.length} / {allCrmLeads.length} 个客户</span>
      </div>
      <div className="crmContent">
        <form className="crmForm" onSubmit={onCreate}>
          <label>
            所属产品线
            <select
              key={selectedProductLineId || "manual-product-line"}
              name="product_line_id"
              required
              defaultValue={selectedProductLineId}
            >
              <option value="">选择产品线</option>
              {productLines.map((productLine) => (
                <option key={productLine.id} value={productLine.id}>{productLine.name}</option>
              ))}
            </select>
          </label>
          <label>
            公司名称
            <input name="company_name" required placeholder="例如：Berlin Lighting GmbH" />
          </label>
          <label>
            官网
            <input name="website" required placeholder="example.com 或 https://example.com" />
          </label>
          <label>
            目标市场
            <input name="target_market" required placeholder="德国、美国、日本" />
          </label>
          <label>
            客户类型
            <input name="buyer_profile" placeholder="经销商、进口商、工程采购商" />
          </label>
          <label className="wideField">
            备注 / 来源
            <input name="notes" placeholder="例如：展会沟通、老客户介绍、名片来源" />
          </label>
          <button className="primaryButton" type="submit" disabled={creating || productLines.length === 0}>
            {creating ? "添加中..." : "添加客户"}
          </button>
        </form>
        <div className="crmList" aria-label="CRM 客户列表">
          <div className="crmTools" aria-label="CRM 筛选">
            <label>
              搜索 CRM 客户
              <input
                value={crmSearch}
                onChange={(event) => setCrmSearch(event.currentTarget.value)}
                placeholder="公司、官网、市场或客户类型"
              />
            </label>
            <label>
              客户状态筛选
              <select
                value={crmStatusFilter}
                onChange={(event) => setCrmStatusFilter(event.currentTarget.value as LeadStatus | "all")}
              >
                <option value="all">全部状态</option>
                {Object.entries(leadStatusLabel)
                  .filter(([value]) => value !== "new")
                  .map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
              </select>
            </label>
          </div>
          {crmLeads.length === 0 ? (
            <div className="emptyState">
              {allCrmLeads.length === 0
                ? "暂无 CRM 客户。你可以手动添加客户，或从搜索结果勾选线索保存到 CRM。"
                : "没有匹配当前筛选条件的 CRM 客户。"}
            </div>
          ) : (
            crmLeads.map((lead) => (
              <article className="crmItem" key={lead.id}>
                <div>
                  <strong>{lead.company_name}</strong>
                  <span>{lead.website}</span>
                  <small>{lead.target_market} / {lead.buyer_profile ?? "不限类型"} / {leadStatusLabel[lead.status]}</small>
                </div>
                <button
                  className="textButton"
                  type="button"
                  onClick={() => onOpenDetail(lead.id)}
                >
                  详情
                </button>
                <button
                  className="dangerTextButton"
                  type="button"
                  disabled={deletingLeadId === lead.id}
                  onClick={() => onDelete(lead.id)}
                >
                  {deletingLeadId === lead.id ? "删除中..." : "删除"}
                </button>
              </article>
            ))
          )}
        </div>
      </div>
    </section>
  );
}

function WebsiteInquiryPanel({
  inquiries,
  productLines,
  organizationId,
  loading,
  convertingInquiryId,
  statusFilter,
  onStatusFilterChange,
  onRefresh,
  onConvert,
}: {
  inquiries: WebsiteInquiry[];
  productLines: ProductLine[];
  organizationId: string;
  loading: boolean;
  convertingInquiryId: string;
  statusFilter: WebsiteInquiryStatus | "all";
  onStatusFilterChange: (status: WebsiteInquiryStatus | "all") => void;
  onRefresh: () => void;
  onConvert: (inquiryId: string) => void;
}) {
  const productNameById = new Map(productLines.map((productLine) => [productLine.id, productLine.name]));
  const newCount = inquiries.filter((inquiry) => inquiry.status === "new").length;
  const [formOrigin, setFormOrigin] = useState("");
  useEffect(() => {
    setFormOrigin(window.location.origin);
  }, []);
  const formBaseUrl = formOrigin ? `${formOrigin}/inquiry` : "/inquiry";
  const inquiryFormUrl = (productLine: ProductLine) =>
    `${formBaseUrl}?organization_id=${encodeURIComponent(organizationId)}&product_line_id=${encodeURIComponent(productLine.id)}&product=${encodeURIComponent(productLine.name)}`;

  return (
    <section className="inquiryPanel" aria-labelledby="website-inquiry-title">
      <div className="sectionHeader">
        <div>
          <p className="sectionLabel">独立站数据接口</p>
          <h2 id="website-inquiry-title">独立站询盘</h2>
        </div>
        <div className="tableActions">
          <label className="inlineFilter">
            状态
            <select
              value={statusFilter}
              onChange={(event) => onStatusFilterChange(event.currentTarget.value as WebsiteInquiryStatus | "all")}
            >
              <option value="new">新询盘</option>
              <option value="converted">已转客户</option>
              <option value="dismissed">已忽略</option>
              <option value="all">全部</option>
            </select>
          </label>
          <button className="textButton" type="button" onClick={onRefresh}>
            刷新
          </button>
        </div>
      </div>
      <div className="inquirySummary">
        <strong>{newCount}</strong>
        <span>条新询盘可转入 CRM。未来独立站表单提交后，会先进入这里，由后台人工确认再转客户。</span>
      </div>
      <div className="inquiryLinkList" aria-label="独立站表单链接">
        {productLines.length === 0 ? (
          <div className="emptyState inquiryEmpty">先创建产品线，再生成对应的公开询盘表单链接。</div>
        ) : (
          productLines.map((productLine) => {
            const url = inquiryFormUrl(productLine);
            return (
              <article className="inquiryLinkItem" key={productLine.id}>
                <div>
                  <strong>{productLine.name}</strong>
                  <span>{url}</span>
                </div>
                <div>
                  <a className="textButton" href={url} target="_blank" rel="noreferrer">打开表单</a>
                  <button
                    className="textButton"
                    type="button"
                    onClick={() => void navigator.clipboard.writeText(url)}
                  >
                    复制链接
                  </button>
                </div>
              </article>
            );
          })
        )}
      </div>
      {loading ? (
        <div className="emptyState inquiryEmpty">正在加载独立站询盘...</div>
      ) : inquiries.length === 0 ? (
        <div className="emptyState inquiryEmpty">当前筛选下暂无询盘。后续独立站上线后，表单数据会进入这个队列。</div>
      ) : (
        <div className="inquiryList" aria-label="独立站询盘列表">
          {inquiries.map((inquiry) => (
            <article className="inquiryItem" key={inquiry.id}>
              <div className="inquiryMain">
                <div>
                  <strong>{inquiry.company_name}</strong>
                  <span>{inquiry.contact_name} / {inquiry.email}</span>
                </div>
                <span className={inquiry.status === "new" ? "status statusPriority" : "status statusQualified"}>
                  {websiteInquiryStatusLabel[inquiry.status]}
                </span>
              </div>
              <p>{inquiry.message}</p>
              <div className="inquiryMeta">
                <span>{inquiry.product_line_id ? productNameById.get(inquiry.product_line_id) ?? "产品线已停用" : "未绑定产品线"}</span>
                <span>{inquiry.target_market || "未填写市场"}</span>
                <span>{formatDateTime(inquiry.created_at)}</span>
              </div>
              <div className="inquiryActions">
                {inquiry.website && <a href={inquiry.website} target="_blank" rel="noreferrer">官网</a>}
                {inquiry.source_url && <a href={inquiry.source_url} target="_blank" rel="noreferrer">来源页</a>}
                <button
                  className="outlineButton"
                  type="button"
                  disabled={inquiry.status !== "new" || convertingInquiryId === inquiry.id}
                  onClick={() => onConvert(inquiry.id)}
                >
                  {convertingInquiryId === inquiry.id ? "转换中..." : inquiry.status === "new" ? "转为 CRM 客户" : "已处理"}
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function ReviewQueue({
  drafts,
  loading,
  onOpen,
  onOpenDraft,
}: {
  drafts: EmailDraft[];
  loading: boolean;
  onOpen: () => void;
  onOpenDraft: (draftId: string) => void;
}) {
  const pendingCount = drafts.filter((draft) => draft.status === "pending_approval").length;
  const readyCount = drafts.filter((draft) => draft.status === "ready_to_send").length;
  return (
    <section className="reviewPanel" aria-labelledby="review-title">
      <div className="sectionHeader compact">
        <div>
          <p className="sectionLabel">人工审批</p>
          <h2 id="review-title">开发信审核</h2>
        </div>
        <button className="textButton" type="button" onClick={onOpen}>
          审核 {pendingCount} 封草稿
        </button>
      </div>
      {loading ? (
        <div className="emptyState">正在加载审批队列...</div>
      ) : drafts.length === 0 ? (
        <div className="emptyState">暂无开发信草稿。先在客户详情页为联系人生成草稿。</div>
      ) : (
        drafts.slice(0, 2).map((draft) => (
          <button className="reviewItem reviewButton" type="button" key={draft.id} onClick={() => onOpenDraft(draft.id)}>
            <div className="avatar blueAvatar">{draft.contact_name.slice(0, 2).toUpperCase() || "EM"}</div>
            <div><strong>{draft.lead_company_name}</strong><span>{draft.contact_name} / {emailDraftStatusLabel[draft.status]}</span></div>
            <span className="qualityMark">{draft.evidence_snapshot.length}</span>
          </button>
        ))
      )}
      <div className="reviewFooter"><span>人工审批已启用</span><strong>{pendingCount} 封草稿待审</strong></div>
      <div className="reviewFooter"><span>待发送箱</span><strong>{readyCount} 封邮件待人工发送</strong></div>
    </section>
  );
}

function FollowUpTimeline({
  records,
  loading,
  onRefresh,
}: {
  records: FollowUpRecord[];
  loading: boolean;
  onRefresh: () => void;
}) {
  return (
    <section className="timelinePanel" aria-labelledby="followup-title">
      <div className="sectionHeader compact">
        <div>
          <p className="sectionLabel">销售执行</p>
          <h2 id="followup-title">跟进控制</h2>
        </div>
        <button className="iconTextButton" type="button" onClick={onRefresh}>刷新</button>
      </div>
      {loading ? (
        <div className="emptyState">正在加载跟进记录...</div>
      ) : records.length === 0 ? (
        <div className="emptyState">暂无跟进记录。发送开发信或在客户详情页添加跟进后，这里会显示下一步动作。</div>
      ) : (
        <ol className="timeline">
          {records.slice(0, 5).map((record) => (
            <li key={record.id}>
              <time>{formatTimelineTime(record.next_follow_up_at ?? record.created_at)}</time>
              <span className={`timelineDot ${record.activity_type === "email_sent" ? "cyanDot" : "blueDot"}`} />
              <div>
                <strong>{followUpActivityLabel(record.activity_type)}</strong>
                <p>{record.lead_company_name ?? "客户"} / {record.content}</p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function InboxPanel({
  records,
  loading,
  onRefresh,
}: {
  records: FollowUpRecord[];
  loading: boolean;
  onRefresh: () => void;
}) {
  const replies = records.filter((record) => record.activity_type === "reply");
  return (
    <section className="timelinePanel" aria-labelledby="inbox-title">
      <div className="sectionHeader compact">
        <div>
          <p className="sectionLabel">收件箱</p>
          <h2 id="inbox-title">客户回复</h2>
        </div>
        <button className="iconTextButton" type="button" onClick={onRefresh}>刷新</button>
      </div>
      {loading ? (
        <div className="emptyState">正在加载客户回复...</div>
      ) : replies.length === 0 ? (
        <div className="emptyState">暂无客户回复。你可以在客户详情页把回复内容记录为“客户回复”。</div>
      ) : (
        <div className="inboxList" aria-label="客户回复列表">
          {replies.slice(0, 5).map((record) => (
            <article className="inboxItem" key={record.id}>
              <div>
                <strong>{record.lead_company_name ?? "客户"}</strong>
                <time>{formatDateTime(record.created_at)}</time>
              </div>
              <p>{record.content}</p>
              <small>{record.lead_status ? leadStatusLabel[record.lead_status] : "未同步状态"}</small>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function ReviewDrawer({
  open,
  draft,
  saving,
  reviewing,
  onClose,
  onSave,
  onApprove,
  onMarkSent,
  onReject,
}: {
  open: boolean;
  draft: EmailDraft | null;
  saving: boolean;
  reviewing: boolean;
  onClose: () => void;
  onSave: (event: FormEvent<HTMLFormElement>) => void;
  onApprove: () => void;
  onMarkSent: () => void;
  onReject: (event: FormEvent<HTMLFormElement>) => void;
}) {
  if (!open) return null;

  return (
    <div className="drawerBackdrop" role="presentation" onMouseDown={onClose}>
      <aside className="reviewDrawer" aria-label="邮件审核队列" onMouseDown={(event) => event.stopPropagation()}>
        <div className="drawerHeader">
          <div><p className="sectionLabel">邮件 Agent</p><h2>邮件审核队列</h2></div>
          <button className="closeButton" type="button" aria-label="关闭审核队列" onClick={onClose}>x</button>
        </div>
        <p className="drawerCopy">每封开发信必须人工查看、修改并审批。批准后只进入“待发送”，不会自动发出。</p>
        {!draft ? (
          <div className="emptyState drawerLoading">暂无待审核草稿。请先在客户详情页选择联系人生成开发信。</div>
        ) : (
          <>
            <article className="draftCard">
              <span className={draft.status === "ready_to_send" || draft.status === "sent" ? "status statusQualified" : "status statusPriority"}>
                {emailDraftStatusLabel[draft.status]}
              </span>
              <h3>{draft.lead_company_name}</h3>
              <p>To: {draft.contact_name} / {draft.contact_email}</p>
              <div className="draftEvidence">
                {draft.evidence_snapshot.length === 0 ? (
                  <span>暂无证据快照</span>
                ) : (
                  draft.evidence_snapshot.map((item) => <span key={`${item.signal_name}-${item.source_url}`}>{item.signal_name}</span>)
                )}
              </div>
            </article>
            <form className="draftEditForm" onSubmit={onSave} key={`draft-${draft.id}`}>
              <label>
                邮件主题
                <input name="subject" defaultValue={draft.subject} disabled={draft.status !== "pending_approval"} />
              </label>
              <label>
                邮件正文
                <textarea name="body" defaultValue={draft.body} disabled={draft.status !== "pending_approval"} />
              </label>
              <div className="drawerActions">
                <button className="outlineButton" type="submit" disabled={saving || draft.status !== "pending_approval"}>
                  {saving ? "保存中..." : "保存修改"}
                </button>
                <button className="primaryButton" type="button" disabled={reviewing || draft.status !== "pending_approval"} onClick={onApprove}>
                  {reviewing ? "审批中..." : "批准为待发送"}
                </button>
                <button className="primaryButton" type="button" disabled={reviewing || draft.status !== "ready_to_send"} onClick={onMarkSent}>
                  {reviewing ? "记录中..." : "标记已发送"}
                </button>
              </div>
            </form>
            <form className="rejectForm" onSubmit={onReject} key={`reject-${draft.id}`}>
              <label>
                驳回原因
                <input name="rejection_reason" defaultValue={draft.rejection_reason} placeholder="例如：需要补充客户采购场景后再发送" disabled={draft.status !== "pending_approval"} />
              </label>
              <button className="dangerTextButton" type="submit" disabled={reviewing || draft.status !== "pending_approval"}>
                驳回草稿
              </button>
            </form>
          </>
        )}
      </aside>
    </div>
  );
}

function formatDateTime(value: string | null) {
  if (!value) return "未设置";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function formatTimelineTime(value: string | null) {
  if (!value) return "待定";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

function followUpActivityLabel(activityType: string) {
  if (activityType === "email_sent") return "开发信已发送";
  if (activityType === "reply") return "客户回复";
  if (activityType === "email") return "邮件跟进";
  if (activityType === "call") return "电话跟进";
  if (activityType === "meeting") return "会议跟进";
  return "客户备注";
}

function CustomerDetailDrawer({
  detail,
  loading,
  saving,
  addingContact,
  addingFollowUp,
  deletingContactId,
  generatingDraftContactId,
  onClose,
  onSave,
  onAddContact,
  onDeleteContact,
  onCreateEmailDraft,
  onAddFollowUp,
}: {
  detail: LeadDetail | null;
  loading: boolean;
  saving: boolean;
  addingContact: boolean;
  addingFollowUp: boolean;
  deletingContactId: string;
  generatingDraftContactId: string;
  onClose: () => void;
  onSave: (event: FormEvent<HTMLFormElement>) => void;
  onAddContact: (event: FormEvent<HTMLFormElement>) => void;
  onDeleteContact: (contactId: string) => void;
  onCreateEmailDraft: (contactId: string) => void;
  onAddFollowUp: (event: FormEvent<HTMLFormElement>) => void;
}) {
  if (!detail && !loading) return null;

  return (
    <div className="drawerBackdrop" role="presentation" onMouseDown={onClose}>
      <aside className="customerDrawer" aria-label="客户详情" onMouseDown={(event) => event.stopPropagation()}>
        <div className="drawerHeader">
          <div>
            <p className="sectionLabel">客户详情</p>
            <h2>{detail?.company_name ?? "正在加载客户..."}</h2>
          </div>
          <button className="closeButton" type="button" aria-label="关闭客户详情" onClick={onClose}>x</button>
        </div>
        {loading || !detail ? (
          <div className="emptyState drawerLoading">正在加载客户详情...</div>
        ) : (
          <div className="customerDetailContent">
            <section className="detailSummary">
              <div>
                <span>官网</span>
                <strong>{detail.website}</strong>
              </div>
              <div>
                <span>市场 / 类型</span>
                <strong>{detail.target_market} / {detail.buyer_profile ?? "不限类型"}</strong>
              </div>
              <div>
                <span>状态</span>
                <strong>{leadStatusLabel[detail.status]}</strong>
              </div>
              <div>
                <span>评分</span>
                <strong>{detail.score}</strong>
              </div>
            </section>

            <form className="detailForm" onSubmit={onSave} key={`detail-${detail.id}`}>
              <label>
                客户状态
                <select name="status" defaultValue={detail.status}>
                  {Object.entries(leadStatusLabel).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              </label>
              <label className="wideField">
                客户备注
                <textarea name="notes" defaultValue={detail.notes} placeholder="记录客户需求、背景、报价偏好等信息" />
              </label>
              <button className="primaryButton" type="submit" disabled={saving}>
                {saving ? "保存中..." : "保存客户详情"}
              </button>
            </form>

            <section className="detailBlock">
              <h3>联系人</h3>
              {detail.contacts.length === 0 ? (
                <p className="mutedCopy">暂无联系人。添加主要联系人后，后续邮件和跟进可以绑定到具体的人。</p>
              ) : (
                <ul className="contactList">
                  {detail.contacts.map((contact: ContactRecord) => (
                    <li key={contact.id}>
                      <div>
                        <strong>{contact.name}</strong>
                        {contact.is_primary && <span className="primaryBadge">主要联系人</span>}
                      </div>
                      <p>{contact.title || "未填写职位"}</p>
                      <small>{contact.email || "未填写邮箱"} / {contact.phone || "未填写电话"}</small>
                      {(contact.linkedin_url || contact.whatsapp) && (
                        <small>{contact.linkedin_url || "未填写 LinkedIn"} / {contact.whatsapp || "未填写 WhatsApp"}</small>
                      )}
                      <button
                        className="textButton"
                        type="button"
                        disabled={!contact.email || generatingDraftContactId === contact.id}
                        onClick={() => onCreateEmailDraft(contact.id)}
                      >
                        {generatingDraftContactId === contact.id ? "生成中..." : "生成开发信草稿"}
                      </button>
                      <button
                        className="dangerTextButton"
                        type="button"
                        disabled={deletingContactId === contact.id}
                        onClick={() => onDeleteContact(contact.id)}
                      >
                        {deletingContactId === contact.id ? "删除中..." : "删除联系人"}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <form className="contactForm" onSubmit={onAddContact} key={`contact-${detail.id}-${detail.contacts.length}`}>
              <h3>新增联系人</h3>
              <label>
                姓名
                <input name="name" required placeholder="例如：Anna Weber" />
              </label>
              <label>
                职位
                <input name="title" placeholder="采购经理 / Founder / Sales Director" />
              </label>
              <label>
                邮箱
                <input name="email" type="email" placeholder="anna@example.com" />
              </label>
              <label>
                电话
                <input name="phone" placeholder="+49 ..." />
              </label>
              <label>
                LinkedIn
                <input name="linkedin_url" placeholder="https://linkedin.com/in/..." />
              </label>
              <label>
                WhatsApp
                <input name="whatsapp" placeholder="+49 ..." />
              </label>
              <label className="checkboxField">
                <input name="is_primary" type="checkbox" />
                设为主要联系人
              </label>
              <button className="primaryButton" type="submit" disabled={addingContact}>
                {addingContact ? "添加中..." : "添加联系人"}
              </button>
            </form>

            <section className="detailBlock">
              <h3>来源证据</h3>
              {detail.evidence.length === 0 ? (
                <p className="mutedCopy">暂无证据。</p>
              ) : (
                <ul className="evidenceList">
                  {detail.evidence.map((item) => (
                    <li key={`${item.signal_name}-${item.source_url}`}>
                      <strong>{item.signal_name}</strong>
                      <span>{item.source_excerpt}</span>
                      <small>{item.source_url}</small>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <form className="followUpForm" onSubmit={onAddFollowUp}>
              <h3>新增跟进记录</h3>
              <label>
                跟进类型
                <select name="activity_type" defaultValue="note">
                  <option value="note">备注</option>
                  <option value="reply">客户回复</option>
                  <option value="email">邮件</option>
                  <option value="call">电话</option>
                  <option value="meeting">会议</option>
                  <option value="quote">报价</option>
                </select>
              </label>
              <label>
                下次跟进时间
                <input name="next_follow_up_at" type="datetime-local" />
              </label>
              <label className="wideField">
                跟进内容
                <textarea name="content" required placeholder="例如：已发送目录，客户要求下周提供 FOB 报价。" />
              </label>
              <button className="primaryButton" type="submit" disabled={addingFollowUp}>
                {addingFollowUp ? "添加中..." : "添加跟进记录"}
              </button>
            </form>

            <section className="detailBlock">
              <h3>跟进记录</h3>
              {detail.follow_ups.length === 0 ? (
                <p className="mutedCopy">暂无跟进记录。</p>
              ) : (
                <ol className="followUpList">
                  {detail.follow_ups.map((record: FollowUpRecord) => (
                    <li key={record.id}>
                      <div>
                        <strong>{record.activity_type}</strong>
                        <time>{formatDateTime(record.created_at)}</time>
                      </div>
                      <p>{record.content}</p>
                      <small>下次跟进：{formatDateTime(record.next_follow_up_at)}</small>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </div>
        )}
      </aside>
    </div>
  );
}

export default function HomePage() {
  const [activeNav, setActiveNav] = useState("总览");
  const [session, setSession] = useState<Session | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [loadingProductLines, setLoadingProductLines] = useState(false);
  const [creatingProductLine, setCreatingProductLine] = useState(false);
  const [productLines, setProductLines] = useState<ProductLine[]>([]);
  const [selectedProductLineId, setSelectedProductLineId] = useState("");
  const [targetMarket, setTargetMarket] = useState("德国");
  const [buyerProfile, setBuyerProfile] = useState("");
  const [leads, setLeads] = useState<Lead[]>([]);
  const [running, setRunning] = useState(false);
  const [selectedLeadIds, setSelectedLeadIds] = useState<string[]>([]);
  const [savingToCrm, setSavingToCrm] = useState(false);
  const [creatingManualLead, setCreatingManualLead] = useState(false);
  const [deletingLeadId, setDeletingLeadId] = useState("");
  const [selectedLeadId, setSelectedLeadId] = useState("");
  const [leadDetail, setLeadDetail] = useState<LeadDetail | null>(null);
  const [loadingLeadDetail, setLoadingLeadDetail] = useState(false);
  const [savingLeadDetail, setSavingLeadDetail] = useState(false);
  const [addingContact, setAddingContact] = useState(false);
  const [deletingContactId, setDeletingContactId] = useState("");
  const [generatingDraftContactId, setGeneratingDraftContactId] = useState("");
  const [addingFollowUp, setAddingFollowUp] = useState(false);
  const [followUps, setFollowUps] = useState<FollowUpRecord[]>([]);
  const [loadingFollowUps, setLoadingFollowUps] = useState(false);
  const [emailDrafts, setEmailDrafts] = useState<EmailDraft[]>([]);
  const [loadingEmailDrafts, setLoadingEmailDrafts] = useState(false);
  const [websiteInquiries, setWebsiteInquiries] = useState<WebsiteInquiry[]>([]);
  const [loadingWebsiteInquiries, setLoadingWebsiteInquiries] = useState(false);
  const [inquiryStatusFilter, setInquiryStatusFilter] = useState<WebsiteInquiryStatus | "all">("new");
  const [convertingInquiryId, setConvertingInquiryId] = useState("");
  const [selectedDraftId, setSelectedDraftId] = useState("");
  const [savingEmailDraft, setSavingEmailDraft] = useState(false);
  const [reviewingEmailDraft, setReviewingEmailDraft] = useState(false);
  const [runMessage, setRunMessage] = useState("请创建或选择产品线后开始搜索");
  const [priorityOnly, setPriorityOnly] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [error, setError] = useState("");

  const selectedProductLine = useMemo(
    () => productLines.find((productLine) => productLine.id === selectedProductLineId),
    [productLines, selectedProductLineId]
  );
  const selectedEmailDraft = useMemo(
    () => emailDrafts.find((draft) => draft.id === selectedDraftId) ?? emailDrafts[0] ?? null,
    [emailDrafts, selectedDraftId]
  );
  const dashboardMetrics = useMemo(
    () => buildMetrics(leads, emailDrafts, followUps),
    [leads, emailDrafts, followUps]
  );

  useEffect(() => {
    const currentSession = readSession();
    if (!currentSession) {
      window.location.assign("/login");
      return;
    }
    setSession(currentSession);
    setCheckingSession(false);
    setLoadingProductLines(true);
    listProductLines(currentSession)
      .then((items) => {
        setProductLines(items);
        if (items.length > 0) {
          setSelectedProductLineId(items[0].id);
          setBuyerProfile(items[0].buyer_profiles[0] ?? "");
          setRunMessage("已准备好进行定向客户搜索");
        }
      })
      .catch((caught: unknown) => handleApiFailure(caught, "无法加载产品线"))
      .finally(() => setLoadingProductLines(false));
    listLeads(currentSession)
      .then((items) => setLeads(items))
      .catch((caught: unknown) => handleApiFailure(caught, "无法加载客户列表"));
    setLoadingFollowUps(true);
    listFollowUps(currentSession)
      .then((items) => setFollowUps(items))
      .catch((caught: unknown) => handleApiFailure(caught, "无法加载跟进记录"))
      .finally(() => setLoadingFollowUps(false));
    setLoadingEmailDrafts(true);
    listEmailDrafts(currentSession)
      .then((items) => {
        setEmailDrafts(items);
        if (items.length > 0) setSelectedDraftId(items[0].id);
      })
      .catch((caught: unknown) => handleApiFailure(caught, "无法加载邮件审批队列"))
      .finally(() => setLoadingEmailDrafts(false));
    setLoadingWebsiteInquiries(true);
    listWebsiteInquiries(currentSession, "new")
      .then((items) => setWebsiteInquiries(items))
      .catch((caught: unknown) => handleApiFailure(caught, "无法加载独立站询盘"))
      .finally(() => setLoadingWebsiteInquiries(false));
  }, []);

  function handleApiFailure(caught: unknown, fallback: string) {
    if (caught instanceof ApiError && caught.status === 401) {
      clearSession();
      window.location.assign("/login");
      return;
    }
    setError(caught instanceof Error ? caught.message : fallback);
  }

  async function refreshEmailDrafts(nextSelectedDraftId?: string) {
    if (!session) return;
    const items = await listEmailDrafts(session);
    setEmailDrafts(items);
    if (nextSelectedDraftId) {
      setSelectedDraftId(nextSelectedDraftId);
    } else if (selectedDraftId && !items.some((draft) => draft.id === selectedDraftId)) {
      setSelectedDraftId(items[0]?.id ?? "");
    } else if (!selectedDraftId && items.length > 0) {
      setSelectedDraftId(items[0].id);
    }
  }

  function openEmailDraftQueue(draftId?: string) {
    if (draftId) setSelectedDraftId(draftId);
    setReviewOpen(true);
  }

  async function refreshFollowUps() {
    if (!session) return;
    setLoadingFollowUps(true);
    try {
      const items = await listFollowUps(session);
      setFollowUps(items);
    } catch (caught) {
      handleApiFailure(caught, "无法刷新跟进记录");
    } finally {
      setLoadingFollowUps(false);
    }
  }

  async function refreshWebsiteInquiries(nextStatusFilter = inquiryStatusFilter) {
    if (!session) return;
    setLoadingWebsiteInquiries(true);
    try {
      const items = await listWebsiteInquiries(session, nextStatusFilter);
      setWebsiteInquiries(items);
    } catch (caught) {
      handleApiFailure(caught, "无法刷新独立站询盘");
    } finally {
      setLoadingWebsiteInquiries(false);
    }
  }

  function changeInquiryStatusFilter(statusFilter: WebsiteInquiryStatus | "all") {
    setInquiryStatusFilter(statusFilter);
    void refreshWebsiteInquiries(statusFilter);
  }

  async function convertInquiryToCustomer(inquiryId: string) {
    if (!session) return;
    setConvertingInquiryId(inquiryId);
    setError("");
    try {
      const converted = await convertWebsiteInquiry(session, inquiryId);
      setWebsiteInquiries((current) =>
        current.map((inquiry) => (inquiry.id === converted.inquiry.id ? converted.inquiry : inquiry))
      );
      setLeads((current) => [converted.lead, ...current.filter((lead) => lead.id !== converted.lead.id)]);
      setSelectedLeadId(converted.lead.id);
      setLeadDetail(converted.lead);
      await refreshWebsiteInquiries();
      await refreshFollowUps();
    } catch (caught) {
      handleApiFailure(caught, "无法把询盘转为 CRM 客户");
    } finally {
      setConvertingInquiryId("");
    }
  }

  function logout() {
    clearSession();
    window.location.assign("/login");
  }

  function exportActivityCsv() {
    const csv = buildActivityCsv(leads, emailDrafts, followUps);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `trade-axis-activity-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function selectProductLine(productLineId: string) {
    setSelectedProductLineId(productLineId);
    const productLine = productLines.find((item) => item.id === productLineId);
    setBuyerProfile(productLine?.buyer_profiles[0] ?? "");
  }

  async function createProductLineFromForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    setCreatingProductLine(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      const created = await createProductLine(session, {
        name: String(form.get("name") ?? "").trim(),
        description: String(form.get("description") ?? "").trim(),
        product_keywords: parseCsv(form.get("keywords")),
        buyer_profiles: parseCsv(form.get("buyer_profiles")),
        target_regions: parseCsv(form.get("target_regions")),
      });
      setProductLines((current) => [...current, created]);
      setSelectedProductLineId(created.id);
      setBuyerProfile(created.buyer_profiles[0] ?? "");
      setRunMessage("已准备好进行定向客户搜索");
      event.currentTarget.reset();
    } catch (caught) {
      handleApiFailure(caught, "无法创建产品线");
    } finally {
      setCreatingProductLine(false);
    }
  }

  async function runDiscovery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !selectedProductLineId) return;
    setRunning(true);
    setError("");
    setRunMessage("客户搜索运行中");
    try {
      const run = await startDiscovery(session, {
        product_line_id: selectedProductLineId,
        target_market: targetMarket.trim(),
        buyer_profile: buyerProfile || undefined,
        limit: 20,
      });
      const nextLeads = await listLeads(session);
      setLeads(nextLeads);
      setSelectedLeadIds([]);
      setRunMessage(`搜索完成 / 已筛选 ${run.lead_count} 家公司 / ${run.query}`);
    } catch (caught) {
      handleApiFailure(caught, "客户搜索失败");
      setRunMessage("客户搜索失败");
    } finally {
      setRunning(false);
    }
  }

  async function createManualLeadFromForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    const form = new FormData(event.currentTarget);
    setCreatingManualLead(true);
    setError("");
    try {
      const created = await createManualLead(session, {
        product_line_id: String(form.get("product_line_id") ?? ""),
        company_name: String(form.get("company_name") ?? "").trim(),
        website: String(form.get("website") ?? "").trim(),
        target_market: String(form.get("target_market") ?? "").trim(),
        buyer_profile: String(form.get("buyer_profile") ?? "").trim() || undefined,
        notes: String(form.get("notes") ?? "").trim(),
      });
      setLeads((current) => [created, ...current.filter((lead) => lead.id !== created.id)]);
      setSelectedLeadIds((current) => current.filter((leadId) => leadId !== created.id));
      event.currentTarget.reset();
    } catch (caught) {
      handleApiFailure(caught, "无法添加客户");
    } finally {
      setCreatingManualLead(false);
    }
  }

  async function deleteCustomerLead(leadId: string) {
    if (!session) return;
    setDeletingLeadId(leadId);
    setError("");
    try {
      await deleteLead(session, leadId);
      setLeads((current) => current.filter((lead) => lead.id !== leadId));
      setSelectedLeadIds((current) => current.filter((selectedId) => selectedId !== leadId));
      setEmailDrafts((current) => current.filter((draft) => draft.lead_id !== leadId));
      if (selectedLeadId === leadId) {
        setSelectedLeadId("");
        setLeadDetail(null);
      }
    } catch (caught) {
      handleApiFailure(caught, "无法删除客户");
    } finally {
      setDeletingLeadId("");
    }
  }

  function selectLeadForCrm(leadId: string, selected: boolean) {
    setSelectedLeadIds((current) => {
      if (selected) return current.includes(leadId) ? current : [...current, leadId];
      return current.filter((selectedId) => selectedId !== leadId);
    });
  }

  function selectAllVisibleLeadsForCrm(leadIds: string[], selected: boolean) {
    setSelectedLeadIds((current) => {
      if (!selected) return current.filter((leadId) => !leadIds.includes(leadId));
      return Array.from(new Set([...current, ...leadIds]));
    });
  }

  async function saveSelectedLeadsToCrm() {
    if (!session || selectedLeadIds.length === 0) return;
    const leadsToSave = leads.filter((lead) => selectedLeadIds.includes(lead.id) && !isCrmLead(lead));
    if (leadsToSave.length === 0) return;
    setSavingToCrm(true);
    setError("");
    try {
      const updatedLeads = await Promise.all(
        leadsToSave.map((lead) =>
          updateLeadDetail(session, lead.id, {
            status: "to_contact",
            notes: lead.notes,
            owner_user_id: lead.owner_user_id,
          })
        )
      );
      const updatedById = new Map(updatedLeads.map((lead) => [lead.id, lead]));
      setLeads((current) => current.map((lead) => updatedById.get(lead.id) ?? lead));
      setSelectedLeadIds((current) => current.filter((leadId) => !updatedById.has(leadId)));
      setRunMessage(`已保存 ${updatedLeads.length} 个客户到 CRM，状态为待联系`);
      if (leadDetail && updatedById.has(leadDetail.id)) {
        const refreshed = await getLeadDetail(session, leadDetail.id);
        setLeadDetail(refreshed);
      }
    } catch (caught) {
      handleApiFailure(caught, "无法保存到 CRM");
    } finally {
      setSavingToCrm(false);
    }
  }

  async function openLeadDetail(leadId: string) {
    if (!session) return;
    setSelectedLeadId(leadId);
    setLoadingLeadDetail(true);
    setError("");
    try {
      const detail = await getLeadDetail(session, leadId);
      setLeadDetail(detail);
    } catch (caught) {
      handleApiFailure(caught, "无法加载客户详情");
      setSelectedLeadId("");
      setLeadDetail(null);
    } finally {
      setLoadingLeadDetail(false);
    }
  }

  function closeLeadDetail() {
    setSelectedLeadId("");
    setLeadDetail(null);
  }

  async function saveLeadDetail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !leadDetail) return;
    const form = new FormData(event.currentTarget);
    setSavingLeadDetail(true);
    setError("");
    try {
      const updated = await updateLeadDetail(session, leadDetail.id, {
        status: String(form.get("status") ?? "new") as LeadStatus,
        notes: String(form.get("notes") ?? ""),
        owner_user_id: null,
      });
      setLeads((current) => current.map((lead) => (lead.id === updated.id ? updated : lead)));
      const refreshed = await getLeadDetail(session, leadDetail.id);
      setLeadDetail(refreshed);
    } catch (caught) {
      handleApiFailure(caught, "无法保存客户详情");
    } finally {
      setSavingLeadDetail(false);
    }
  }

  async function addContactRecord(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !leadDetail) return;
    const form = new FormData(event.currentTarget);
    setAddingContact(true);
    setError("");
    try {
      await createContact(session, leadDetail.id, {
        name: String(form.get("name") ?? "").trim(),
        title: String(form.get("title") ?? "").trim(),
        email: String(form.get("email") ?? "").trim(),
        phone: String(form.get("phone") ?? "").trim(),
        linkedin_url: String(form.get("linkedin_url") ?? "").trim(),
        whatsapp: String(form.get("whatsapp") ?? "").trim(),
        is_primary: form.get("is_primary") === "on",
      });
      const refreshed = await getLeadDetail(session, leadDetail.id);
      setLeadDetail(refreshed);
      await refreshFollowUps();
      event.currentTarget.reset();
    } catch (caught) {
      handleApiFailure(caught, "无法添加联系人");
    } finally {
      setAddingContact(false);
    }
  }

  async function deleteContactRecord(contactId: string) {
    if (!session || !leadDetail) return;
    setDeletingContactId(contactId);
    setError("");
    try {
      await deleteContact(session, leadDetail.id, contactId);
      const refreshed = await getLeadDetail(session, leadDetail.id);
      setLeadDetail(refreshed);
      setEmailDrafts((current) => current.filter((draft) => draft.contact_id !== contactId));
    } catch (caught) {
      handleApiFailure(caught, "无法删除联系人");
    } finally {
      setDeletingContactId("");
    }
  }

  async function createEmailDraftForContact(contactId: string) {
    if (!session || !leadDetail) return;
    setGeneratingDraftContactId(contactId);
    setError("");
    try {
      const draft = await createEmailDraft(session, leadDetail.id, contactId);
      await refreshEmailDrafts(draft.id);
      setReviewOpen(true);
    } catch (caught) {
      handleApiFailure(caught, "无法生成开发信草稿");
    } finally {
      setGeneratingDraftContactId("");
    }
  }

  async function addFollowUpRecord(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !leadDetail) return;
    const form = new FormData(event.currentTarget);
    const nextFollowUp = String(form.get("next_follow_up_at") ?? "");
    setAddingFollowUp(true);
    setError("");
    try {
      await createFollowUp(session, leadDetail.id, {
        activity_type: String(form.get("activity_type") ?? "note"),
        content: String(form.get("content") ?? "").trim(),
        next_follow_up_at: nextFollowUp ? new Date(nextFollowUp).toISOString() : null,
      });
      const refreshed = await getLeadDetail(session, leadDetail.id);
      setLeadDetail(refreshed);
      setLeads((current) => current.map((lead) => (lead.id === refreshed.id ? refreshed : lead)));
      await refreshFollowUps();
      event.currentTarget.reset();
    } catch (caught) {
      handleApiFailure(caught, "无法添加跟进记录");
    } finally {
      setAddingFollowUp(false);
    }
  }

  async function saveEmailDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !selectedEmailDraft) return;
    const form = new FormData(event.currentTarget);
    setSavingEmailDraft(true);
    setError("");
    try {
      const updated = await updateEmailDraft(session, selectedEmailDraft.id, {
        subject: String(form.get("subject") ?? "").trim(),
        body: String(form.get("body") ?? "").trim(),
      });
      setEmailDrafts((current) => current.map((draft) => (draft.id === updated.id ? updated : draft)));
      setSelectedDraftId(updated.id);
    } catch (caught) {
      handleApiFailure(caught, "无法保存开发信草稿");
    } finally {
      setSavingEmailDraft(false);
    }
  }

  async function approveEmailDraft() {
    if (!session || !selectedEmailDraft) return;
    setReviewingEmailDraft(true);
    setError("");
    try {
      const updated = await reviewEmailDraft(session, selectedEmailDraft.id, { action: "approve" });
      setEmailDrafts((current) => current.map((draft) => (draft.id === updated.id ? updated : draft)));
      setSelectedDraftId(updated.id);
    } catch (caught) {
      handleApiFailure(caught, "无法批准开发信草稿");
    } finally {
      setReviewingEmailDraft(false);
    }
  }

  async function markSelectedEmailDraftSent() {
    if (!session || !selectedEmailDraft) return;
    setReviewingEmailDraft(true);
    setError("");
    try {
      const updated = await markEmailDraftSent(session, selectedEmailDraft.id);
      setEmailDrafts((current) => current.map((draft) => (draft.id === updated.id ? updated : draft)));
      setLeads((current) =>
        current.map((lead) =>
          lead.id === updated.lead_id ? { ...lead, status: "contacted" } : lead
        )
      );
      setSelectedDraftId(updated.id);
      if (leadDetail?.id === updated.lead_id) {
        const refreshed = await getLeadDetail(session, updated.lead_id);
        setLeadDetail(refreshed);
      }
      await refreshFollowUps();
    } catch (caught) {
      handleApiFailure(caught, "无法标记开发信已发送");
    } finally {
      setReviewingEmailDraft(false);
    }
  }

  async function rejectEmailDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !selectedEmailDraft) return;
    const form = new FormData(event.currentTarget);
    setReviewingEmailDraft(true);
    setError("");
    try {
      const updated = await reviewEmailDraft(session, selectedEmailDraft.id, {
        action: "reject",
        rejection_reason: String(form.get("rejection_reason") ?? "").trim(),
      });
      setEmailDrafts((current) => current.map((draft) => (draft.id === updated.id ? updated : draft)));
      setSelectedDraftId(updated.id);
    } catch (caught) {
      handleApiFailure(caught, "无法驳回开发信草稿");
    } finally {
      setReviewingEmailDraft(false);
    }
  }

  if (checkingSession || !session) {
    return (
      <main className="authCheck">
        <span className="statusDot" aria-hidden="true" />
        正在加载工作台...
      </main>
    );
  }

  return (
    <main className="appShell">
      <aside className="sidebar">
        <a className="brand" href="#top" aria-label="Trade Axis 首页"><span>TA</span><strong>TRADE<br />AXIS</strong></a>
        <nav aria-label="主导航">
          {navItems.map((item) => (
            <button className={activeNav === item ? "navItem active" : "navItem"} key={item} type="button" onClick={() => setActiveNav(item)}>
              <span className="navMarker" aria-hidden="true" />{item}
            </button>
          ))}
        </nav>
        <div className="sidebarFooter"><span className="connectionDot" />系统运行中<span className="tenant">{session.organization_role ?? "成员"}</span></div>
      </aside>
      <section className="workspace" id="top">
        <header className="topbar">
          <div className="crumbs"><span>销售工作台</span><strong>{activeNav}</strong></div>
          <div className="topbarActions"><button className="utilityButton" type="button">中文</button><button className="utilityButton logoutButton" type="button" onClick={logout}>退出登录</button><button className="profileButton" type="button" aria-label="打开 Mia Chen 资料">MC</button></div>
        </header>
        <div className="content">
          <section className="pageHeading">
            <div><p className="sectionLabel">客户开发</p><h1>外贸客户开发工作台</h1><p>配置产品线，启动基于公开证据的客户搜索，并把合格线索推进到 CRM 和开发信流程。</p></div>
            <button className="outlineButton exportButton" type="button" onClick={exportActivityCsv}>
              导出活动
            </button>
          </section>
          {error && <div className="errorBanner" role="alert">{error}</div>}
          <section className="metricGrid" aria-label="销售指标">{dashboardMetrics.map((metric) => <MetricTile key={metric.label} {...metric} />)}</section>
          <ProductLineSetup productLines={productLines} loading={loadingProductLines} creating={creatingProductLine} onCreate={createProductLineFromForm} />
          <CustomerAgent
            productLines={productLines}
            selectedProductLineId={selectedProductLineId}
            targetMarket={targetMarket}
            buyerProfile={buyerProfile}
            running={running}
            runMessage={selectedProductLine ? runMessage : "请先创建第一个产品线，再开始搜索"}
            onProductLineChange={selectProductLine}
            onTargetMarketChange={setTargetMarket}
            onBuyerProfileChange={setBuyerProfile}
            onRun={runDiscovery}
          />
          <CRMCustomerManager
            leads={leads}
            productLines={productLines}
            selectedProductLineId={selectedProductLineId}
            creating={creatingManualLead}
            deletingLeadId={deletingLeadId}
            onCreate={createManualLeadFromForm}
            onDelete={deleteCustomerLead}
            onOpenDetail={openLeadDetail}
          />
          <WebsiteInquiryPanel
            inquiries={websiteInquiries}
            productLines={productLines}
            organizationId={session.organization_id}
            loading={loadingWebsiteInquiries}
            convertingInquiryId={convertingInquiryId}
            statusFilter={inquiryStatusFilter}
            onStatusFilterChange={changeInquiryStatusFilter}
            onRefresh={() => void refreshWebsiteInquiries()}
            onConvert={convertInquiryToCustomer}
          />
          <div className="secondaryGrid">
            <ReviewQueue
              drafts={emailDrafts}
              loading={loadingEmailDrafts}
              onOpen={() => openEmailDraftQueue()}
              onOpenDraft={openEmailDraftQueue}
            />
            <InboxPanel
              records={followUps}
              loading={loadingFollowUps}
              onRefresh={refreshFollowUps}
            />
            <FollowUpTimeline
              records={followUps}
              loading={loadingFollowUps}
              onRefresh={refreshFollowUps}
            />
          </div>
          <LeadTable
            leads={leads}
            priorityOnly={priorityOnly}
            selectedLeadIds={selectedLeadIds}
            savingToCrm={savingToCrm}
            onPriorityToggle={() => setPriorityOnly((current) => !current)}
            onSelectLead={selectLeadForCrm}
            onSelectAllVisible={selectAllVisibleLeadsForCrm}
            onSaveToCrm={saveSelectedLeadsToCrm}
            onOpenDetail={openLeadDetail}
          />
        </div>
      </section>
      <CustomerDetailDrawer
        detail={leadDetail}
        loading={loadingLeadDetail}
        saving={savingLeadDetail}
        addingContact={addingContact}
        addingFollowUp={addingFollowUp}
        deletingContactId={deletingContactId}
        generatingDraftContactId={generatingDraftContactId}
        onClose={closeLeadDetail}
        onSave={saveLeadDetail}
        onAddContact={addContactRecord}
        onDeleteContact={deleteContactRecord}
        onCreateEmailDraft={createEmailDraftForContact}
        onAddFollowUp={addFollowUpRecord}
      />
      <ReviewDrawer
        open={reviewOpen}
        draft={selectedEmailDraft}
        saving={savingEmailDraft}
        reviewing={reviewingEmailDraft}
        onClose={() => setReviewOpen(false)}
        onSave={saveEmailDraft}
        onApprove={approveEmailDraft}
        onMarkSent={markSelectedEmailDraftSent}
        onReject={rejectEmailDraft}
      />
    </main>
  );
}
