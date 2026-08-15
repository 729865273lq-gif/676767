"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  completeFollowUpTask,
  convertWebsiteInquiry,
  createContact,
  createEmailDraft,
  createFollowUp,
  createFollowUpTask,
  createProductItem,
  createProductLine,
  createManualLead,
  createQuoteDraft,
  deleteContact,
  deleteLead,
  deleteProductLine,
  deleteProductItem,
  discoverContacts,
  discoverContactBatch,
  getLeadDetail,
  getCustomerDevelopmentConnectors,
  getEmailDeliveryStatus,
  getPublicProductCatalogUrl,
  listEmailDrafts,
  listFollowUpTasks,
  listFollowUps,
  listKnowledgeDocuments,
  listLeads,
  listProductLines,
  listSearchSources,
  listWebsiteInquiries,
  markEmailDraftSent,
  markQuoteDraftSent,
  reviewEmailDraft,
  resolveAdministrativeLocation,
  startDiscovery,
  updateEmailDraft,
  updateDraftContactEmail,
  updateLeadDetail,
  updateQuoteDraft,
  updateSearchSource,
  uploadKnowledgeDocument,
  verifyContactEmail,
  type ContactRecord,
  type BatchContactDiscoveryItem,
  type AdministrativeArea,
  type ConnectorStatus,
  type DiscoveryRun,
  type EmailDeliveryStatus,
  type EmailDraft,
  type KnowledgeDocument,
  type KnowledgeDocumentStatus,
  type FollowUpRecord,
  type FollowUpTask,
  type FollowUpTaskStatus,
  type Lead,
  type LeadDetail,
  type LeadStatus,
  type ProductItem,
  type ProductLine,
  type QuoteDraft,
  type SearchSource,
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

type FunnelStage = {
  status: LeadStatus;
  label: string;
  count: number;
  share: number;
  note: string;
};

type ActionSignal = {
  label: string;
  count: number;
  note: string;
};

const API_STATUS_NAV = "API 接口状态";
const KNOWLEDGE_NAV = "知识库";
const navItems = ["总览", "客户搜索 Agent", "CRM", "独立站询盘", API_STATUS_NAV, "邮件审核", "收件箱", KNOWLEDGE_NAV];

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

const sendRiskLabel: Record<EmailDraft["send_risk_level"], string> = {
  safe: "可发送",
  caution: "谨慎发送",
  warning: "建议验证",
  blocked: "禁止发送",
};

const blockedContactEmailStatuses = new Set(["invalid", "spamtrap", "abuse", "do_not_mail"]);
const batchEligibleContactEmailStatuses = new Set(["valid", "catch_all", "accept_all", "unknown"]);

type CustomerBatchResultItem = {
  leadId: string;
  companyName: string;
  status: "success" | "warning" | "error";
  message: string;
};

