import { authHeaders, clearSession, type Session } from "./auth";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ProductLine = {
  id: string;
  name: string;
  description: string;
  product_keywords: string[];
  buyer_profiles: string[];
  target_regions: string[];
  excluded_keywords: string[];
  is_active: boolean;
  suppliers: string[];
  product_items: ProductItem[];
};

export type ProductItem = {
  id: string;
  product_line_id: string;
  name: string;
  sku: string;
  summary: string;
  specs: string[];
  image_url: string;
  is_published: boolean;
};

export type PublicProductItem = {
  id: string;
  name: string;
  sku: string;
  summary: string;
  specs: string[];
  image_url: string;
  inquiry_product_line_id: string;
  inquiry_product_item_id: string;
};

export type PublicProductLine = {
  id: string;
  name: string;
  description: string;
  product_keywords: string[];
  buyer_profiles: string[];
  target_regions: string[];
  product_items: PublicProductItem[];
};

export type PublicProductCatalog = {
  organization_id: string;
  product_lines: PublicProductLine[];
};

export type EmailDeliveryStatus = {
  provider: string;
  configured: boolean;
  from_email: string | null;
  from_name: string;
  missing: string[];
};

export type ConnectorStatus = {
  connector_id: string;
  label: string;
  provider: string;
  purpose: string;
  configured: boolean;
  missing: string[];
};

export type CustomerDevelopmentConnectors = {
  connectors: ConnectorStatus[];
};

export type SearchSource = {
  source_id: string;
  label: string;
  provider: string;
  category: string;
  purpose: string;
  base_url: string;
  enabled: boolean;
  configured: boolean;
  status: "ready" | "needs_config" | "planned";
  missing: string[];
};

export type SearchSourcesResponse = {
  sources: SearchSource[];
};

export type CreateProductLinePayload = {
  name: string;
  description: string;
  product_keywords: string[];
  buyer_profiles: string[];
  target_regions: string[];
  excluded_keywords: string[];
};

export type ProductItemPayload = {
  name: string;
  sku?: string;
  summary?: string;
  specs?: string[];
  image_url?: string;
  is_published?: boolean;
};

export type DiscoveryRun = {
  workflow_run_id: string;
  query: string;
  lead_count: number;
  lead_ids?: string[];
  filtered_count?: number;
  query_count?: number;
  queries?: string[];
  candidate_count?: number;
  duplicate_count?: number;
  overflow_count?: number;
  failed_query_count?: number;
  state: string;
};

export type AdministrativeArea = {
  scope_id: string;
  name: string;
  formatted: string;
  search_label: string;
  country_code: string;
  level: string;
  search_count: number;
  last_searched_at: string | null;
};

export type ResolvedLocation = {
  area: AdministrativeArea;
  subdivisions: AdministrativeArea[];
};

export type Lead = {
  id: string;
  workflow_run_id: string;
  product_line_id: string;
  company_name: string;
  website: string;
  target_market: string;
  buyer_profile: string | null;
  score: number;
  bucket: "priority_recommendation" | "needs_enrichment" | "not_qualified";
  status: LeadStatus;
  owner_user_id: string | null;
  notes: string;
  reasons: string[];
  missing_signals: string[];
  contact_discovery_status: "not_scanned" | "has_email" | "has_contact" | "no_contacts" | "needs_review";
  contact_discovery_message: string;
  contact_discovered_at: string | null;
  contact_email_count: number;
  contact_phone_count: number;
  contact_social_count: number;
  last_discovered_at: string;
  created_at: string;
  evidence: Array<{ source_url: string; source_excerpt: string; signal_name: string }>;
};

export type LeadStatus = "new" | "to_contact" | "contacted" | "interested" | "quoting" | "won" | "not_fit";

export type FollowUpRecord = {
  id: string;
  lead_id: string;
  actor_user_id: string | null;
  activity_type: string;
  content: string;
  next_follow_up_at: string | null;
  created_at: string;
  lead_company_name?: string;
  lead_status?: LeadStatus;
};

export type FollowUpTaskStatus = "open" | "done";

export type FollowUpTask = {
  id: string;
  lead_id: string;
  actor_user_id: string | null;
  title: string;
  task_type: string;
  quote_status: string;
  due_at: string | null;
  status: FollowUpTaskStatus;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  lead_company_name?: string;
  lead_status?: LeadStatus;
};

