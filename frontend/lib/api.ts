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
  reasons: string[];
  missing_signals: string[];
  evidence: Array<{ source_url: string; source_excerpt: string; signal_name: string }>;
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