function whatsappLink(value: string): string {
  if (/^https?:\/\//i.test(value)) return value;
  return `https://wa.me/${value.replace(/\D/g, "")}`;
}

const websiteInquiryStatusLabel: Record<WebsiteInquiryStatus, string> = {
  new: "新询盘",
  converted: "已转客户",
  dismissed: "已忽略",
};

const followUpTaskStatusLabel: Record<FollowUpTaskStatus, string> = {
  open: "待完成",
  done: "已完成",
};

const quoteDraftStatusLabel: Record<QuoteDraft["status"], string> = {
  draft: "草稿",
  sent: "已发送报价",
};

const quoteStatusLabel: Record<string, string> = {
  requested: "客户要报价",
  preparing_quote: "准备报价",
  quote_sent: "已发报价",
  negotiating: "谈判中",
  won: "已成交",
  lost: "未成交",
};

function taskTypeLabel(taskType: string) {
  if (taskType === "quote") return "报价任务";
  if (taskType === "sample") return "样品任务";
  if (taskType === "call") return "电话任务";
  if (taskType === "meeting") return "会议任务";
  return "跟进任务";
}

function quoteDraftPayloadFromForm(form: FormData) {
  const validUntil = String(form.get("valid_until") ?? "");
  return {
    title: String(form.get("title") ?? "").trim(),
    currency: String(form.get("currency") ?? "USD").trim() || "USD",
    incoterm: String(form.get("incoterm") ?? "FOB").trim() || "FOB",
    valid_until: validUntil ? new Date(`${validUntil}T00:00:00Z`).toISOString() : null,
    line_items: [
      {
        item_name: String(form.get("item_name") ?? "").trim(),
        quantity: Number(form.get("quantity") ?? 0),
        unit_price: Number(form.get("unit_price") ?? 0),
        unit: String(form.get("unit") ?? "pcs").trim() || "pcs",
        notes: String(form.get("line_notes") ?? "").trim(),
      },
    ],
    notes: String(form.get("notes") ?? "").trim(),
  };
}

function isCrmLead(lead: Lead) {
  return lead.status !== "new";
}

const contactDiscoveryLabel: Record<Lead["contact_discovery_status"], string> = {
  not_scanned: "未提取",
  has_email: "有邮箱",
  has_contact: "有人工联系方式",
  no_contacts: "未发现",
  needs_review: "待复查",
};

function sortLeadsNewestFirst(items: Lead[]) {
  return [...items].sort((left, right) => {
    const discoveryDifference =
      Date.parse(right.last_discovered_at) - Date.parse(left.last_discovered_at);
    if (Number.isFinite(discoveryDifference) && discoveryDifference !== 0) {
      return discoveryDifference;
    }
    const creationDifference = Date.parse(right.created_at) - Date.parse(left.created_at);
    if (Number.isFinite(creationDifference) && creationDifference !== 0) {
      return creationDifference;
    }
    return 0;
  });
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

function SalesFunnelPanel({
  stages,
  actionSignals,
  totalLeads,
  disqualified,
}: {
  stages: FunnelStage[];
  actionSignals: ActionSignal[];
  totalLeads: number;
  disqualified: number;
}) {
  const activeActions = actionSignals.reduce((sum, signal) => sum + signal.count, 0);
  return (
    <section className="funnelPanel" aria-labelledby="sales-funnel-title">
      <div className="sectionHeader compact">
        <div>
          <p className="sectionLabel">销售漏斗</p>
          <h2 id="sales-funnel-title">客户阶段总览</h2>
        </div>
        <span className="countBadge">{totalLeads} 个客户 / {activeActions} 个动作</span>
      </div>
      <div className="funnelContent">
        <div className="funnelStages" aria-label="客户阶段漏斗">
          {stages.map((stage) => (
            <article className="funnelStage" key={stage.status}>
              <div>
                <strong>{stage.label}</strong>
                <span>{stage.note}</span>
              </div>
              <div className="funnelMeter" aria-label={`${stage.label} ${stage.count} 个客户`}>
                <span style={{ width: `${Math.max(stage.share, stage.count > 0 ? 8 : 0)}%` }} />
              </div>
              <small>{stage.count} 个 / {stage.share}%</small>
            </article>
          ))}
        </div>
        <div className="actionSignals" aria-label="待处理动作">
          <div className="actionSignalHeader">
            <strong>待处理动作</strong>
            <span>暂不自动外联，只提示人工处理</span>
          </div>
          {actionSignals.map((signal) => (
            <article className="actionSignal" key={signal.label}>
              <strong>{signal.count}</strong>
              <div>
                <span>{signal.label}</span>
                <small>{signal.note}</small>
              </div>
            </article>
          ))}
          <div className="funnelFooter">
            <span>暂不合适</span>
            <strong>{disqualified} 个客户</strong>
          </div>
        </div>
      </div>
    </section>
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

function buildSalesFunnel(
  leads: Lead[],
  drafts: EmailDraft[],
  tasks: FollowUpTask[],
  inquiries: WebsiteInquiry[]
) {
  const stageOrder: LeadStatus[] = ["new", "to_contact", "contacted", "interested", "quoting", "won"];
  const totalLeads = leads.length;
  const stages: FunnelStage[] = stageOrder.map((status) => {
    const count = leads.filter((lead) => lead.status === status).length;
    const share = totalLeads > 0 ? Math.round((count / totalLeads) * 100) : 0;
    return {
      status,
      label: leadStatusLabel[status],
      count,
      share,
      note: status === "new" ? "待筛选" : status === "won" ? "已成交" : "推进中",
    };
  });
  const disqualified = leads.filter((lead) => lead.status === "not_fit").length;
  const actionSignals: ActionSignal[] = [
    {
      label: "新询盘",
      count: inquiries.filter((inquiry) => inquiry.status === "new").length,
      note: "独立站接口进来的未转客户询盘",
    },
    {
      label: "待联系",
      count: leads.filter((lead) => lead.status === "to_contact").length,
      note: "已进入 CRM 但还没完成首次联系",
    },
    {
      label: "待审核邮件",
      count: drafts.filter((draft) => draft.status === "pending_approval").length,
      note: "人工审核后才允许标记待发送",
    },
    {
      label: "待办任务",
      count: tasks.filter((task) => task.status === "open").length,
      note: "报价、样品、电话和会议任务",
    },
  ];
  return { stages, actionSignals, totalLeads, disqualified };
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

function buildInquiryFormUrl(
  formBaseUrl: string,
  organizationId: string,
  productLine: ProductLine,
  productItem?: ProductItem
) {
  const params = new URLSearchParams({
    organization_id: organizationId,
    product_line_id: productLine.id,
    product: productItem?.name ?? productLine.name,
  });
  if (productItem) params.set("product_item_id", productItem.id);
  return `${formBaseUrl}?${params.toString()}`;
}

function ProductLineSetup({
  productLines,
  loading,
  creating,
  deletingProductLineId,
  onCreate,
  onDelete,
}: {
  productLines: ProductLine[];
  loading: boolean;
  creating: boolean;
  deletingProductLineId: string;
  onCreate: (event: FormEvent<HTMLFormElement>) => void;
  onDelete: (productLineId: string) => void;
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
            排除关键词
            <input name="excluded_keywords" placeholder="同行品牌, manufacturer, factory, jobs" />
            <small className="fieldHint">命中公司名称、官网或搜索摘要的结果不会进入线索库</small>
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
                <div>
                  <strong>{productLine.name}</strong>
                  <span>{productLine.product_keywords.join(", ") || "暂无关键词"}</span>
                  <small>
                    {productLine.buyer_profiles.join(", ") || "暂无客户类型"} /{" "}
                    {productLine.target_regions.join(", ") || "暂无目标区域"}
                  </small>
                  <small>排除：{(productLine.excluded_keywords ?? []).join(", ") || "未配置"}</small>
                  <small>{(productLine.product_items ?? []).length} 个产品条目可用于独立站</small>
                </div>
                <button
                  className="dangerTextButton"
                  type="button"
                  aria-label={`删除产品线 ${productLine.name}`}
                  disabled={deletingProductLineId === productLine.id}
                  onClick={() => onDelete(productLine.id)}
                >
                  {deletingProductLineId === productLine.id ? "删除中..." : "删除"}
                </button>
              </article>
            ))
          )}
        </div>
      </div>
    </section>
  );
}

function ProductCatalogManager({
  productLines,
  selectedProductLineId,
  organizationId,
  creating,
  deletingProductItemId,
  onCreate,
  onDelete,
}: {
  productLines: ProductLine[];
  selectedProductLineId: string;
  organizationId: string;
  creating: boolean;
  deletingProductItemId: string;
  onCreate: (event: FormEvent<HTMLFormElement>) => void;
  onDelete: (productItemId: string) => void;
}) {
  const [formOrigin, setFormOrigin] = useState("");
  useEffect(() => {
    setFormOrigin(window.location.origin);
  }, []);
  const formBaseUrl = formOrigin ? `${formOrigin}/inquiry` : "/inquiry";
  const catalogFeedUrl = getPublicProductCatalogUrl(organizationId);
  const catalogItems = productLines.flatMap((productLine) =>
    (productLine.product_items ?? []).map((productItem) => ({ productLine, productItem }))
  );
  const publishedCount = catalogItems.filter(({ productItem }) => productItem.is_published).length;

  return (
    <section className="catalogPanel" aria-labelledby="product-catalog-title">
      <div className="sectionHeader">
        <div>
          <p className="sectionLabel">独立站内容底座</p>
          <h2 id="product-catalog-title">产品目录</h2>
        </div>
        <span className="countBadge">{catalogItems.length} 个产品</span>
      </div>
      <div className="catalogContent">
        <form className="catalogForm" onSubmit={onCreate}>
          <label>
            所属产品线
            <select
              key={selectedProductLineId || "catalog-product-line"}
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
            产品名称
            <input name="name" required maxLength={200} placeholder="LED Floodlight 200W" />
          </label>
          <label>
            SKU / 型号
            <input name="sku" maxLength={120} placeholder="FL-200W" />
          </label>
          <label>
            图片 URL
            <input name="image_url" maxLength={1000} placeholder="https://example.com/product.jpg" />
          </label>
          <label className="wideField">
            简短卖点
            <textarea name="summary" maxLength={1000} placeholder="适合仓库、厂房、码头等场景，支持 OEM 规格定制。" />
          </label>
          <label className="wideField">
            规格参数
            <input name="specs" placeholder="200W, IP66, CE, 5 years warranty" />
          </label>
          <label className="checkboxField">
            <input name="is_published" type="checkbox" defaultChecked />
            可用于独立站公开表单
          </label>
          <button className="primaryButton" type="submit" disabled={creating || productLines.length === 0}>
            {creating ? "保存中..." : "保存产品"}
          </button>
        </form>
        <div className="catalogExport">
          <div className="catalogFeed">
            <div>
              <strong>公开产品 API</strong>
              <span>{publishedCount} 个已发布产品会进入独立站数据出口</span>
              <small>{catalogFeedUrl}</small>
            </div>
            <div className="catalogActions">
              <a className="textButton" href={catalogFeedUrl} target="_blank" rel="noreferrer">打开 JSON</a>
              <button className="textButton" type="button" onClick={() => void navigator.clipboard.writeText(catalogFeedUrl)}>
                复制 API
              </button>
            </div>
          </div>
          <div className="catalogList" aria-label="产品目录列表">
            {catalogItems.length === 0 ? (
              <div className="emptyState">先维护产品条目。后续独立站页面、询盘表单和客户跟进都会引用这里的数据。</div>
            ) : (
              catalogItems.map(({ productLine, productItem }) => {
                const url = buildInquiryFormUrl(formBaseUrl, organizationId, productLine, productItem);
                return (
                  <article className="catalogItem" key={productItem.id}>
                    <div>
                      <strong>{productItem.name}</strong>
                      <span>{productLine.name} / {productItem.sku || "未填 SKU"}</span>
                      <small>{productItem.summary || "暂无卖点摘要"}</small>
                      <small>{(productItem.specs ?? []).join(", ") || "暂无规格参数"}</small>
                      <small>{url}</small>
                      <small>{productItem.is_published ? "公开表单可用" : "仅后台留存"}</small>
                    </div>
                    <div className="catalogActions">
                      <a className="textButton" href={url} target="_blank" rel="noreferrer">打开询盘表单</a>
                      <button className="textButton" type="button" onClick={() => void navigator.clipboard.writeText(url)}>
                        复制链接
                      </button>
                      <button
                        className="dangerTextButton"
                        type="button"
                        disabled={deletingProductItemId === productItem.id}
                        onClick={() => onDelete(productItem.id)}
                      >
                        {deletingProductItemId === productItem.id ? "删除中..." : "删除"}
                      </button>
                    </div>
                  </article>
                );
              })
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function leadSourceLabel(lead: Lead) {
  const sourceUrl = lead.evidence[0]?.source_url.toLowerCase() ?? "";
  if (sourceUrl.includes("openstreetmap.org")) return "OpenStreetMap";
  if (sourceUrl.includes("tomtom.com")) return "TomTom";
  if (sourceUrl.includes("geoapify.com")) return "Geoapify";
  if (sourceUrl.includes("foursquare.com")) return "Foursquare";
  return "公开网页";
}

function DiscoveryWorkbench({
  productLines,
  selectedProductLineId,
  targetMarket,
  resolvedLocation,
  locationSubdivisions,
  resolvingLocation,
  allowRepeatLocation,
  buyerProfile,
  excludedKeywords,
  searchLimit,
  running,
  runMessage,
  sources,
  loadingSources,
  updatingSourceId,
  leads,
  showingLatestSearch,
  deletingLeadId,
  priorityOnly,
  selectedLeadIds,
  savingToCrm,
  runningDailyContactDiscovery,
  contactDiscoveryProgress,
  contactDiscoveryItems,
  discoveryRun,
  onProductLineChange,
  onTargetMarketChange,
  onResolveLocation,
  onSelectLocation,
  onAllowRepeatLocationChange,
  onBuyerProfileChange,
  onExcludedKeywordsChange,
  onSearchLimitChange,
  onSourceToggle,
  onRun,
  onPriorityToggle,
  onShowAllLeads,
  onDelete,
  onSelectLead,
  onSelectAllVisible,
  onSaveToCrm,
  onOpenDetail,
  onDiscoverDailyContacts,
  onRetryContactDiscovery,
}: {
  productLines: ProductLine[];
  selectedProductLineId: string;
  targetMarket: string;
  resolvedLocation: AdministrativeArea | null;
  locationSubdivisions: AdministrativeArea[];
  resolvingLocation: boolean;
  allowRepeatLocation: boolean;
  buyerProfile: string;
  excludedKeywords: string;
  searchLimit: number;
  running: boolean;
  runMessage: string;
  sources: SearchSource[];
  loadingSources: boolean;
  updatingSourceId: string;
  leads: Lead[];
  showingLatestSearch: boolean;
  deletingLeadId: string;
  priorityOnly: boolean;
  selectedLeadIds: string[];
  savingToCrm: boolean;
  runningDailyContactDiscovery: boolean;
  contactDiscoveryProgress: { completed: number; total: number } | null;
  contactDiscoveryItems: BatchContactDiscoveryItem[];
  discoveryRun: DiscoveryRun | null;
  onProductLineChange: (value: string) => void;
  onTargetMarketChange: (value: string) => void;
  onResolveLocation: () => void;
  onSelectLocation: (area: AdministrativeArea) => void;
  onAllowRepeatLocationChange: (value: boolean) => void;
  onBuyerProfileChange: (value: string) => void;
  onExcludedKeywordsChange: (value: string) => void;
  onSearchLimitChange: (value: number) => void;
  onSourceToggle: (sourceId: string, enabled: boolean) => void;
  onRun: (event: FormEvent<HTMLFormElement>) => void;
  onPriorityToggle: () => void;
  onShowAllLeads: () => void;
  onDelete: (leadId: string) => void;
  onSelectLead: (leadId: string, selected: boolean) => void;
  onSelectAllVisible: (leadIds: string[], selected: boolean) => void;
  onSaveToCrm: () => void;
  onOpenDetail: (leadId: string) => void;
  onDiscoverDailyContacts: () => void;
  onRetryContactDiscovery: () => void;
}) {
  const [contactStatusFilter, setContactStatusFilter] = useState<Lead["contact_discovery_status"] | "all">("all");
  const [lastAutomaticLocationQuery, setLastAutomaticLocationQuery] = useState("");
  const selectedProductLine = productLines.find((item) => item.id === selectedProductLineId);
  const buyerProfiles = selectedProductLine?.buyer_profiles ?? [];
  const enabledSources = sources.filter((source) => source.enabled);
  const readySources = enabledSources.filter((source) => source.configured || source.status === "ready");
  const bucketFilteredLeads = priorityOnly
    ? leads.filter((lead) => lead.bucket === "priority_recommendation")
    : leads;
  const displayedLeads = contactStatusFilter === "all"
    ? bucketFilteredLeads
    : bucketFilteredLeads.filter(
        (lead) => (lead.contact_discovery_status ?? "not_scanned") === contactStatusFilter
      );
  const selectableLeadIds = displayedLeads
    .filter((lead) => !isCrmLead(lead))
    .map((lead) => lead.id);
  const selectedVisibleIds = selectableLeadIds.filter((leadId) => selectedLeadIds.includes(leadId));
  const allVisibleSelected =
    selectableLeadIds.length > 0 && selectedVisibleIds.length === selectableLeadIds.length;

  useEffect(() => {
    const query = targetMarket.trim();
    if (!query || query === lastAutomaticLocationQuery || resolvedLocation || resolvingLocation) return;
    const timer = window.setTimeout(() => {
      setLastAutomaticLocationQuery(query);
      onResolveLocation();
    }, 800);
    return () => window.clearTimeout(timer);
  }, [lastAutomaticLocationQuery, onResolveLocation, resolvedLocation, resolvingLocation, targetMarket]);

  return (
    <section className="discoveryWorkbench" aria-labelledby="customer-agent-title">
      <header className="discoveryHeader">
        <div>
          <p className="sectionLabel">客户搜索</p>
          <h2 id="customer-agent-title">地图客户搜索工作台</h2>
          <p>按产品、地区和客户类型运行多来源搜索，筛选后直接进入联系方式补全或 CRM。</p>
        </div>
        <div className="sourceSummary" aria-label="搜索源概况">
          <strong>{readySources.length}</strong>
          <span>个来源可运行</span>
        </div>
      </header>
      <div className="discoveryBody">
        <aside className="discoveryControls" aria-label="客户搜索条件">
          <form className="discoveryForm" onSubmit={onRun}>
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
              国家 / 行政区
              <span className="locationLookup">
                <input
                  aria-label="搜索目标市场"
                  name="target_market"
                  required
                  placeholder="输入国家、省、州或城市，例如：北京"
                  value={targetMarket}
                  onChange={(event) => onTargetMarketChange(event.target.value)}
                />
                <button className="outlineButton" type="button" disabled={resolvingLocation || !targetMarket.trim()} onClick={onResolveLocation}>
                  {resolvingLocation ? "识别中" : "识别行政区"}
                </button>
              </span>
            </label>
            {resolvedLocation && (
              <section className="administrativeAreaPanel" aria-label="行政区选择">
                <div className="administrativeAreaCurrent">
                  <span>当前搜索范围</span>
                  <strong>{resolvedLocation.name}</strong>
                  <small>{resolvedLocation.formatted}</small>
                  {resolvedLocation.search_count > 0 && <em>已搜索 {resolvedLocation.search_count} 次</em>}
                </div>
                {locationSubdivisions.length > 0 ? (
                  <div className="administrativeAreaList">
                    <span>选择下级行政区，减少遗漏和重复</span>
                    <div>
                      {locationSubdivisions.map((area) => (
                        <button
                          className={area.search_count > 0 ? "areaOption areaSearched" : "areaOption"}
                          type="button"
                          key={area.scope_id}
                          onClick={() => onSelectLocation(area)}
                          title={area.search_count > 0 ? `已搜索 ${area.search_count} 次，点击查看或继续下钻` : "选择该行政区"}
                        >
                          <span>{area.name}</span>
                          <small>{area.search_count > 0 ? `已搜索 ${area.search_count} 次` : "未搜索"}</small>
                        </button>
                      ))}
                    </div>
                  </div>
                ) : (
                  <small className="fieldHint">没有找到更小的行政区，可以直接搜索当前范围。</small>
                )}
                {resolvedLocation.search_count > 0 && (
                  <label className="repeatLocationToggle">
                    <input type="checkbox" checked={allowRepeatLocation} onChange={(event) => onAllowRepeatLocationChange(event.target.checked)} />
                    允许重新搜索这个已覆盖区域
                  </label>
                )}
              </section>
            )}
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
            <label>
              结果数量
              <select
                aria-label="搜索结果数量"
                value={searchLimit}
                onChange={(event) => onSearchLimitChange(Number(event.target.value))}
              >
                <option value={20}>20 家（快速）</option>
                <option value={50}>50 家（标准）</option>
                <option value={100}>100 家（深度）</option>
                <option value={200}>200 家（批量）</option>
              </select>
            </label>
            <label className="discoveryWideField">
              排除同行 / 无效结果
              <input
                aria-label="搜索排除关键词"
                placeholder="同行品牌, manufacturer, factory, jobs"
                value={excludedKeywords}
                onChange={(event) => onExcludedKeywordsChange(event.target.value)}
              />
            </label>
            <button className="primaryButton discoveryRunButton" type="submit" disabled={running || !selectedProductLineId || !resolvedLocation || (resolvedLocation.search_count > 0 && !allowRepeatLocation) || readySources.length === 0}>
              {running ? "正在搜索..." : "开始搜索客户"}
            </button>
          </form>

          <section className="sourceChooser" aria-labelledby="search-source-title">
            <div className="sourceChooserHeader">
              <div>
                <span>数据来源</span>
                <h3 id="search-source-title">客户搜索源</h3>
              </div>
              <strong>{loadingSources ? "加载中" : `${enabledSources.length}/${sources.length}`}</strong>
            </div>
            {loadingSources ? (
              <div className="emptyState">正在加载搜索来源...</div>
            ) : (
              <div className="sourceToggleList">
                {sources.map((source) => {
                  const ready = source.configured || source.status === "ready";
                  return (
                    <label className="connectorItem sourceToggle" key={source.source_id}>
                      <input
                        type="checkbox"
                        checked={source.enabled}
                        disabled={updatingSourceId === source.source_id}
                        onChange={(event) => onSourceToggle(source.source_id, event.currentTarget.checked)}
                      />
                      <span className="sourceIdentity">
                        <strong>{source.label}</strong>
                        <small>{source.provider}</small>
                      </span>
                      <span className={ready ? "sourceState sourceReady" : "sourceState sourceNeedsConfig"}>
                        {source.enabled ? (ready ? "已启用" : "已启用 · 待配置") : "已停用"}
                      </span>
                    </label>
                  );
                })}
              </div>
            )}
          </section>
        </aside>

        <div className="discoveryResults" aria-labelledby="lead-results-title">
          <div className="resultsToolbar">
            <div>
              <p className="sectionLabel">{showingLatestSearch ? "本次搜索结果" : "全部搜索记录"}</p>
              <h2 id="lead-results-title">{showingLatestSearch ? "本次发现公司" : "已发现公司"}</h2>
            </div>
            <div className="resultFilters" aria-label="客户结果筛选">
              <button className={priorityOnly ? "segmentButton" : "segmentButton active"} type="button" onClick={priorityOnly ? onPriorityToggle : undefined}>全部</button>
              <button className={priorityOnly ? "segmentButton active" : "segmentButton"} type="button" onClick={priorityOnly ? undefined : onPriorityToggle}>优先客户</button>
              <select aria-label="联系方式状态筛选" value={contactStatusFilter} onChange={(event) => setContactStatusFilter(event.currentTarget.value as Lead["contact_discovery_status"] | "all")}>
                <option value="all">全部联系方式状态</option>
                <option value="has_email">有邮箱</option>
                <option value="has_contact">有人工联系方式</option>
                <option value="needs_review">待复查</option>
                <option value="no_contacts">未发现</option>
                <option value="not_scanned">未提取</option>
              </select>
            </div>
          </div>

          <div className="selectionBar">
            <label>
              <input
                type="checkbox"
                aria-label="选择全部未入库线索"
                checked={allVisibleSelected}
                disabled={selectableLeadIds.length === 0}
                onChange={(event) => onSelectAllVisible(selectableLeadIds, event.currentTarget.checked)}
              />
              选择当前 {selectableLeadIds.length} 家
            </label>
            <span>{displayedLeads.length} 家公司</span>
            {showingLatestSearch && <button className="textButton" type="button" onClick={onShowAllLeads}>查看历史线索</button>}
            <button className="outlineButton" type="button" disabled={savingToCrm || selectedLeadIds.length === 0} onClick={onSaveToCrm}>
              {savingToCrm ? "保存中..." : selectedLeadIds.length > 0 ? `保存 ${selectedLeadIds.length} 个到 CRM` : "保存到 CRM"}
            </button>
          </div>

          <div className="dailyContactBar" aria-label="今日线索联系方式提取">
            <div>
              <strong>批量提取客户联系方式</strong>
              <span>优先处理已勾选客户，否则处理当前搜索结果；只保存公开联系方式，不会发送邮件</span>
            </div>
            <button className="outlineButton" type="button" disabled={runningDailyContactDiscovery} onClick={onDiscoverDailyContacts}>
              {runningDailyContactDiscovery
                ? `正在提取 ${contactDiscoveryProgress?.completed ?? 0}/${contactDiscoveryProgress?.total ?? 0}`
                : selectedLeadIds.length > 0
                  ? `提取已选 ${selectedLeadIds.length} 家`
                  : `提取当前 ${leads.length} 家`}
            </button>
          </div>
          {contactDiscoveryProgress && (
            <div className="contactProgress" aria-label="联系方式提取进度" aria-live="polite">
              <progress value={contactDiscoveryProgress.completed} max={contactDiscoveryProgress.total} />
              <span>{contactDiscoveryProgress.completed} / {contactDiscoveryProgress.total} 家</span>
            </div>
          )}
          {contactDiscoveryItems.length > 0 && (
            <div className="dailyContactResult" aria-live="polite">
              <div className="dailyContactSummary">
                <strong>本次联系方式提取</strong>
                <span>有邮箱 {contactDiscoveryItems.filter((item) => item.status === "has_email").length} 家</span>
                <span>有人工联系方式 {contactDiscoveryItems.filter((item) => item.status === "has_contact").length} 家</span>
                <span>待复查 {contactDiscoveryItems.filter((item) => item.status === "needs_review").length} 家</span>
                <button className="textButton" type="button" disabled={runningDailyContactDiscovery || !contactDiscoveryItems.some((item) => item.status === "needs_review")} onClick={onRetryContactDiscovery}>
                  重试待复查
                </button>
              </div>
              <details className="dailyContactDetails">
                <summary>查看逐家公司联系方式</summary>
                <div>
                  {contactDiscoveryItems.map((item) => (
                    <article key={item.lead_id}>
                      <span className={`dailyContactState dailyContactState-${item.status}`}>{contactDiscoveryLabel[item.status]}</span>
                      <strong>{item.company_name}</strong>
                      <small>邮箱 {item.email_count}（已基础检查 {item.checked_email_count}） / 电话 {item.phone_count} / 社媒 {item.social_count} · {item.message}</small>
                      <button className="textButton" type="button" onClick={() => onOpenDetail(item.lead_id)}>查看客户</button>
                    </article>
                  ))}
                </div>
              </details>
            </div>
          )}
          <div className={`runStatus workbenchRunStatus ${runMessage.includes("完成") ? "runComplete" : ""}`} aria-live="polite">
            <span className="statusDot" aria-hidden="true" />
            {runMessage}
          </div>
          {discoveryRun && (discoveryRun.queries?.length ?? 0) > 0 && (
            <details className="dailyContactDetails discoveryQueryDetails">
              <summary>查看本次 {discoveryRun.query_count ?? discoveryRun.queries?.length ?? 1} 组搜索词</summary>
              <div>
                {(discoveryRun.queries ?? []).map((query, index) => (
                  <article key={`${index}-${query}`}>
                    <span className="sourceTag">查询 {index + 1}</span>
                    <strong>{query}</strong>
                  </article>
                ))}
              </div>
            </details>
          )}

          {leads.length === 0 ? (
            <div className="emptyState resultEmpty">暂无客户结果。设置左侧条件并启动搜索。</div>
          ) : displayedLeads.length === 0 ? (
            <div className="emptyState resultEmpty">本批结果中没有优先客户，请切换到“全部”。</div>
          ) : (
            <div className="leadResultList" aria-label="客户搜索结果列表">
              {displayedLeads.map((lead) => (
                <article className="leadResultRow" key={lead.id}>
                  <label className="leadSelect">
                    <input
                      type="checkbox"
                      aria-label={`选择 ${lead.company_name}`}
                      checked={selectedLeadIds.includes(lead.id)}
                      disabled={isCrmLead(lead)}
                      onChange={(event) => onSelectLead(lead.id, event.currentTarget.checked)}
                    />
                  </label>
                  <div className="leadResultMain">
                    <div className="leadTitleRow">
                      <div>
                        <strong>{lead.company_name}</strong>
                        <span>{lead.target_market} / {lead.buyer_profile ?? "不限类型"}</span>
                      </div>
                      <div className="leadMarks">
                        <span className={scoreClass(lead.score)}>{lead.score}</span>
                        <span className={bucketClass(lead.bucket)}>{bucketLabel[lead.bucket]}</span>
                        <span className={`contactState contactState-${lead.contact_discovery_status ?? "not_scanned"}`}>
                          {contactDiscoveryLabel[lead.contact_discovery_status ?? "not_scanned"]}
                          {(lead.contact_email_count ?? 0) > 0 ? ` ${lead.contact_email_count}` : ""}
                        </span>
                        {isCrmLead(lead) && <span className="status statusQualified">已入 CRM</span>}
                      </div>
                    </div>
                    <div className="leadEvidence">
                      <span className="sourceTag">{leadSourceLabel(lead)}</span>
                      <p>{lead.evidence[0]?.source_excerpt || lead.reasons[0] || "暂无来源摘要"}</p>
                    </div>
                    <div className="leadResultActions">
                      {lead.website ? <a href={lead.website} target="_blank" rel="noreferrer">打开官网</a> : <span>暂无官网</span>}
                      <button className="textButton" type="button" onClick={() => onOpenDetail(lead.id)}>查看并提取联系方式</button>
                      <button className="dangerTextButton" type="button" disabled={deletingLeadId === lead.id} onClick={() => onDelete(lead.id)}>
                        {deletingLeadId === lead.id ? "删除中..." : "删除"}
                      </button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function CRMCustomerManager({
  leads,
  productLines,
  selectedProductLineId,
  selectedCrmLeadIds,
  creating,
  deletingLeadId,
  runningBatch,
  batchMessage,
  batchResults,
  onCreate,
  onDelete,
  onOpenDetail,
  onSelectLead,
  onSelectAllVisible,
  onRunBatch,
}: {
  leads: Lead[];
  productLines: ProductLine[];
  selectedProductLineId: string;
  selectedCrmLeadIds: string[];
  creating: boolean;
  deletingLeadId: string;
  runningBatch: boolean;
  batchMessage: string;
  batchResults: CustomerBatchResultItem[];
  onCreate: (event: FormEvent<HTMLFormElement>) => void;
  onDelete: (leadId: string) => void;
  onOpenDetail: (leadId: string) => void;
  onSelectLead: (leadId: string, selected: boolean) => void;
  onSelectAllVisible: (leadIds: string[], selected: boolean) => void;
  onRunBatch: () => void;
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
  const visibleLeadIds = crmLeads.map((lead) => lead.id);
  const selectedVisibleIds = visibleLeadIds.filter((leadId) => selectedCrmLeadIds.includes(leadId));
  const allVisibleSelected = visibleLeadIds.length > 0 && selectedVisibleIds.length === visibleLeadIds.length;

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
          <div className="batchBar" aria-label="批量客户开发" aria-live="polite">
            <label className="checkboxField">
              <input
                type="checkbox"
                aria-label="选择当前筛选的 CRM 客户"
                checked={allVisibleSelected}
                disabled={visibleLeadIds.length === 0 || runningBatch}
                onChange={(event) => onSelectAllVisible(visibleLeadIds, event.currentTarget.checked)}
              />
              选择当前筛选客户
            </label>
            <button
              className="outlineButton"
              type="button"
              disabled={runningBatch || selectedCrmLeadIds.length === 0}
              onClick={onRunBatch}
            >
              {runningBatch ? "批量处理中..." : `批量开发 ${selectedCrmLeadIds.length} 个客户`}
            </button>
            <span>{batchMessage || "批量流程：查邮箱、验证邮箱、为可发送联系人生成开发信草稿"}</span>
          </div>
          {batchResults.length > 0 ? (
            <div className="batchResults" aria-label="批量开发处理结果">
              {batchResults.map((item) => (
                <div className={`batchResultItem ${item.status}`} key={item.leadId}>
                  <strong>{item.companyName}</strong>
                  <span>{item.message}</span>
                </div>
              ))}
            </div>
          ) : null}
          {crmLeads.length === 0 ? (
            <div className="emptyState">
              {allCrmLeads.length === 0
                ? "暂无 CRM 客户。你可以手动添加客户，或从搜索结果勾选线索保存到 CRM。"
                : "没有匹配当前筛选条件的 CRM 客户。"}
            </div>
          ) : (
            crmLeads.map((lead) => (
              <article className="crmItem" key={lead.id}>
                <input
                  type="checkbox"
                  aria-label={`选择 CRM 客户 ${lead.company_name}`}
                  checked={selectedCrmLeadIds.includes(lead.id)}
                  disabled={runningBatch}
                  onChange={(event) => onSelectLead(lead.id, event.currentTarget.checked)}
                />
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
  const formLinks = productLines.flatMap((productLine) => {
    const productItems = (productLine.product_items ?? []).filter((productItem) => productItem.is_published);
    if (productItems.length === 0) {
      return [{
        id: productLine.id,
        label: productLine.name,
        detail: "产品线询盘链接",
        url: buildInquiryFormUrl(formBaseUrl, organizationId, productLine),
      }];
    }
    return productItems.map((productItem) => ({
      id: productItem.id,
      label: productItem.name,
      detail: `${productLine.name} / ${productItem.sku || "未填 SKU"}`,
      url: buildInquiryFormUrl(formBaseUrl, organizationId, productLine, productItem),
    }));
  });

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
          formLinks.map((formLink) => (
              <article className="inquiryLinkItem" key={formLink.id}>
                <div>
                  <strong>{formLink.label}</strong>
                  <small>{formLink.detail}</small>
                  <span>{formLink.url}</span>
                </div>
                <div>
                  <a className="textButton" href={formLink.url} target="_blank" rel="noreferrer">打开表单</a>
                  <button
                    className="textButton"
                    type="button"
                    onClick={() => void navigator.clipboard.writeText(formLink.url)}
                  >
                    复制链接
                  </button>
                </div>
              </article>
          ))
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
                <span>{inquiry.product_item_name || "未绑定具体产品"}</span>
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
  emailDeliveryStatus,
  onOpen,
  onOpenDraft,
}: {
  drafts: EmailDraft[];
  loading: boolean;
  emailDeliveryStatus: EmailDeliveryStatus | null;
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
      <div className="reviewFooter">
        <span>发件邮箱</span>
        <strong>
          {emailDeliveryStatus?.configured
            ? `${emailDeliveryStatus.from_name} / ${emailDeliveryStatus.from_email}`
            : "未配置 SMTP，暂不能真实发送"}
        </strong>
      </div>
    </section>
  );
}

function ConnectorStatusPanel({
  connectors,
  loading,
}: {
  connectors: ConnectorStatus[];
  loading: boolean;
}) {
  const configuredCount = connectors.filter((connector) => connector.configured).length;
  return (
    <section className="timelinePanel" aria-labelledby="connector-title">
      <div className="sectionHeader compact">
        <div>
          <p className="sectionLabel">API 连接</p>
          <h2 id="connector-title">客户开发 API</h2>
        </div>
        <span className="countBadge">
          {loading ? "检查中" : `${configuredCount}/${connectors.length || 6}`}
        </span>
      </div>
      {loading ? (
        <div className="emptyState">正在检查客户开发 API 配置...</div>
      ) : (
        <div className="connectorList">
          {connectors.map((connector) => (
            <div className="connectorItem" key={connector.connector_id}>
              <div>
                <strong>{connector.label}</strong>
                <span>{connector.provider} / {connector.purpose}</span>
              </div>
              <span className={connector.configured ? "status statusQualified" : "status statusResearch"}>
                {connector.configured ? "已配置" : `缺 ${connector.missing.join(", ")}`}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function ApiStatusPage({
  connectors,
  sources,
  loadingConnectors,
  loadingSources,
  error,
  updatingSourceId,
  onSourceToggle,
  onRefresh,
}: {
  connectors: ConnectorStatus[];
  sources: SearchSource[];
  loadingConnectors: boolean;
  loadingSources: boolean;
  error: string;
  updatingSourceId: string;
  onSourceToggle: (sourceId: string, enabled: boolean) => void;
  onRefresh: () => void;
}) {
  const configuredCount = connectors.filter((connector) => connector.configured).length;
  const enabledSources = sources.filter((source) => source.enabled);
  const runnableSources = enabledSources.filter((source) => source.configured || source.status === "ready");
  const needsConfigCount = sources.filter((source) => source.enabled && !source.configured && source.status !== "ready").length;

  return (
    <div className="apiStatusPage" aria-label="API 接口状态页面">
      <section className="pageHeading apiPageHeading">
        <div>
          <p className="sectionLabel">系统连接</p>
          <h1>API 接口状态</h1>
          <p>集中查看客户搜索、联系方式补全和邮件开发相关接口的启用与配置状态。</p>
        </div>
        <button className="outlineButton" type="button" disabled={loadingConnectors || loadingSources} onClick={onRefresh}>
          {loadingConnectors || loadingSources ? "检查中..." : "重新检查"}
        </button>
      </section>

      {error && <div className="errorBanner apiErrorBanner" role="alert">{error}</div>}

      <section className="apiMetricGrid" aria-label="API 状态概览">
        <div><span>已配置接口</span><strong>{configuredCount}</strong><small>共 {connectors.length} 个客户开发接口</small></div>
        <div><span>已启用来源</span><strong>{enabledSources.length}</strong><small>共 {sources.length} 个搜索来源</small></div>
        <div><span>可运行来源</span><strong>{runnableSources.length}</strong><small>启用且配置完整</small></div>
        <div className={needsConfigCount > 0 ? "metricAttention" : ""}><span>待配置</span><strong>{needsConfigCount}</strong><small>已启用但缺少密钥</small></div>
      </section>

      <section className="apiStatusSection" aria-labelledby="website-api-status-title">
        <div className="sectionHeader">
          <div>
            <p className="sectionLabel">搜索平台</p>
            <h2 id="website-api-status-title">网站 API 接口链接状态</h2>
          </div>
          <span className="countBadge">{loadingSources ? "检查中" : `${runnableSources.length}/${sources.length} 可运行`}</span>
        </div>
        {loadingSources ? (
          <div className="emptyState apiStatusEmpty">正在检查搜索平台接口...</div>
        ) : sources.length === 0 ? (
          <div className="emptyState apiStatusEmpty">未获取到接口目录。请确认后端 API 服务已启动，然后点击“重新检查”。</div>
        ) : (
          <div className="apiSourceList" aria-label="网站 API 接口列表">
            <div className="apiSourceHeader" aria-hidden="true">
              <span>平台 / 用途</span><span>接口地址</span><span>启用</span><span>配置</span><span>运行状态</span>
            </div>
            {sources.map((source) => {
              const ready = source.configured || source.status === "ready";
              const runnable = source.enabled && ready;
              return (
                <article className="apiSourceRow" key={source.source_id}>
                  <div className="apiSourceName">
                    <strong>{source.label}</strong>
                    <span>{source.provider}</span>
                    <small>{source.purpose}</small>
                  </div>
                  <a href={source.base_url} target="_blank" rel="noreferrer">打开平台</a>
                  <label className="switchField apiSourceSwitch">
                    <input
                      type="checkbox"
                      checked={source.enabled}
                      disabled={updatingSourceId === source.source_id}
                      onChange={(event) => onSourceToggle(source.source_id, event.currentTarget.checked)}
                    />
                    <span>{source.enabled ? "已启用" : "已停用"}</span>
                  </label>
                  <span className={ready ? "apiState apiStateReady" : "apiState apiStateWarning"}>
                    {ready ? "已配置" : "缺少配置"}
                  </span>
                  <span className={runnable ? "apiState apiStateReady" : "apiState apiStateMuted"}>
                    {runnable ? "可运行" : source.enabled ? "等待配置" : "未运行"}
                  </span>
                  {!ready && source.missing.length > 0 && <small className="apiMissing">缺少：{source.missing.join(", ")}</small>}
                </article>
              );
            })}
          </div>
        )}
      </section>

      <section className="apiStatusSection" aria-labelledby="development-api-title">
        <div className="sectionHeader">
          <div>
            <p className="sectionLabel">功能接口</p>
            <h2 id="development-api-title">客户开发 API</h2>
          </div>
          <span className="countBadge">{loadingConnectors ? "检查中" : `${configuredCount}/${connectors.length} 已配置`}</span>
        </div>
        {loadingConnectors ? (
          <div className="emptyState apiStatusEmpty">正在检查客户开发 API...</div>
        ) : connectors.length === 0 ? (
          <div className="emptyState apiStatusEmpty">未获取到客户开发 API 状态。请检查后端连接后重新加载。</div>
        ) : (
          <div className="developmentApiGrid" aria-label="客户开发 API 列表">
            {connectors.map((connector) => (
              <article key={connector.connector_id}>
                <div>
                  <strong>{connector.label}</strong>
                  <span>{connector.provider}</span>
                  <small>{connector.purpose}</small>
                </div>
                <span className={connector.configured ? "apiState apiStateReady" : "apiState apiStateWarning"}>
                  {connector.configured ? "已配置" : "待配置"}
                </span>
                {!connector.configured && connector.missing.length > 0 && <small className="apiMissing">缺少：{connector.missing.join(", ")}</small>}
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

const knowledgeStatusLabel: Record<KnowledgeDocumentStatus, string> = {
  uploaded: "已上传",
  processing: "处理中",
  ready: "就绪",
  failed: "失败",
};

function knowledgeStatusClass(status: KnowledgeDocumentStatus) {
  if (status === "ready") return "kbStatus kbReady";
  if (status === "processing") return "kbStatus kbProcessing";
  if (status === "failed") return "kbStatus kbFailed";
  return "kbStatus kbUploaded";
}

function KnowledgeBasePanel({
  documents,
  productLines,
  isAdmin,
  loading,
  uploading,
  onCreate,
  onRefresh,
}: {
  documents: KnowledgeDocument[];
  productLines: ProductLine[];
  isAdmin: boolean;
  loading: boolean;
  uploading: boolean;
  onCreate: (event: FormEvent<HTMLFormElement>) => void;
  onRefresh: () => void;
}) {
  const productLineNameById = new Map(productLines.map((line) => [line.id, line.name]));
  return (
    <section className="knowledgePanel" aria-labelledby="knowledge-title">
      <div className="sectionHeader">
        <div>
          <p className="sectionLabel">知识库</p>
          <h2 id="knowledge-title">组织知识库</h2>
        </div>
        <div className="tableActions">
          <span className="countBadge">{loading ? "加载中" : `${documents.length} 个文档`}</span>
          <button className="textButton" type="button" onClick={onRefresh}>刷新</button>
        </div>
      </div>
      {isAdmin && (
        <form className="knowledgeForm" onSubmit={onCreate}>
          <label>
            产品线（可选）
            <select name="product_line_id" defaultValue="">
              <option value="">不绑定产品线</option>
              {productLines.map((line) => (
                <option key={line.id} value={line.id}>{line.name}</option>
              ))}
            </select>
          </label>
          <label>
            上传文档（PDF / DOCX / XLSX）
            <input name="file" type="file" accept=".pdf,.docx,.xlsx" required />
          </label>
          <button className="primaryButton" type="submit" disabled={uploading}>
            {uploading ? "上传处理中..." : "上传文档"}
          </button>
        </form>
      )}
      {loading ? (
        <div className="emptyState knowledgeEmpty">正在加载知识库文档...</div>
      ) : documents.length === 0 ? (
        <div className="emptyState knowledgeEmpty">
          {isAdmin
            ? "上传 PDF、DOCX 或 XLSX 文档，系统会自动切分并向量化，供后续邮件上下文检索使用。"
            : "暂无知识库文档。"}
        </div>
      ) : (
        <div className="knowledgeList" aria-label="知识库文档列表">
          {documents.map((document) => (
            <article className="knowledgeItem" key={document.id}>
              <div className="knowledgeItemMain">
                <strong>{document.filename}</strong>
                <span>
                  {document.product_line_id
                    ? productLineNameById.get(document.product_line_id) ?? "产品线已停用"
                    : "未绑定产品线"}{" "}/ {formatDateTime(document.created_at)}
                </span>
              </div>
              <span className={knowledgeStatusClass(document.status)}>
                {knowledgeStatusLabel[document.status] ?? document.status}
              </span>
              {isAdmin && document.failure_message ? (
                <small className="knowledgeFailure">{document.failure_message}</small>
              ) : null}
            </article>
          ))}
        </div>
      )}
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

function FollowUpTaskBoard({
  tasks,
  loading,
  completingTaskId,
  onRefresh,
  onComplete,
}: {
  tasks: FollowUpTask[];
  loading: boolean;
  completingTaskId: string;
  onRefresh: () => void;
  onComplete: (taskId: string) => void;
}) {
  const openTasks = tasks.filter((task) => task.status === "open");
  return (
    <section className="timelinePanel" aria-labelledby="task-board-title">
      <div className="sectionHeader compact">
        <div>
          <p className="sectionLabel">销售任务</p>
          <h2 id="task-board-title">跟进任务</h2>
        </div>
        <button className="iconTextButton" type="button" onClick={onRefresh}>刷新</button>
      </div>
      {loading ? (
        <div className="emptyState">正在加载跟进任务...</div>
      ) : openTasks.length === 0 ? (
        <div className="emptyState">暂无待办任务。可以在客户详情页创建报价、电话或样品跟进任务。</div>
      ) : (
        <div className="taskList" aria-label="跟进任务列表">
          {openTasks.slice(0, 5).map((task) => (
            <article className="taskItem" key={task.id}>
              <div>
                <strong>{task.title}</strong>
                <span>{task.lead_company_name ?? "客户"} / {taskTypeLabel(task.task_type)}</span>
                <small>
                  {task.quote_status ? quoteStatusLabel[task.quote_status] ?? task.quote_status : "无报价状态"} / 截止：{formatDateTime(task.due_at)}
                </small>
              </div>
              <button
                className="outlineButton"
                type="button"
                disabled={completingTaskId === task.id}
                onClick={() => onComplete(task.id)}
              >
                {completingTaskId === task.id ? "完成中..." : "标记完成"}
              </button>
            </article>
          ))}
        </div>
      )}
      <div className="reviewFooter"><span>待完成</span><strong>{openTasks.length} 个任务</strong></div>
    </section>
  );
}

function sendRiskClass(level: EmailDraft["send_risk_level"]) {
  if (level === "safe") return "sendRisk sendRiskSafe";
  if (level === "blocked") return "sendRisk sendRiskBlocked";
  if (level === "caution") return "sendRisk sendRiskCaution";
  return "sendRisk sendRiskWarning";
}

function draftVerificationSummary(draft: EmailDraft) {
  const status = draft.contact_email_verification_status;
  if (!status) return "邮箱验证：未验证";
  const provider = draft.contact_email_verification_provider || "验证服务";
  const subStatus = draft.contact_email_verification_sub_status
    ? ` / ${draft.contact_email_verification_sub_status}`
    : "";
  return `邮箱验证：${provider} / ${status}${subStatus}`;
}

function normalizeContactEmailStatus(contact: ContactRecord) {
  return contact.email_verification_status.trim().toLowerCase().replaceAll("-", "_");
}

function contactEmailIsBlocked(contact: ContactRecord) {
  return blockedContactEmailStatuses.has(normalizeContactEmailStatus(contact));
}

function contactIsBatchEligible(contact: ContactRecord) {
  return Boolean(contact.email.trim()) && !contactEmailIsBlocked(contact);
}

function chooseBatchContact(contacts: ContactRecord[], existingDrafts: EmailDraft[]) {
  const draftedContactIds = new Set(
    existingDrafts
      .filter((draft) => draft.status !== "rejected")
      .map((draft) => draft.contact_id)
  );
  return contacts
    .filter((contact) => contactIsBatchEligible(contact) && !draftedContactIds.has(contact.id))
    .sort((a, b) => {
      const verificationRank = (contact: ContactRecord) =>
        batchEligibleContactEmailStatuses.has(normalizeContactEmailStatus(contact)) ? 1 : 0;
      return verificationRank(b) - verificationRank(a) || Number(b.is_primary) - Number(a.is_primary);
    })[0] ?? null;
}

function contactHasManualChannel(contact: ContactRecord) {
  return Boolean(
    contact.phone.trim() ||
    contact.linkedin_url.trim() ||
    contact.whatsapp.trim() ||
    contact.social_profiles.length
  );
}

function batchFailureMessage(caught: unknown) {
  const message = caught instanceof Error ? caught.message : "未知错误";
  if (message.includes("could not reach the site")) return "官网当前无法访问";
  if (message.includes("did not return HTML")) return "官网未返回可提取的网页内容";
  if (message.includes("HTTP ")) return `官网拒绝访问（${message.match(/HTTP \d+/)?.[0] ?? "HTTP 错误"}）`;
  if (message.includes("public contact discovery failed")) return "官网联系方式提取失败";
  if (message.includes("host could not be resolved")) return "官网域名无法解析";
  if (message.includes("non-public address")) return "官网地址被安全策略拦截";
  return message;
}

function ReviewDrawer({
  open,
  draft,
  saving,
  savingRecipient,
  verifyingRecipient,
  reviewing,
  onClose,
  onSave,
  onSaveRecipient,
  onVerifyRecipient,
  onApprove,
  onMarkSent,
  onReject,
}: {
  open: boolean;
  draft: EmailDraft | null;
  saving: boolean;
  savingRecipient: boolean;
  verifyingRecipient: boolean;
  reviewing: boolean;
  onClose: () => void;
  onSave: (event: FormEvent<HTMLFormElement>) => void;
  onSaveRecipient: (event: FormEvent<HTMLFormElement>) => void;
  onVerifyRecipient: () => void;
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
              <div className={sendRiskClass(draft.send_risk_level)}>
                <strong>{sendRiskLabel[draft.send_risk_level]}</strong>
                <span>{draft.send_risk_message}</span>
              </div>
              <div className="draftEvidence">
                {draft.evidence_snapshot.length === 0 ? (
                  <span>暂无证据快照</span>
                ) : (
                  draft.evidence_snapshot.map((item) => <span key={`${item.signal_name}-${item.source_url}`}>{item.signal_name}</span>)
                )}
              </div>
            </article>
            <form className="recipientEditForm" onSubmit={onSaveRecipient} key={`recipient-${draft.id}-${draft.current_contact_email}-${draft.contact_email}`}>
              <label>
                客户邮箱地址
                <input
                  name="contact_email"
                  type="email"
                  required
                  defaultValue={draft.current_contact_email || draft.contact_email}
                  disabled={draft.status === "ready_to_send"}
                />
              </label>
              <div className="recipientMeta">
                <span>{draftVerificationSummary(draft)}</span>
                {draft.contact_source_url ? (
                  <a href={draft.contact_source_url} target="_blank" rel="noreferrer">查看邮箱来源页</a>
                ) : (
                  <span>未记录邮箱来源页</span>
                )}
              </div>
              <div className="recipientActions">
                <button className="outlineButton" type="submit" disabled={savingRecipient || draft.status === "ready_to_send"}>
                  {savingRecipient ? "保存中..." : "保存邮箱"}
                </button>
                <button className="outlineButton" type="button" disabled={verifyingRecipient || draft.status === "ready_to_send"} onClick={onVerifyRecipient}>
                  {verifyingRecipient ? "验证中..." : "验证当前邮箱"}
                </button>
              </div>
              <small>
                {draft.status === "sent"
                  ? `本封邮件已发送到 ${draft.contact_email}；这里修改的是客户当前邮箱，供后续开发使用。`
                  : "修改邮箱后会自动清除旧验证结果，请重新验证后再批准发送。"}
              </small>
            </form>
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
                <button className="primaryButton" type="button" disabled={reviewing || draft.status !== "ready_to_send" || draft.send_blocked} onClick={onMarkSent}>
                  {reviewing ? "发送中..." : "发送开发信"}
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
  addingTask,
  addingQuoteDraft,
  discoveringContacts,
  deletingContactId,
  verifyingContactId,
  generatingDraftContactId,
  completingTaskId,
  savingQuoteDraftId,
  sendingQuoteDraftId,
  onClose,
  onSave,
  onAddContact,
  onDiscoverContacts,
  onDeleteContact,
  onVerifyContactEmail,
  onCreateEmailDraft,
  onAddFollowUp,
  onAddTask,
  onCompleteTask,
  onCreateQuoteDraft,
  onUpdateQuoteDraft,
  onMarkQuoteDraftSent,
}: {
  detail: LeadDetail | null;
  loading: boolean;
  saving: boolean;
  addingContact: boolean;
  addingFollowUp: boolean;
  addingTask: boolean;
  addingQuoteDraft: boolean;
  discoveringContacts: boolean;
  deletingContactId: string;
  verifyingContactId: string;
  generatingDraftContactId: string;
  completingTaskId: string;
  savingQuoteDraftId: string;
  sendingQuoteDraftId: string;
  onClose: () => void;
  onSave: (event: FormEvent<HTMLFormElement>) => void;
  onAddContact: (event: FormEvent<HTMLFormElement>) => void;
  onDiscoverContacts: () => void;
  onDeleteContact: (contactId: string) => void;
  onVerifyContactEmail: (contactId: string) => void;
  onCreateEmailDraft: (contactId: string) => void;
  onAddFollowUp: (event: FormEvent<HTMLFormElement>) => void;
  onAddTask: (event: FormEvent<HTMLFormElement>) => void;
  onCompleteTask: (taskId: string) => void;
  onCreateQuoteDraft: (event: FormEvent<HTMLFormElement>) => void;
  onUpdateQuoteDraft: (draftId: string, event: FormEvent<HTMLFormElement>) => void;
  onMarkQuoteDraftSent: (draftId: string) => void;
}) {
  if (!detail && !loading) return null;
  const followUpTasks = detail?.follow_up_tasks ?? [];
  const quoteDrafts = detail?.quote_drafts ?? [];

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
              <button
                className="outlineButton compactButton"
                type="button"
                disabled={discoveringContacts}
                onClick={onDiscoverContacts}
              >
                {discoveringContacts ? "扫描中..." : "扫描公开联系方式"}
              </button>
              {detail.contacts.length === 0 ? (
                <p className="mutedCopy">暂无联系方式。可录入电话、社交主页或邮箱，后续跟进可以绑定到具体的人或企业。</p>
              ) : (
                <ul className="contactList">
                  {detail.contacts.map((contact: ContactRecord) => (
                    <li key={contact.id}>
                      <div>
                        <strong>{contact.name}</strong>
                        {contact.is_primary && <span className="primaryBadge">主要联系人</span>}
                      </div>
                      <p>{contact.title || "未填写职位"}</p>
                      <div className="contactChannels">
                        {contact.email && <a href={`mailto:${contact.email}`}>邮箱</a>}
                        {contact.phone && <a href={`tel:${contact.phone}`}>电话</a>}
                        {contact.whatsapp && (
                          <a href={whatsappLink(contact.whatsapp)} target="_blank" rel="noreferrer">WhatsApp</a>
                        )}
                        {contact.linkedin_url && (
                          <a href={contact.linkedin_url} target="_blank" rel="noreferrer">LinkedIn</a>
                        )}
                        {(contact.social_profiles ?? []).map((profile) => (
                          <a key={`${profile.platform}-${profile.url}`} href={profile.url} target="_blank" rel="noreferrer">
                            {profile.platform}
                          </a>
                        ))}
                        {contact.source_url && (
                          <a href={contact.source_url} target="_blank" rel="noreferrer">来源页</a>
                        )}
                      </div>
                      {contact.email && (
                        <small className="verificationStatus">
                          {contact.email_verification_status
                            ? `邮箱验证：${contact.email_verification_provider || "Provider"} / ${contact.email_verification_status}${
                                contact.email_verification_sub_status ? ` / ${contact.email_verification_sub_status}` : ""
                              }`
                            : "邮箱验证：未验证"}
                        </small>
                      )}
                      <button
                        className="textButton"
                        type="button"
                        disabled={!contact.email || verifyingContactId === contact.id}
                        onClick={() => onVerifyContactEmail(contact.id)}
                      >
                        {verifyingContactId === contact.id ? "验证中..." : "验证邮箱"}
                      </button>
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
              <label>
                Facebook
                <input name="facebook_url" placeholder="https://facebook.com/..." />
              </label>
              <label>
                Instagram
                <input name="instagram_url" placeholder="https://instagram.com/..." />
              </label>
              <label>
                TikTok
                <input name="tiktok_url" placeholder="https://tiktok.com/@..." />
              </label>
              <label>
                其他社交主页
                <input name="other_social_url" placeholder="https://..." />
              </label>
              <label className="wideField">
                联系方式来源页
                <input name="source_url" placeholder="企业官网联系页、Google 地图或目录页" />
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

            <form className="quoteForm" onSubmit={onCreateQuoteDraft} key={`quote-${detail.id}-${quoteDrafts.length}`}>
              <h3>新增报价草稿</h3>
              <label className="wideField">
                报价标题
                <input name="title" required maxLength={200} defaultValue={`${detail.company_name} 报价草稿`} />
              </label>
              <label>
                币种
                <input name="currency" required maxLength={10} defaultValue="USD" />
              </label>
              <label>
                贸易条款
                <input name="incoterm" required maxLength={20} defaultValue="FOB" />
              </label>
              <label>
                有效期
                <input name="valid_until" type="date" />
              </label>
              <label>
                产品 / 服务
                <input name="item_name" required maxLength={200} placeholder="例如：LED floodlight 200W" />
              </label>
              <label>
                数量
                <input name="quantity" required min="0.01" step="0.01" type="number" placeholder="500" />
              </label>
              <label>
                单价
                <input name="unit_price" required min="0" step="0.01" type="number" placeholder="12.50" />
              </label>
              <label>
                单位
                <input name="unit" maxLength={50} defaultValue="pcs" />
              </label>
              <label className="wideField">
                行项目备注
                <input name="line_notes" maxLength={500} placeholder="例如：Sample batch / Lead time 20 days" />
              </label>
              <label className="wideField">
                报价备注
                <textarea name="notes" maxLength={2000} placeholder="例如：价格需人工复核，发出前确认包装、交期和付款条款。" />
              </label>
              <button className="primaryButton" type="submit" disabled={addingQuoteDraft}>
                {addingQuoteDraft ? "创建中..." : "创建报价草稿"}
              </button>
            </form>

            <section className="detailBlock">
              <h3>报价草稿</h3>
              {quoteDrafts.length === 0 ? (
                <p className="mutedCopy">暂无报价草稿。报价只会保存为草稿或人工标记已发送，不会自动发送给客户。</p>
              ) : (
                <div className="quoteDraftList">
                  {quoteDrafts.map((draft: QuoteDraft) => {
                    const firstLine = draft.line_items[0];
                    return (
                      <form
                        className="quoteDraftItem"
                        key={draft.id}
                        onSubmit={(event) => onUpdateQuoteDraft(draft.id, event)}
                      >
                        <div className="quoteDraftHeader">
                          <div>
                            <strong>{draft.title}</strong>
                            <span>{quoteDraftStatusLabel[draft.status]} / {draft.currency} {draft.total_amount.toFixed(2)} / {draft.incoterm}</span>
                          </div>
                          <small>{draft.status === "sent" ? `发送：${formatDateTime(draft.sent_at)}` : `更新：${formatDateTime(draft.updated_at)}`}</small>
                        </div>
                        <label className="wideField">
                          报价标题
                          <input name="title" defaultValue={draft.title} disabled={draft.status !== "draft"} />
                        </label>
                        <label>
                          币种
                          <input name="currency" defaultValue={draft.currency} disabled={draft.status !== "draft"} />
                        </label>
                        <label>
                          贸易条款
                          <input name="incoterm" defaultValue={draft.incoterm} disabled={draft.status !== "draft"} />
                        </label>
                        <label>
                          有效期
                          <input name="valid_until" type="date" defaultValue={draft.valid_until?.slice(0, 10) ?? ""} disabled={draft.status !== "draft"} />
                        </label>
                        <label>
                          产品 / 服务
                          <input name="item_name" defaultValue={firstLine?.item_name ?? ""} disabled={draft.status !== "draft"} />
                        </label>
                        <label>
                          数量
                          <input name="quantity" type="number" step="0.01" min="0.01" defaultValue={firstLine?.quantity ?? 1} disabled={draft.status !== "draft"} />
                        </label>
                        <label>
                          单价
                          <input name="unit_price" type="number" step="0.01" min="0" defaultValue={firstLine?.unit_price ?? 0} disabled={draft.status !== "draft"} />
                        </label>
                        <label>
                          单位
                          <input name="unit" defaultValue={firstLine?.unit ?? "pcs"} disabled={draft.status !== "draft"} />
                        </label>
                        <label className="wideField">
                          行项目备注
                          <input name="line_notes" defaultValue={firstLine?.notes ?? ""} disabled={draft.status !== "draft"} />
                        </label>
                        <label className="wideField">
                          报价备注
                          <textarea name="notes" defaultValue={draft.notes} disabled={draft.status !== "draft"} />
                        </label>
                        <div className="drawerActions">
                          <button className="outlineButton" type="submit" disabled={draft.status !== "draft" || savingQuoteDraftId === draft.id}>
                            {savingQuoteDraftId === draft.id ? "保存中..." : "保存报价草稿"}
                          </button>
                          <button
                            className="primaryButton"
                            type="button"
                            disabled={draft.status !== "draft" || sendingQuoteDraftId === draft.id}
                            onClick={() => onMarkQuoteDraftSent(draft.id)}
                          >
                            {sendingQuoteDraftId === draft.id ? "记录中..." : "标记已发送报价"}
                          </button>
                        </div>
                      </form>
                    );
                  })}
                </div>
              )}
            </section>

            <form className="taskForm" onSubmit={onAddTask} key={`task-${detail.id}-${followUpTasks.length}`}>
              <h3>新增跟进任务</h3>
              <label>
                任务类型
                <select name="task_type" defaultValue="follow_up">
                  <option value="follow_up">普通跟进</option>
                  <option value="quote">报价</option>
                  <option value="sample">样品</option>
                  <option value="call">电话</option>
                  <option value="meeting">会议</option>
                </select>
              </label>
              <label>
                报价状态
                <select name="quote_status" defaultValue="">
                  <option value="">不设置</option>
                  <option value="requested">客户要报价</option>
                  <option value="preparing_quote">准备报价</option>
                  <option value="quote_sent">已发报价</option>
                  <option value="negotiating">谈判中</option>
                </select>
              </label>
              <label>
                截止时间
                <input name="due_at" type="datetime-local" />
              </label>
              <label className="wideField">
                任务内容
                <textarea name="title" required maxLength={200} placeholder="例如：准备 500 套样品 FOB 报价并发给客户。" />
              </label>
              <button className="primaryButton" type="submit" disabled={addingTask}>
                {addingTask ? "创建中..." : "创建任务"}
              </button>
            </form>

            <section className="detailBlock">
              <h3>跟进任务</h3>
              {followUpTasks.length === 0 ? (
                <p className="mutedCopy">暂无跟进任务。</p>
              ) : (
                <div className="taskList">
                  {followUpTasks.map((task: FollowUpTask) => (
                    <article className="taskItem" key={task.id}>
                      <div>
                        <strong>{task.title}</strong>
                        <span>{taskTypeLabel(task.task_type)} / {followUpTaskStatusLabel[task.status]}</span>
                        <small>
                          {task.quote_status ? quoteStatusLabel[task.quote_status] ?? task.quote_status : "无报价状态"} / 截止：{formatDateTime(task.due_at)}
                        </small>
                      </div>
                      <button
                        className="outlineButton"
                        type="button"
                        disabled={task.status !== "open" || completingTaskId === task.id}
                        onClick={() => onCompleteTask(task.id)}
                      >
                        {completingTaskId === task.id ? "完成中..." : task.status === "open" ? "标记完成" : "已完成"}
                      </button>
                    </article>
                  ))}
                </div>
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
  const [deletingProductLineId, setDeletingProductLineId] = useState("");
  const [creatingProductItem, setCreatingProductItem] = useState(false);
  const [deletingProductItemId, setDeletingProductItemId] = useState("");
  const [productLines, setProductLines] = useState<ProductLine[]>([]);
  const [selectedProductLineId, setSelectedProductLineId] = useState("");
  const [targetMarket, setTargetMarket] = useState("");
  const [resolvedLocation, setResolvedLocation] = useState<AdministrativeArea | null>(null);
  const [locationSubdivisions, setLocationSubdivisions] = useState<AdministrativeArea[]>([]);
  const [resolvingLocation, setResolvingLocation] = useState(false);
  const [allowRepeatLocation, setAllowRepeatLocation] = useState(false);
  const [buyerProfile, setBuyerProfile] = useState("");
  const [excludedKeywords, setExcludedKeywords] = useState("");
  const [searchLimit, setSearchLimit] = useState(50);
  const [leads, setLeads] = useState<Lead[]>([]);
  const sortedLeads = useMemo(() => sortLeadsNewestFirst(leads), [leads]);
  const [running, setRunning] = useState(false);
  const [runningDailyContactDiscovery, setRunningDailyContactDiscovery] = useState(false);
  const [contactDiscoveryProgress, setContactDiscoveryProgress] = useState<{ completed: number; total: number } | null>(null);
  const [contactDiscoveryItems, setContactDiscoveryItems] = useState<BatchContactDiscoveryItem[]>([]);
  const [lastDiscoveryRun, setLastDiscoveryRun] = useState<DiscoveryRun | null>(null);
  const [selectedLeadIds, setSelectedLeadIds] = useState<string[]>([]);
  const [latestSearchLeadIds, setLatestSearchLeadIds] = useState<string[] | null>(null);
  const [savingToCrm, setSavingToCrm] = useState(false);
  const [selectedCrmLeadIds, setSelectedCrmLeadIds] = useState<string[]>([]);
  const [runningCustomerBatch, setRunningCustomerBatch] = useState(false);
  const [customerBatchMessage, setCustomerBatchMessage] = useState("");
  const [customerBatchResults, setCustomerBatchResults] = useState<CustomerBatchResultItem[]>([]);
  const [creatingManualLead, setCreatingManualLead] = useState(false);
  const [deletingLeadId, setDeletingLeadId] = useState("");
  const [selectedLeadId, setSelectedLeadId] = useState("");
  const [leadDetail, setLeadDetail] = useState<LeadDetail | null>(null);
  const [loadingLeadDetail, setLoadingLeadDetail] = useState(false);
  const [savingLeadDetail, setSavingLeadDetail] = useState(false);
  const [addingContact, setAddingContact] = useState(false);
  const [discoveringContacts, setDiscoveringContacts] = useState(false);
  const [deletingContactId, setDeletingContactId] = useState("");
  const [generatingDraftContactId, setGeneratingDraftContactId] = useState("");
  const [addingFollowUp, setAddingFollowUp] = useState(false);
  const [addingTask, setAddingTask] = useState(false);
  const [completingTaskId, setCompletingTaskId] = useState("");
  const [addingQuoteDraft, setAddingQuoteDraft] = useState(false);
  const [savingQuoteDraftId, setSavingQuoteDraftId] = useState("");
  const [sendingQuoteDraftId, setSendingQuoteDraftId] = useState("");
  const [verifyingContactId, setVerifyingContactId] = useState("");
  const [followUps, setFollowUps] = useState<FollowUpRecord[]>([]);
  const [loadingFollowUps, setLoadingFollowUps] = useState(false);
  const [followUpTasks, setFollowUpTasks] = useState<FollowUpTask[]>([]);
  const [loadingFollowUpTasks, setLoadingFollowUpTasks] = useState(false);
  const [emailDrafts, setEmailDrafts] = useState<EmailDraft[]>([]);
  const [loadingEmailDrafts, setLoadingEmailDrafts] = useState(false);
  const [emailDeliveryStatus, setEmailDeliveryStatus] = useState<EmailDeliveryStatus | null>(null);
  const [customerDevelopmentConnectors, setCustomerDevelopmentConnectors] = useState<ConnectorStatus[]>([]);
  const [loadingCustomerDevelopmentConnectors, setLoadingCustomerDevelopmentConnectors] = useState(false);
  const [searchSources, setSearchSources] = useState<SearchSource[]>([]);
  const [loadingSearchSources, setLoadingSearchSources] = useState(false);
  const [apiStatusError, setApiStatusError] = useState("");
  const [updatingSearchSourceId, setUpdatingSearchSourceId] = useState("");
  const [websiteInquiries, setWebsiteInquiries] = useState<WebsiteInquiry[]>([]);
  const [loadingWebsiteInquiries, setLoadingWebsiteInquiries] = useState(false);
  const [inquiryStatusFilter, setInquiryStatusFilter] = useState<WebsiteInquiryStatus | "all">("new");
  const [convertingInquiryId, setConvertingInquiryId] = useState("");
  const [selectedDraftId, setSelectedDraftId] = useState("");
  const [savingEmailDraft, setSavingEmailDraft] = useState(false);
  const [savingDraftRecipient, setSavingDraftRecipient] = useState(false);
  const [verifyingDraftRecipient, setVerifyingDraftRecipient] = useState(false);
  const [reviewingEmailDraft, setReviewingEmailDraft] = useState(false);
  const [runMessage, setRunMessage] = useState("请创建或选择产品线后开始搜索");
  const [priorityOnly, setPriorityOnly] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [knowledgeDocuments, setKnowledgeDocuments] = useState<KnowledgeDocument[]>([]);
  const [loadingKnowledgeDocuments, setLoadingKnowledgeDocuments] = useState(false);
  const [uploadingKnowledgeDocument, setUploadingKnowledgeDocument] = useState(false);
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
  const salesFunnel = useMemo(
    () => buildSalesFunnel(leads, emailDrafts, followUpTasks, websiteInquiries),
    [leads, emailDrafts, followUpTasks, websiteInquiries]
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
          setExcludedKeywords((items[0].excluded_keywords ?? []).join(", "));
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
    setLoadingFollowUpTasks(true);
    listFollowUpTasks(currentSession, "open")
      .then((items) => setFollowUpTasks(items))
      .catch((caught: unknown) => handleApiFailure(caught, "无法加载跟进任务"))
      .finally(() => setLoadingFollowUpTasks(false));
    setLoadingEmailDrafts(true);
    listEmailDrafts(currentSession)
      .then((items) => {
        setEmailDrafts(items);
        if (items.length > 0) setSelectedDraftId(items[0].id);
      })
      .catch((caught: unknown) => handleApiFailure(caught, "无法加载邮件审批队列"))
      .finally(() => setLoadingEmailDrafts(false));
    getEmailDeliveryStatus(currentSession)
      .then((status) => setEmailDeliveryStatus(status))
      .catch((caught: unknown) => handleApiFailure(caught, "无法加载发件邮箱状态"));
    setLoadingCustomerDevelopmentConnectors(true);
    getCustomerDevelopmentConnectors(currentSession)
      .then((status) => setCustomerDevelopmentConnectors(status.connectors))
      .catch((caught: unknown) => {
        handleApiFailure(caught, "无法加载客户开发 API 状态");
        setApiStatusError("后端 API 未连接，无法读取接口状态。请确认 8000 端口服务已启动。");
      })
      .finally(() => setLoadingCustomerDevelopmentConnectors(false));
    setLoadingSearchSources(true);
    listSearchSources(currentSession)
      .then((response) => setSearchSources(response.sources))
      .catch((caught: unknown) => {
        handleApiFailure(caught, "无法加载客户搜索来源");
        setApiStatusError("后端 API 未连接，无法读取网站接口目录。请确认 8000 端口服务已启动。");
      })
      .finally(() => setLoadingSearchSources(false));
    setLoadingWebsiteInquiries(true);
    listWebsiteInquiries(currentSession, "new")
      .then((items) => setWebsiteInquiries(items))
      .catch((caught: unknown) => handleApiFailure(caught, "无法加载独立站询盘"))
      .finally(() => setLoadingWebsiteInquiries(false));
    setLoadingKnowledgeDocuments(true);
    listKnowledgeDocuments(currentSession)
      .then((items) => setKnowledgeDocuments(items))
      .catch((caught: unknown) => handleApiFailure(caught, "无法加载知识库文档"))
      .finally(() => setLoadingKnowledgeDocuments(false));
  }, []);

  function handleApiFailure(caught: unknown, fallback: string) {
    if (caught instanceof ApiError && caught.status === 401) {
      clearSession();
      window.location.assign("/login");
      return;
    }
    setError(caught instanceof Error ? caught.message : fallback);
  }

  async function refreshApiStatus() {
    if (!session) return;
    setApiStatusError("");
    setLoadingCustomerDevelopmentConnectors(true);
    setLoadingSearchSources(true);
    const [connectorResult, sourceResult] = await Promise.allSettled([
      getCustomerDevelopmentConnectors(session),
      listSearchSources(session),
    ]);
    if (connectorResult.status === "fulfilled") {
      setCustomerDevelopmentConnectors(connectorResult.value.connectors);
    }
    if (sourceResult.status === "fulfilled") {
      setSearchSources(sourceResult.value.sources);
    }
    if (connectorResult.status === "rejected" || sourceResult.status === "rejected") {
      setApiStatusError("部分接口状态加载失败。请确认后端 API 的 8000 端口可访问，然后重新检查。");
    }
    setLoadingCustomerDevelopmentConnectors(false);
    setLoadingSearchSources(false);
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

  async function refreshFollowUpTasks() {
    if (!session) return;
    setLoadingFollowUpTasks(true);
    try {
      const items = await listFollowUpTasks(session, "open");
      setFollowUpTasks(items);
    } catch (caught) {
      handleApiFailure(caught, "无法刷新跟进任务");
    } finally {
      setLoadingFollowUpTasks(false);
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

  async function refreshKnowledgeDocuments() {
    if (!session) return;
    setLoadingKnowledgeDocuments(true);
    try {
      const items = await listKnowledgeDocuments(session);
      setKnowledgeDocuments(items);
    } catch (caught) {
      handleApiFailure(caught, "无法刷新知识库文档");
    } finally {
      setLoadingKnowledgeDocuments(false);
    }
  }

  async function uploadKnowledgeDocumentFromForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    const form = new FormData(event.currentTarget);
    const file = form.get("file");
    if (!(file instanceof File)) return;
    const productLineId = String(form.get("product_line_id") ?? "").trim();
    setUploadingKnowledgeDocument(true);
    setError("");
    try {
      const created = await uploadKnowledgeDocument(session, file, productLineId || undefined);
      setKnowledgeDocuments((current) => [created, ...current]);
      event.currentTarget.reset();
    } catch (caught) {
      handleApiFailure(caught, "无法上传知识库文档");
    } finally {
      setUploadingKnowledgeDocument(false);
    }
  }

  async function toggleSearchSource(sourceId: string, enabled: boolean) {
    if (!session) return;
    setUpdatingSearchSourceId(sourceId);
    setError("");
    try {
      const updated = await updateSearchSource(session, sourceId, enabled);
      setSearchSources((current) => current.map((source) => (source.source_id === updated.source_id ? updated : source)));
    } catch (caught) {
      handleApiFailure(caught, "无法更新搜索来源");
    } finally {
      setUpdatingSearchSourceId("");
    }
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
    setExcludedKeywords((productLine?.excluded_keywords ?? []).join(", "));
    setResolvedLocation(null);
    setLocationSubdivisions([]);
    setAllowRepeatLocation(false);
  }

  function changeTargetMarket(value: string) {
    setTargetMarket(value);
    setResolvedLocation(null);
    setLocationSubdivisions([]);
    setAllowRepeatLocation(false);
  }

  async function resolveLocation(query = targetMarket) {
    if (!session || !query.trim()) return;
    setResolvingLocation(true);
    setError("");
    try {
      const result = await resolveAdministrativeLocation(session, query.trim(), selectedProductLineId);
      setResolvedLocation(result.area);
      setLocationSubdivisions(result.subdivisions);
      setTargetMarket(result.area.search_label);
      setAllowRepeatLocation(false);
      setRunMessage(
        result.subdivisions.length > 0
          ? `已识别 ${result.area.name}，请选择下级行政区后搜索`
          : `已识别 ${result.area.name}，可以开始搜索`
      );
    } catch (caught) {
      handleApiFailure(caught, "无法识别行政区");
      setRunMessage("行政区识别失败");
    } finally {
      setResolvingLocation(false);
    }
  }

  function selectAdministrativeArea(area: AdministrativeArea) {
    setResolvedLocation(area);
    setLocationSubdivisions([]);
    setTargetMarket(area.search_label);
    setAllowRepeatLocation(false);
    void resolveLocation(area.search_label);
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
        excluded_keywords: parseCsv(form.get("excluded_keywords")),
      });
      setProductLines((current) => [...current, created]);
      setSelectedProductLineId(created.id);
      setBuyerProfile(created.buyer_profiles[0] ?? "");
      setExcludedKeywords((created.excluded_keywords ?? []).join(", "));
      setRunMessage("已准备好进行定向客户搜索");
      event.currentTarget.reset();
    } catch (caught) {
      handleApiFailure(caught, "无法创建产品线");
    } finally {
      setCreatingProductLine(false);
    }
  }

  async function deleteProductLineRecord(productLineId: string) {
    if (!session) return;
    const productLine = productLines.find((item) => item.id === productLineId);
    if (!productLine) return;
    const confirmed = window.confirm(
      `确认删除产品线“${productLine.name}”？该产品线下的供应商和产品条目会一起删除。已关联客户的产品线不能直接删除。`
    );
    if (!confirmed) return;

    setDeletingProductLineId(productLineId);
    setError("");
    try {
      await deleteProductLine(session, productLineId);
      const remaining = productLines.filter((item) => item.id !== productLineId);
      setProductLines(remaining);
      if (selectedProductLineId === productLineId) {
        const nextProductLine = remaining[0];
        setSelectedProductLineId(nextProductLine?.id ?? "");
        setBuyerProfile(nextProductLine?.buyer_profiles[0] ?? "");
        setExcludedKeywords((nextProductLine?.excluded_keywords ?? []).join(", "));
        setRunMessage(nextProductLine ? "已切换到剩余产品线" : "请创建产品线后开始搜索");
      }
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        setError("该产品线已关联客户，不能直接删除。请先删除相关客户线索。");
      } else {
        handleApiFailure(caught, "无法删除产品线");
      }
    } finally {
      setDeletingProductLineId("");
    }
  }

  async function createProductItemFromForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    const form = new FormData(event.currentTarget);
    const productLineId = String(form.get("product_line_id") ?? "");
    if (!productLineId) return;
    setCreatingProductItem(true);
    setError("");
    try {
      const created = await createProductItem(session, productLineId, {
        name: String(form.get("name") ?? "").trim(),
        sku: String(form.get("sku") ?? "").trim(),
        summary: String(form.get("summary") ?? "").trim(),
        specs: parseCsv(form.get("specs")),
        image_url: String(form.get("image_url") ?? "").trim(),
        is_published: form.get("is_published") === "on",
      });
      setProductLines((current) =>
        current.map((productLine) =>
          productLine.id === productLineId
            ? { ...productLine, product_items: [...(productLine.product_items ?? []), created] }
            : productLine
        )
      );
      event.currentTarget.reset();
    } catch (caught) {
      handleApiFailure(caught, "无法保存产品条目");
    } finally {
      setCreatingProductItem(false);
    }
  }

  async function deleteCatalogProductItem(productItemId: string) {
    if (!session) return;
    setDeletingProductItemId(productItemId);
    setError("");
    try {
      await deleteProductItem(session, productItemId);
      setProductLines((current) =>
        current.map((productLine) => ({
          ...productLine,
          product_items: (productLine.product_items ?? []).filter((productItem) => productItem.id !== productItemId),
        }))
      );
    } catch (caught) {
      handleApiFailure(caught, "无法删除产品条目");
    } finally {
      setDeletingProductItemId("");
    }
  }

  async function runDiscovery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !selectedProductLineId) return;
    setRunning(true);
    setError("");
    setLastDiscoveryRun(null);
    setRunMessage("客户搜索运行中");
    try {
      const run = await startDiscovery(session, {
        product_line_id: selectedProductLineId,
        target_market: resolvedLocation?.search_label ?? targetMarket.trim(),
        location_scope_id: resolvedLocation?.scope_id,
        location_country_code: resolvedLocation?.country_code,
        allow_repeat_location: allowRepeatLocation,
        buyer_profile: buyerProfile || undefined,
        excluded_keywords: parseCsv(excludedKeywords),
        limit: searchLimit,
      });
      const nextLeads = await listLeads(session);
      setLastDiscoveryRun(run);
      setLeads(nextLeads);
      const runLeadIds = run.lead_ids ?? nextLeads
        .filter((lead) => lead.workflow_run_id === run.workflow_run_id)
        .map((lead) => lead.id);
      setLatestSearchLeadIds(runLeadIds);
      setSelectedLeadIds([]);
      const failedQueryCount = run.failed_query_count ?? 0;
      const failedSummary = failedQueryCount > 0 ? ` / ${failedQueryCount} 组查询失败` : "";
      setRunMessage(
        `${resolvedLocation?.name ?? targetMarket} 搜索完成 / ${run.query_count ?? 1} 组查询获得 ${run.candidate_count ?? runLeadIds.length} 条候选` +
        ` / 去重 ${run.duplicate_count ?? 0} 条 / 过滤 ${run.filtered_count ?? 0} 条` +
        ` / 保存 ${runLeadIds.length} 家客户${failedSummary}`
      );
      if (resolvedLocation) {
        setResolvedLocation({
          ...resolvedLocation,
          search_count: resolvedLocation.search_count + 1,
          last_searched_at: new Date().toISOString(),
        });
        setAllowRepeatLocation(false);
      }
      requestAnimationFrame(() => {
        document.getElementById("lead-results-title")?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    } catch (caught) {
      handleApiFailure(caught, "客户搜索失败");
      setRunMessage("客户搜索失败");
    } finally {
      setRunning(false);
    }
  }

  async function runDailyContactDiscovery(requestedLeadIds?: string[]) {
    if (!session) return;
    const leadIds = requestedLeadIds ?? (
      selectedLeadIds.length > 0
        ? selectedLeadIds
        : latestSearchLeadIds?.length
          ? latestSearchLeadIds
          : sortedLeads.map((lead) => lead.id)
    );
    if (leadIds.length === 0) {
      setRunMessage("当前没有可提取联系方式的客户");
      return;
    }
    setRunningDailyContactDiscovery(true);
    setContactDiscoveryItems([]);
    setContactDiscoveryProgress({ completed: 0, total: leadIds.length });
    setError("");
    try {
      let completed = 0;
      let collected: BatchContactDiscoveryItem[] = [];
      for (let index = 0; index < leadIds.length; index += 5) {
        const batch = leadIds.slice(index, index + 5);
        const result = await discoverContactBatch(session, batch);
        completed += batch.length;
        collected = [...collected, ...result.items];
        setContactDiscoveryItems(collected);
        setContactDiscoveryProgress({ completed, total: leadIds.length });
        const resultById = new Map(result.items.map((item) => [item.lead_id, item]));
        setLeads((current) => current.map((lead) => {
          const item = resultById.get(lead.id);
          return item ? {
            ...lead,
            contact_discovery_status: item.status,
            contact_discovery_message: item.message,
            contact_discovered_at: new Date().toISOString(),
            contact_email_count: item.email_count,
            contact_phone_count: item.phone_count,
            contact_social_count: item.social_count,
          } : lead;
        }));
      }
      const emailCount = collected.filter((item) => item.status === "has_email").length;
      const manualCount = collected.filter((item) => item.status === "has_contact").length;
      const reviewCount = collected.filter((item) => item.status === "needs_review").length;
      setRunMessage(
        `联系方式提取完成 / ${leadIds.length} 家客户 / 有邮箱 ${emailCount} 家 / 有人工联系方式 ${manualCount} 家 / 待复查 ${reviewCount} 家`
      );
      const refreshedLeads = await listLeads(session);
      setLeads(refreshedLeads);
      await refreshFollowUps();
    } catch (caught) {
      handleApiFailure(caught, "无法批量提取客户联系方式");
      setRunMessage("联系方式批量提取中断，已完成的客户结果已保留，可重新执行待复查客户");
    } finally {
      setRunningDailyContactDiscovery(false);
    }
  }

  function retryContactDiscovery() {
    const retryLeadIds = contactDiscoveryItems
      .filter((item) => item.status === "needs_review")
      .map((item) => item.lead_id);
    void runDailyContactDiscovery(retryLeadIds);
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
    const lead = leads.find((item) => item.id === leadId);
    if (!window.confirm(`确认删除“${lead?.company_name ?? "该客户"}”吗？相关联系人和跟进记录也会删除。`)) {
      return;
    }
    setDeletingLeadId(leadId);
    setError("");
    try {
      await deleteLead(session, leadId);
      setLeads((current) => current.filter((lead) => lead.id !== leadId));
      setLatestSearchLeadIds((current) => current?.filter((currentId) => currentId !== leadId) ?? null);
      setSelectedLeadIds((current) => current.filter((selectedId) => selectedId !== leadId));
      setSelectedCrmLeadIds((current) => current.filter((selectedId) => selectedId !== leadId));
      setEmailDrafts((current) => current.filter((draft) => draft.lead_id !== leadId));
      setFollowUpTasks((current) => current.filter((task) => task.lead_id !== leadId));
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

  function selectCrmLeadForBatch(leadId: string, selected: boolean) {
    setSelectedCrmLeadIds((current) => {
      if (selected) return current.includes(leadId) ? current : [...current, leadId];
      return current.filter((selectedId) => selectedId !== leadId);
    });
  }

  function selectAllVisibleCrmLeadsForBatch(leadIds: string[], selected: boolean) {
    setSelectedCrmLeadIds((current) => {
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

  async function runSelectedCustomerBatch() {
    if (!session || selectedCrmLeadIds.length === 0) return;
    setRunningCustomerBatch(true);
    setError("");
    setCustomerBatchResults([]);
    let discoveredCount = 0;
    let verifiedCount = 0;
    let draftCount = 0;
    let skippedCount = 0;
    const resultItems: CustomerBatchResultItem[] = [];
    try {
      let draftSnapshot = await listEmailDrafts(session);
      setEmailDrafts(draftSnapshot);
      for (const [index, leadId] of selectedCrmLeadIds.entries()) {
        const lead = leads.find((item) => item.id === leadId);
        const companyName = lead?.company_name ?? leadId;
        setCustomerBatchMessage(`正在处理 ${index + 1}/${selectedCrmLeadIds.length}：${companyName}`);
        try {
          let detail = await getLeadDetail(session, leadId);
          if (!detail.contacts.some((contact) => contact.email.trim())) {
            try {
              const discovered = await discoverContacts(session, leadId, 10);
              discoveredCount += discovered.length;
            } catch (caught) {
              skippedCount += 1;
              resultItems.push({
                leadId,
                companyName,
                status: "error",
                message: `${batchFailureMessage(caught)}，未生成草稿`,
              });
              setCustomerBatchResults([...resultItems]);
              continue;
            }
            detail = await getLeadDetail(session, leadId);
          }
          let verificationUnavailable = false;
          for (const contact of detail.contacts.filter((item) => item.email.trim() && !item.email_verification_status)) {
            try {
              await verifyContactEmail(session, leadId, contact.id);
              verifiedCount += 1;
            } catch {
              verificationUnavailable = true;
            }
          }
          detail = await getLeadDetail(session, leadId);
          const contact = chooseBatchContact(detail.contacts, draftSnapshot);
          if (!contact) {
            skippedCount += 1;
            const hasEmail = detail.contacts.some((item) => item.email.trim());
            const hasBlockedEmail = detail.contacts.some((item) => item.email.trim() && contactEmailIsBlocked(item));
            const hasManualChannel = detail.contacts.some(contactHasManualChannel);
            const hasExistingDraft = draftSnapshot.some(
              (draft) => draft.lead_id === leadId && draft.status !== "rejected"
            );
            const message = hasExistingDraft
              ? "已有未驳回的开发信草稿，无需重复生成"
              : hasBlockedEmail
                ? "邮箱验证结果不适合发送，请打开详情检查"
                : hasEmail
                  ? "邮箱暂不可用于批量草稿，请打开详情检查"
                  : hasManualChannel
                    ? "已找到电话或社交媒体，但没有公开邮箱，请打开详情人工联系"
                    : "官网未找到公开邮箱或其他联系方式";
            resultItems.push({ leadId, companyName, status: "warning", message });
            setCustomerBatchResults([...resultItems]);
            continue;
          }
          const draft = await createEmailDraft(session, leadId, contact.id);
          draftCount += 1;
          draftSnapshot = [draft, ...draftSnapshot];
          setEmailDrafts(draftSnapshot);
          const isUnverified = !normalizeContactEmailStatus(contact);
          resultItems.push({
            leadId,
            companyName,
            status: isUnverified || verificationUnavailable ? "warning" : "success",
            message: isUnverified || verificationUnavailable
              ? `已生成待审核草稿：${contact.email}（邮箱未验证，发送前请人工确认）`
              : `已生成待审核草稿：${contact.email}`,
          });
          setCustomerBatchResults([...resultItems]);
        } catch (caught) {
          skippedCount += 1;
          resultItems.push({
            leadId,
            companyName,
            status: "error",
            message: `${batchFailureMessage(caught)}，未生成草稿`,
          });
          setCustomerBatchResults([...resultItems]);
        }
      }
      const refreshedLeads = await listLeads(session);
      setLeads(refreshedLeads);
      await refreshFollowUps();
      await refreshEmailDrafts(draftSnapshot[0]?.id);
      setSelectedCrmLeadIds([]);
      if (draftCount > 0) setReviewOpen(true);
      setCustomerBatchMessage(
        `批量完成：新增或更新联系方式 ${discoveredCount} 个，验证邮箱 ${verifiedCount} 个，生成草稿 ${draftCount} 封，跳过 ${skippedCount} 项`
      );
    } catch (caught) {
      handleApiFailure(caught, "批量开发客户失败");
      setCustomerBatchMessage("批量开发中断，请检查 API 配置或客户数据后重试");
    } finally {
      setRunningCustomerBatch(false);
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
        social_profiles: [
          { platform: "Facebook", url: String(form.get("facebook_url") ?? "").trim() },
          { platform: "Instagram", url: String(form.get("instagram_url") ?? "").trim() },
          { platform: "TikTok", url: String(form.get("tiktok_url") ?? "").trim() },
          { platform: "其他平台", url: String(form.get("other_social_url") ?? "").trim() },
        ].filter((profile) => profile.url),
        source_url: String(form.get("source_url") ?? "").trim(),
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

  async function discoverContactRecords() {
    if (!session || !leadDetail) return;
    setDiscoveringContacts(true);
    setError("");
    try {
      await discoverContacts(session, leadDetail.id, 10);
      const refreshed = await getLeadDetail(session, leadDetail.id);
      setLeadDetail(refreshed);
      setLeads((current) =>
        current.map((lead) =>
          lead.id === refreshed.id ? { ...lead, status: refreshed.status } : lead
        )
      );
      await refreshFollowUps();
    } catch (caught) {
      handleApiFailure(caught, "无法补充联系人");
    } finally {
      setDiscoveringContacts(false);
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

  async function verifyContactEmailRecord(contactId: string) {
    if (!session || !leadDetail) return;
    setVerifyingContactId(contactId);
    setError("");
    try {
      await verifyContactEmail(session, leadDetail.id, contactId);
      const refreshed = await getLeadDetail(session, leadDetail.id);
      setLeadDetail(refreshed);
      await refreshFollowUps();
    } catch (caught) {
      handleApiFailure(caught, "无法验证联系人邮箱");
    } finally {
      setVerifyingContactId("");
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

  async function addFollowUpTaskRecord(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !leadDetail) return;
    const form = new FormData(event.currentTarget);
    const dueAt = String(form.get("due_at") ?? "");
    setAddingTask(true);
    setError("");
    try {
      await createFollowUpTask(session, leadDetail.id, {
        title: String(form.get("title") ?? "").trim(),
        task_type: String(form.get("task_type") ?? "follow_up"),
        quote_status: String(form.get("quote_status") ?? ""),
        due_at: dueAt ? new Date(dueAt).toISOString() : null,
      });
      const refreshed = await getLeadDetail(session, leadDetail.id);
      setLeadDetail(refreshed);
      setLeads((current) => current.map((lead) => (lead.id === refreshed.id ? refreshed : lead)));
      await refreshFollowUpTasks();
      event.currentTarget.reset();
    } catch (caught) {
      handleApiFailure(caught, "无法创建跟进任务");
    } finally {
      setAddingTask(false);
    }
  }

  async function completeTask(taskId: string) {
    if (!session) return;
    setCompletingTaskId(taskId);
    setError("");
    try {
      const completed = await completeFollowUpTask(session, taskId);
      setFollowUpTasks((current) => current.filter((task) => task.id !== taskId));
      if (leadDetail?.id === completed.lead_id) {
        const refreshed = await getLeadDetail(session, completed.lead_id);
        setLeadDetail(refreshed);
      }
      await refreshFollowUps();
    } catch (caught) {
      handleApiFailure(caught, "无法完成跟进任务");
    } finally {
      setCompletingTaskId("");
    }
  }

  async function addQuoteDraftRecord(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !leadDetail) return;
    const form = new FormData(event.currentTarget);
    setAddingQuoteDraft(true);
    setError("");
    try {
      await createQuoteDraft(session, leadDetail.id, quoteDraftPayloadFromForm(form));
      const refreshed = await getLeadDetail(session, leadDetail.id);
      setLeadDetail(refreshed);
      setLeads((current) => current.map((lead) => (lead.id === refreshed.id ? refreshed : lead)));
      event.currentTarget.reset();
    } catch (caught) {
      handleApiFailure(caught, "无法创建报价草稿");
    } finally {
      setAddingQuoteDraft(false);
    }
  }

  async function saveQuoteDraftRecord(draftId: string, event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !leadDetail) return;
    const form = new FormData(event.currentTarget);
    setSavingQuoteDraftId(draftId);
    setError("");
    try {
      await updateQuoteDraft(session, draftId, quoteDraftPayloadFromForm(form));
      const refreshed = await getLeadDetail(session, leadDetail.id);
      setLeadDetail(refreshed);
    } catch (caught) {
      handleApiFailure(caught, "无法保存报价草稿");
    } finally {
      setSavingQuoteDraftId("");
    }
  }

  async function markSelectedQuoteDraftSent(draftId: string) {
    if (!session || !leadDetail) return;
    setSendingQuoteDraftId(draftId);
    setError("");
    try {
      const updated = await markQuoteDraftSent(session, draftId);
      setLeads((current) =>
        current.map((lead) =>
          lead.id === updated.lead_id ? { ...lead, status: "quoting" } : lead
        )
      );
      const refreshed = await getLeadDetail(session, updated.lead_id);
      setLeadDetail(refreshed);
      await refreshFollowUps();
    } catch (caught) {
      handleApiFailure(caught, "无法标记报价已发送");
    } finally {
      setSendingQuoteDraftId("");
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

  async function saveDraftRecipient(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !selectedEmailDraft) return;
    const form = new FormData(event.currentTarget);
    const email = String(form.get("contact_email") ?? "").trim();
    setSavingDraftRecipient(true);
    setError("");
    try {
      const updated = await updateDraftContactEmail(session, selectedEmailDraft.id, email);
      setEmailDrafts((current) => current.map((draft) => (draft.id === updated.id ? updated : draft)));
      setSelectedDraftId(updated.id);
      if (leadDetail?.id === updated.lead_id) {
        setLeadDetail(await getLeadDetail(session, updated.lead_id));
      }
    } catch (caught) {
      handleApiFailure(caught, "无法更新客户邮箱");
    } finally {
      setSavingDraftRecipient(false);
    }
  }

  async function verifyDraftRecipient() {
    if (!session || !selectedEmailDraft) return;
    setVerifyingDraftRecipient(true);
    setError("");
    try {
      await verifyContactEmail(session, selectedEmailDraft.lead_id, selectedEmailDraft.contact_id);
      await refreshEmailDrafts(selectedEmailDraft.id);
      if (leadDetail?.id === selectedEmailDraft.lead_id) {
        setLeadDetail(await getLeadDetail(session, selectedEmailDraft.lead_id));
      }
    } catch (caught) {
      handleApiFailure(caught, "无法验证客户邮箱");
    } finally {
      setVerifyingDraftRecipient(false);
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
      handleApiFailure(caught, "无法发送开发信");
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
          {activeNav === API_STATUS_NAV ? (
            <ApiStatusPage
              connectors={customerDevelopmentConnectors}
              sources={searchSources}
              loadingConnectors={loadingCustomerDevelopmentConnectors}
              loadingSources={loadingSearchSources}
              error={apiStatusError}
              updatingSourceId={updatingSearchSourceId}
              onSourceToggle={toggleSearchSource}
              onRefresh={() => void refreshApiStatus()}
            />
          ) : activeNav === KNOWLEDGE_NAV ? (
            <KnowledgeBasePanel
              documents={knowledgeDocuments}
              productLines={productLines}
              isAdmin={session.organization_role === "admin"}
              loading={loadingKnowledgeDocuments}
              uploading={uploadingKnowledgeDocument}
              onCreate={uploadKnowledgeDocumentFromForm}
              onRefresh={() => void refreshKnowledgeDocuments()}
            />
          ) : (
          <>
          <section className="pageHeading">
            <div><p className="sectionLabel">客户开发</p><h1>外贸客户开发工作台</h1><p>配置产品线，启动基于公开证据的客户搜索，并把合格线索推进到 CRM 和开发信流程。</p></div>
            <button className="outlineButton exportButton" type="button" onClick={exportActivityCsv}>
              导出活动
            </button>
          </section>
          {error && <div className="errorBanner" role="alert">{error}</div>}
          <section className="metricGrid" aria-label="销售指标">{dashboardMetrics.map((metric) => <MetricTile key={metric.label} {...metric} />)}</section>
          <DiscoveryWorkbench
            productLines={productLines}
            selectedProductLineId={selectedProductLineId}
            targetMarket={targetMarket}
            resolvedLocation={resolvedLocation}
            locationSubdivisions={locationSubdivisions}
            resolvingLocation={resolvingLocation}
            allowRepeatLocation={allowRepeatLocation}
            buyerProfile={buyerProfile}
            excludedKeywords={excludedKeywords}
            searchLimit={searchLimit}
            running={running}
            runMessage={selectedProductLine ? runMessage : "请先创建第一个产品线，再开始搜索"}
            sources={searchSources}
            loadingSources={loadingSearchSources}
            updatingSourceId={updatingSearchSourceId}
            leads={latestSearchLeadIds === null
              ? sortedLeads
              : sortedLeads.filter((lead) => latestSearchLeadIds.includes(lead.id))}
            showingLatestSearch={latestSearchLeadIds !== null}
            deletingLeadId={deletingLeadId}
            priorityOnly={priorityOnly}
            selectedLeadIds={selectedLeadIds}
            savingToCrm={savingToCrm}
            runningDailyContactDiscovery={runningDailyContactDiscovery}
            contactDiscoveryProgress={contactDiscoveryProgress}
            contactDiscoveryItems={contactDiscoveryItems}
            discoveryRun={lastDiscoveryRun}
            onProductLineChange={selectProductLine}
            onTargetMarketChange={changeTargetMarket}
            onResolveLocation={() => void resolveLocation()}
            onSelectLocation={selectAdministrativeArea}
            onAllowRepeatLocationChange={setAllowRepeatLocation}
            onBuyerProfileChange={setBuyerProfile}
            onExcludedKeywordsChange={setExcludedKeywords}
            onSearchLimitChange={setSearchLimit}
            onSourceToggle={toggleSearchSource}
            onRun={runDiscovery}
            onPriorityToggle={() => setPriorityOnly((current) => !current)}
            onShowAllLeads={() => setLatestSearchLeadIds(null)}
            onDelete={deleteCustomerLead}
            onSelectLead={selectLeadForCrm}
            onSelectAllVisible={selectAllVisibleLeadsForCrm}
            onSaveToCrm={saveSelectedLeadsToCrm}
            onOpenDetail={openLeadDetail}
            onDiscoverDailyContacts={() => void runDailyContactDiscovery()}
            onRetryContactDiscovery={retryContactDiscovery}
          />
          <SalesFunnelPanel {...salesFunnel} />
          <CRMCustomerManager
            leads={sortedLeads}
            productLines={productLines}
            selectedProductLineId={selectedProductLineId}
            selectedCrmLeadIds={selectedCrmLeadIds}
            creating={creatingManualLead}
            deletingLeadId={deletingLeadId}
            runningBatch={runningCustomerBatch}
            batchMessage={customerBatchMessage}
            batchResults={customerBatchResults}
            onCreate={createManualLeadFromForm}
            onDelete={deleteCustomerLead}
            onOpenDetail={openLeadDetail}
            onSelectLead={selectCrmLeadForBatch}
            onSelectAllVisible={selectAllVisibleCrmLeadsForBatch}
            onRunBatch={runSelectedCustomerBatch}
          />
          <ProductLineSetup
            productLines={productLines}
            loading={loadingProductLines}
            creating={creatingProductLine}
            deletingProductLineId={deletingProductLineId}
            onCreate={createProductLineFromForm}
            onDelete={deleteProductLineRecord}
          />
          <ProductCatalogManager
            productLines={productLines}
            selectedProductLineId={selectedProductLineId}
            organizationId={session.organization_id}
            creating={creatingProductItem}
            deletingProductItemId={deletingProductItemId}
            onCreate={createProductItemFromForm}
            onDelete={deleteCatalogProductItem}
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
              emailDeliveryStatus={emailDeliveryStatus}
              onOpen={() => openEmailDraftQueue()}
              onOpenDraft={openEmailDraftQueue}
            />
            <InboxPanel
              records={followUps}
              loading={loadingFollowUps}
              onRefresh={refreshFollowUps}
            />
            <FollowUpTaskBoard
              tasks={followUpTasks}
              loading={loadingFollowUpTasks}
              completingTaskId={completingTaskId}
              onRefresh={refreshFollowUpTasks}
              onComplete={completeTask}
            />
            <FollowUpTimeline
              records={followUps}
              loading={loadingFollowUps}
              onRefresh={refreshFollowUps}
            />
          </div>
          </>
          )}
        </div>
      </section>
      <CustomerDetailDrawer
        detail={leadDetail}
        loading={loadingLeadDetail}
        saving={savingLeadDetail}
        addingContact={addingContact}
        addingFollowUp={addingFollowUp}
        addingTask={addingTask}
        addingQuoteDraft={addingQuoteDraft}
        discoveringContacts={discoveringContacts}
        deletingContactId={deletingContactId}
        verifyingContactId={verifyingContactId}
        generatingDraftContactId={generatingDraftContactId}
        completingTaskId={completingTaskId}
        savingQuoteDraftId={savingQuoteDraftId}
        sendingQuoteDraftId={sendingQuoteDraftId}
        onClose={closeLeadDetail}
        onSave={saveLeadDetail}
        onAddContact={addContactRecord}
        onDiscoverContacts={discoverContactRecords}
        onDeleteContact={deleteContactRecord}
        onVerifyContactEmail={verifyContactEmailRecord}
        onCreateEmailDraft={createEmailDraftForContact}
        onAddFollowUp={addFollowUpRecord}
        onAddTask={addFollowUpTaskRecord}
        onCompleteTask={completeTask}
        onCreateQuoteDraft={addQuoteDraftRecord}
        onUpdateQuoteDraft={saveQuoteDraftRecord}
        onMarkQuoteDraftSent={markSelectedQuoteDraftSent}
      />
      <ReviewDrawer
        open={reviewOpen}
        draft={selectedEmailDraft}
        saving={savingEmailDraft}
        savingRecipient={savingDraftRecipient}
        verifyingRecipient={verifyingDraftRecipient}
        reviewing={reviewingEmailDraft}
        onClose={() => setReviewOpen(false)}
        onSave={saveEmailDraft}
        onSaveRecipient={saveDraftRecipient}
        onVerifyRecipient={verifyDraftRecipient}
        onApprove={approveEmailDraft}
        onMarkSent={markSelectedEmailDraftSent}
        onReject={rejectEmailDraft}
      />
    </main>
  );
}