export type QuoteDraftStatus = "draft" | "sent";

export type QuoteLineItem = {
  item_name: string;
  quantity: number;
  unit_price: number;
  unit: string;
  notes: string;
};

export type QuoteDraft = {
  id: string;
  organization_id: string;
  lead_id: string;
  product_line_id: string;
  created_by_user_id: string | null;
  sent_by_user_id: string | null;
  status: QuoteDraftStatus;
  title: string;
  currency: string;
  incoterm: string;
  valid_until: string | null;
  line_items: QuoteLineItem[];
  notes: string;
  total_amount: number;
  created_at: string;
  updated_at: string;
  sent_at: string | null;
  lead_company_name: string;
};

export type ContactRecord = {
  id: string;
  lead_id: string;
  name: string;
  title: string;
  email: string;
  phone: string;
  linkedin_url: string;
  whatsapp: string;
  social_profiles: Array<{ platform: string; url: string }>;
  source_url: string;
  email_verification_provider: string;
  email_verification_status: string;
  email_verification_sub_status: string;
  email_verified_at: string | null;
  is_primary: boolean;
  created_at: string;
};

export type LeadDetail = Lead & {
  contacts: ContactRecord[];
  follow_ups: FollowUpRecord[];
  follow_up_tasks: FollowUpTask[];
  quote_drafts: QuoteDraft[];
};

export type DailyContactDiscoveryItem = {
  lead_id: string;
  company_name: string;
  website: string;
  status: "found" | "no_contacts" | "skipped" | "failed";
  contact_count: number;
  message: string;
};

export type DailyContactDiscoveryResult = {
  discovery_date: string;
  timezone: string;
  lead_count: number;
  processed_count: number;
  contacts_found: number;
  no_contacts_count: number;
  skipped_count: number;
  failed_count: number;
  items: DailyContactDiscoveryItem[];
};

export type BatchContactDiscoveryItem = {
  lead_id: string;
  company_name: string;
  website: string;
  status: Lead["contact_discovery_status"];
  contact_count: number;
  email_count: number;
  checked_email_count: number;
  phone_count: number;
  social_count: number;
  message: string;
};

export type BatchContactDiscoveryResult = {
  items: BatchContactDiscoveryItem[];
};

export type ManualLeadPayload = {
  product_line_id: string;
  company_name: string;
  website: string;
  target_market: string;
  buyer_profile?: string;
  notes: string;
};

export type LeadDetailPayload = {
  status: LeadStatus;
  notes: string;
  owner_user_id?: string | null;
};

export type FollowUpPayload = {
  activity_type: string;
  content: string;
  next_follow_up_at?: string | null;
};

export type FollowUpTaskPayload = {
  title: string;
  task_type?: string;
  quote_status?: string;
  due_at?: string | null;
};

export type QuoteDraftPayload = {
  title: string;
  currency?: string;
  incoterm?: string;
  valid_until?: string | null;
  line_items: QuoteLineItem[];
  notes?: string;
};

export type ContactPayload = {
  name: string;
  title?: string;
  email?: string;
  phone?: string;
  linkedin_url?: string;
  whatsapp?: string;
  social_profiles?: Array<{ platform: string; url: string }>;
  source_url?: string;
  is_primary?: boolean;
};

export type EmailDraftStatus = "pending_approval" | "ready_to_send" | "sent" | "rejected";

export type WebsiteInquiryStatus = "new" | "converted" | "dismissed";

export type WebsiteInquiry = {
  id: string;
  organization_id: string;
  product_line_id: string | null;
  product_item_id: string | null;
  lead_id: string | null;
  status: WebsiteInquiryStatus;
  product_item_name: string;
  company_name: string;
  contact_name: string;
  email: string;
  phone: string;
  website: string;
  target_market: string;
  message: string;
  source_url: string;
  created_at: string;
  converted_at: string | null;
};

export type WebsiteInquiryPayload = {
  product_line_id: string;
  product_item_id?: string;
  company_name: string;
  contact_name: string;
  email: string;
  phone?: string;
  website?: string;
  target_market?: string;
  message: string;
  source_url?: string;
};

