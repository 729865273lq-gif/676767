import { authHeaders, clearSession, type Session } from "./auth";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ProductLine = {
  id: string;
  name: string;
  description: string;
  product_keywords: string[];
  buyer_profiles: string[];
  target_regions: string[];
  is_active: boolean;
  suppliers: string[];
};

export type CreateProductLinePayload = {
  name: string;
  description: string;
  product_keywords: string[];
  buyer_profiles: string[];
  target_regions: string[];
};

export type DiscoveryRun = {
  workflow_run_id: string;
  query: string;
  lead_count: number;
  state: string;
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

export type ContactRecord = {
  id: string;
  lead_id: string;
  name: string;
  title: string;
  email: string;
  phone: string;
  linkedin_url: string;
  whatsapp: string;
  is_primary: boolean;
  created_at: string;
};

export type LeadDetail = Lead & {
  contacts: ContactRecord[];
  follow_ups: FollowUpRecord[];
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

export type ContactPayload = {
  name: string;
  title?: string;
  email?: string;
  phone?: string;
  linkedin_url?: string;
  whatsapp?: string;
  is_primary?: boolean;
};

export type EmailDraftStatus = "pending_approval" | "ready_to_send" | "sent" | "rejected";

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
  evidence_snapshot: Array<{ signal_name: string; source_excerpt: string; source_url: string }>;
  rejection_reason: string;
  created_at: string;
  updated_at: string;
  reviewed_at: string | null;
  sent_at: string | null;
  lead_company_name: string;
  contact_name: string;
  contact_email: string;
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

export function startDiscovery(
  session: Session,
  payload: { product_line_id: string; target_market: string; buyer_profile?: string; limit: number }
) {
  return requestJson<DiscoveryRun>(session, `/discovery/organizations/${session.organization_id}/runs`, {
    method: "POST",
    body: JSON.stringify({ ...payload, idempotency_key: `discovery-${Date.now()}` }),
  });
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

export function listFollowUps(session: Session, limit = 20) {
  return requestJson<FollowUpRecord[]>(
    session,
    `/discovery/organizations/${session.organization_id}/follow-ups?limit=${limit}`
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