export type WebsiteInquiryConversion = {
  inquiry: WebsiteInquiry;
  lead: LeadDetail;
};

export type EmailDraft = {
  id: string;
  organization_id: string;
  lead_id: string;
  contact_id: string;
  product_line_id: string;
  created_by_user_id: string | null;
  reviewed_by_user_id: string | null;
  sent_by_user_id: string | null;
  status: EmailDraftStatus;
  subject: string;
  body: string;
  provider_message_id: string;
  evidence_snapshot: Array<{ signal_name: string; source_excerpt: string; source_url: string }>;
  rejection_reason: string;
  created_at: string;
  updated_at: string;
  reviewed_at: string | null;
  sent_at: string | null;
  lead_company_name: string;
  contact_name: string;
  contact_email: string;
  current_contact_email: string;
  contact_email_verification_provider: string;
  contact_email_verification_status: string;
  contact_email_verification_sub_status: string;
  contact_email_verified_at: string | null;
  contact_source_url: string;
  send_blocked: boolean;
  send_risk_level: "safe" | "caution" | "warning" | "blocked";
  send_risk_message: string;
};

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function requestJson<T>(session: Session, path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    headers: {
      ...authHeaders(session),
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  const data: unknown = await response.json().catch(() => null);
  if (response.status === 401) clearSession();
  if (!response.ok) {
    const detail =
      typeof data === "object" &&
      data !== null &&
      "detail" in data &&
      typeof data.detail === "string"
        ? data.detail
        : "Request failed";
    throw new ApiError(detail, response.status);
  }
  return data as T;
}

export function listProductLines(session: Session) {
  return requestJson<ProductLine[]>(
    session,
    `/platform/organizations/${session.organization_id}/product-lines`
  );
}

export function createProductLine(session: Session, payload: CreateProductLinePayload) {
  return requestJson<ProductLine>(session, `/platform/organizations/${session.organization_id}/product-lines`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function deleteProductLine(session: Session, productLineId: string) {
  await requestJson<null>(
    session,
    `/platform/organizations/${session.organization_id}/product-lines/${productLineId}`,
    { method: "DELETE" }
  );
}

export function createProductItem(session: Session, productLineId: string, payload: ProductItemPayload) {
  return requestJson<ProductItem>(
    session,
    `/platform/organizations/${session.organization_id}/product-lines/${productLineId}/items`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function deleteProductItem(session: Session, productItemId: string) {
  await requestJson<null>(
    session,
    `/platform/organizations/${session.organization_id}/product-items/${productItemId}`,
    { method: "DELETE" }
  );
}

export function getPublicProductCatalogUrl(organizationId: string) {
  return `${apiUrl}/platform/public/organizations/${organizationId}/product-catalog`;
}

export async function fetchPublicProductCatalog(organizationId: string) {
  const response = await fetch(getPublicProductCatalogUrl(organizationId));
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      typeof data === "object" &&
      data !== null &&
      "detail" in data &&
      typeof data.detail === "string"
        ? data.detail
        : "Request failed";
    throw new ApiError(detail, response.status);
  }
  return data as PublicProductCatalog;
}

export function startDiscovery(
  session: Session,
  payload: {
    product_line_id: string;
    target_market: string;
    location_scope_id?: string;
    location_country_code?: string;
    allow_repeat_location?: boolean;
    buyer_profile?: string;
    excluded_keywords?: string[];
    limit: number;
  }
) {
  return requestJson<DiscoveryRun>(session, `/discovery/organizations/${session.organization_id}/runs`, {
    method: "POST",
    body: JSON.stringify({ ...payload, idempotency_key: `discovery-${Date.now()}` }),
  });
}

export function resolveAdministrativeLocation(
  session: Session,
  query: string,
  productLineId?: string,
) {
  return requestJson<ResolvedLocation>(
    session,
    `/discovery/organizations/${session.organization_id}/locations/resolve`,
    {
      method: "POST",
      body: JSON.stringify({ query, product_line_id: productLineId ?? "" }),
    }
  );
}

export function listLeads(session: Session, workflowRunId?: string) {
  const query = workflowRunId ? `?workflow_run_id=${encodeURIComponent(workflowRunId)}` : "";
  return requestJson<Lead[]>(session, `/discovery/organizations/${session.organization_id}/leads${query}`);
}

export function createManualLead(session: Session, payload: ManualLeadPayload) {
  return requestJson<Lead>(session, `/discovery/organizations/${session.organization_id}/leads`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function deleteLead(session: Session, leadId: string) {
  await requestJson<null>(
    session,
    `/discovery/organizations/${session.organization_id}/leads/${leadId}`,
    { method: "DELETE" }
  );
}

export function getLeadDetail(session: Session, leadId: string) {
  return requestJson<LeadDetail>(
    session,
    `/discovery/organizations/${session.organization_id}/leads/${leadId}/detail`
  );
}

export function updateLeadDetail(session: Session, leadId: string, payload: LeadDetailPayload) {
  return requestJson<Lead>(session, `/discovery/organizations/${session.organization_id}/leads/${leadId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function createFollowUp(session: Session, leadId: string, payload: FollowUpPayload) {
  return requestJson<FollowUpRecord>(
    session,
    `/discovery/organizations/${session.organization_id}/leads/${leadId}/follow-ups`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export function createFollowUpTask(session: Session, leadId: string, payload: FollowUpTaskPayload) {
  return requestJson<FollowUpTask>(
    session,
    `/discovery/organizations/${session.organization_id}/leads/${leadId}/follow-up-tasks`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export function listFollowUps(session: Session, limit = 20) {
  return requestJson<FollowUpRecord[]>(
    session,
    `/discovery/organizations/${session.organization_id}/follow-ups?limit=${limit}`
  );
}

export function listFollowUpTasks(session: Session, statusFilter: FollowUpTaskStatus | "all" = "open", limit = 20) {
  const statusQuery = statusFilter === "all" ? "" : `status_filter=${encodeURIComponent(statusFilter)}&`;
  return requestJson<FollowUpTask[]>(
    session,
    `/discovery/organizations/${session.organization_id}/follow-up-tasks?${statusQuery}limit=${limit}`
  );
}

export function completeFollowUpTask(session: Session, taskId: string) {
  return requestJson<FollowUpTask>(
    session,
    `/discovery/organizations/${session.organization_id}/follow-up-tasks/${taskId}/complete`,
    { method: "POST" }
  );
}

export function createQuoteDraft(session: Session, leadId: string, payload: QuoteDraftPayload) {
  return requestJson<QuoteDraft>(
    session,
    `/discovery/organizations/${session.organization_id}/leads/${leadId}/quote-drafts`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export function updateQuoteDraft(session: Session, draftId: string, payload: QuoteDraftPayload) {
  return requestJson<QuoteDraft>(
    session,
    `/discovery/organizations/${session.organization_id}/quote-drafts/${draftId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    }
  );
}

export function markQuoteDraftSent(session: Session, draftId: string) {
  return requestJson<QuoteDraft>(
    session,
    `/discovery/organizations/${session.organization_id}/quote-drafts/${draftId}/send`,
    { method: "POST" }
  );
}

export function getEmailDeliveryStatus(session: Session) {
  return requestJson<EmailDeliveryStatus>(
    session,
    `/platform/organizations/${session.organization_id}/email-delivery`
  );
}

export function getCustomerDevelopmentConnectors(session: Session) {
  return requestJson<CustomerDevelopmentConnectors>(
    session,
    `/platform/organizations/${session.organization_id}/customer-development-connectors`
  );
}

export function listSearchSources(session: Session) {
  return requestJson<SearchSourcesResponse>(
    session,
    `/platform/organizations/${session.organization_id}/search-sources`
  );
}

export function updateSearchSource(session: Session, sourceId: string, enabled: boolean) {
  return requestJson<SearchSource>(
    session,
    `/platform/organizations/${session.organization_id}/search-sources/${sourceId}`,
    {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    }
  );
}

export function createContact(session: Session, leadId: string, payload: ContactPayload) {
  return requestJson<ContactRecord>(
    session,
    `/discovery/organizations/${session.organization_id}/leads/${leadId}/contacts`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export function discoverContacts(session: Session, leadId: string, limit = 10) {
  return requestJson<ContactRecord[]>(
    session,
    `/discovery/organizations/${session.organization_id}/leads/${leadId}/contacts/discover`,
    {
      method: "POST",
      body: JSON.stringify({ limit }),
    }
  );
}

export function discoverDailyContacts(session: Session) {
  return requestJson<DailyContactDiscoveryResult>(
    session,
    `/discovery/organizations/${session.organization_id}/contacts/discover-daily`,
    {
      method: "POST",
      body: JSON.stringify({
        timezone: "Asia/Shanghai",
        lead_limit: 50,
        contacts_per_lead: 10,
      }),
    }
  );
}

export function discoverContactBatch(session: Session, leadIds: string[]) {
  return requestJson<BatchContactDiscoveryResult>(
    session,
    `/discovery/organizations/${session.organization_id}/contacts/discover-batch`,
    {
      method: "POST",
      body: JSON.stringify({ lead_ids: leadIds, contacts_per_lead: 10 }),
    }
  );
}

export function verifyContactEmail(session: Session, leadId: string, contactId: string) {
  return requestJson<ContactRecord>(
    session,
    `/discovery/organizations/${session.organization_id}/leads/${leadId}/contacts/${contactId}/verify-email`,
    { method: "POST" }
  );
}

export async function deleteContact(session: Session, leadId: string, contactId: string) {
  await requestJson<null>(
    session,
    `/discovery/organizations/${session.organization_id}/leads/${leadId}/contacts/${contactId}`,
    { method: "DELETE" }
  );
}

export function createEmailDraft(session: Session, leadId: string, contactId: string) {
  return requestJson<EmailDraft>(
    session,
    `/discovery/organizations/${session.organization_id}/leads/${leadId}/email-drafts`,
    {
      method: "POST",
      body: JSON.stringify({ contact_id: contactId }),
    }
  );
}

export function listEmailDrafts(session: Session, statusFilter?: EmailDraftStatus) {
  const query = statusFilter ? `?status_filter=${encodeURIComponent(statusFilter)}` : "";
  return requestJson<EmailDraft[]>(
    session,
    `/discovery/organizations/${session.organization_id}/email-drafts${query}`
  );
}

export function listWebsiteInquiries(session: Session, statusFilter?: WebsiteInquiryStatus | "all") {
  const query = statusFilter && statusFilter !== "all" ? `?status_filter=${encodeURIComponent(statusFilter)}` : "";
  return requestJson<WebsiteInquiry[]>(
    session,
    `/discovery/organizations/${session.organization_id}/website-inquiries${query}`
  );
}

export function convertWebsiteInquiry(session: Session, inquiryId: string) {
  return requestJson<WebsiteInquiryConversion>(
    session,
    `/discovery/organizations/${session.organization_id}/website-inquiries/${inquiryId}/convert`,
    { method: "POST" }
  );
}

export async function submitWebsiteInquiry(organizationId: string, payload: WebsiteInquiryPayload) {
  const response = await fetch(`${apiUrl}/discovery/public/organizations/${organizationId}/website-inquiries`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      typeof data === "object" &&
      data !== null &&
      "detail" in data &&
      typeof data.detail === "string"
        ? data.detail
        : "Request failed";
    throw new ApiError(detail, response.status);
  }
  return data as WebsiteInquiry;
}

export function updateEmailDraft(
  session: Session,
  draftId: string,
  payload: { subject: string; body: string }
) {
  return requestJson<EmailDraft>(
    session,
    `/discovery/organizations/${session.organization_id}/email-drafts/${draftId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    }
  );
}

export function updateDraftContactEmail(session: Session, draftId: string, email: string) {
  return requestJson<EmailDraft>(
    session,
    `/discovery/organizations/${session.organization_id}/email-drafts/${draftId}/contact-email`,
    {
      method: "PATCH",
      body: JSON.stringify({ email }),
    }
  );
}

export function reviewEmailDraft(
  session: Session,
  draftId: string,
  payload: { action: "approve" | "reject"; rejection_reason?: string }
) {
  return requestJson<EmailDraft>(
    session,
    `/discovery/organizations/${session.organization_id}/email-drafts/${draftId}/review`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export function markEmailDraftSent(session: Session, draftId: string) {
  return requestJson<EmailDraft>(
    session,
    `/discovery/organizations/${session.organization_id}/email-drafts/${draftId}/send`,
    { method: "POST" }
  );
}
