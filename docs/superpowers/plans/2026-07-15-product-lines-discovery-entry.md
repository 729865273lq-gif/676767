# Product Lines Discovery Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the logged-in product-line setup and customer discovery entry workflow.

**Architecture:** Keep the first iteration in the existing Next.js dashboard route. Add a small authenticated frontend API client that reads the saved session, calls existing FastAPI product-line and discovery endpoints, and feeds focused dashboard sections for product-line setup, discovery controls, and lead results.

**Tech Stack:** Next.js 15, React 19, TypeScript, Playwright e2e, existing FastAPI product-line and discovery APIs.

---

## File Structure

- Create: `frontend/lib/api.ts`  
  Owns typed authenticated API requests, product-line calls, discovery run calls, and lead-list calls.
- Create: `frontend/e2e/discovery-entry.spec.ts`  
  Browser contract for logged-in product-line creation, product selection, discovery run, and evidence-backed lead display.
- Modify: `frontend/lib/auth.ts`  
  Reuse session and auth header helpers from the API client.
- Modify: `frontend/app/page.tsx`  
  Replace static discovery seed data with API-backed product-line and lead state while preserving the existing dashboard shell.
- Modify: `frontend/app/globals.css`  
  Add layout styles for product-line setup, discovery controls, loading, error, and empty states.
- Modify: `frontend/e2e/health.spec.ts`  
  Keep the legacy smoke test aligned with the API-backed dashboard by stubbing required endpoints.

---

### Task 1: Frontend API Client

**Files:**
- Create: `frontend/lib/api.ts`
- Modify: `frontend/lib/auth.ts`

- [ ] **Step 1: Write the API client shape**

Create `frontend/lib/api.ts` with these exported types and functions:

```ts
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
```

- [ ] **Step 2: Implement authenticated request handling**

Add:

```ts
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
```

- [ ] **Step 3: Add endpoint helpers**

Add:

```ts
export function listProductLines(session: Session) {
  return requestJson<ProductLine[]>(session, `/platform/organizations/${session.organization_id}/product-lines`);
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
```

- [ ] **Step 4: Run TypeScript through build later**

Run after Task 3: `cd frontend && npm.cmd run build`.

Expected: build exits 0.

---

### Task 2: E2E Contract First

**Files:**
- Create: `frontend/e2e/discovery-entry.spec.ts`
- Modify: `frontend/e2e/health.spec.ts`

- [ ] **Step 1: Write the failing browser test**

Create `frontend/e2e/discovery-entry.spec.ts`:

```ts
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

  await expect(page.getByText("Industrial LED lighting")).toBeVisible();
  await page.getByLabel("Discovery product line").selectOption("product-1");
  await page.getByLabel("Discovery target market").fill("Germany");
  await page.getByLabel("Discovery buyer profile").selectOption("Distributor");
  await page.getByRole("button", { name: "Start discovery" }).click();

  await expect(page.getByText("Discovery complete")).toBeVisible();
  await expect(page.getByRole("cell", { name: "LumenHaus GmbH" })).toBeVisible();
  await expect(page.getByText("Commercial lighting distributor")).toBeVisible();
  await expect(page.getByText("Needs enrichment")).toBeVisible();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm.cmd run test:e2e -- discovery-entry.spec.ts`.

Expected: FAIL because product-line setup controls are not rendered yet.

- [ ] **Step 3: Update the smoke test to stub the new API calls**

Modify `frontend/e2e/health.spec.ts` to route product-line and discovery endpoints before `page.goto("/")`, so the dashboard test remains deterministic.

- [ ] **Step 4: Run the smoke test after implementation**

Run after Task 3: `cd frontend && npm.cmd run test:e2e -- health.spec.ts`.

Expected: PASS.

---

### Task 3: Dashboard Implementation

**Files:**
- Modify: `frontend/app/page.tsx`
- Modify: `frontend/app/globals.css`

- [ ] **Step 1: Replace static seed leads with API-backed state**

In `frontend/app/page.tsx`, import:

```ts
import {
  ApiError,
  createProductLine,
  listLeads,
  listProductLines,
  startDiscovery,
  type Lead,
  type ProductLine,
} from "../lib/api";
```

Use state for:

```ts
const [productLines, setProductLines] = useState<ProductLine[]>([]);
const [selectedProductLineId, setSelectedProductLineId] = useState("");
const [leads, setLeads] = useState<Lead[]>([]);
const [targetMarket, setTargetMarket] = useState("Germany");
const [buyerProfile, setBuyerProfile] = useState("");
const [error, setError] = useState("");
const [loadingProductLines, setLoadingProductLines] = useState(false);
```

- [ ] **Step 2: Load product lines after session**

After `readSession()` succeeds, call `listProductLines(currentSession)`, set `productLines`, and select the first product line when present. If `ApiError.status === 401`, clear the session and redirect to `/login`.

- [ ] **Step 3: Add product-line create form**

Add a dashboard section with labels:

```tsx
Product line name
Product keywords
Buyer profiles
Target regions
```

Parse comma-separated values with:

```ts
function parseCsv(value: FormDataEntryValue | null) {
  return String(value ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}
```

- [ ] **Step 4: Add discovery controls**

Render:

```tsx
<select aria-label="Discovery product line" />
<input aria-label="Discovery target market" />
<select aria-label="Discovery buyer profile" />
```

Disable `Start discovery` until a product line exists.

- [ ] **Step 5: Start discovery and fetch leads**

On submit, call `startDiscovery(session, { product_line_id, target_market, buyer_profile, limit: 20 })`, then call `listLeads(session, run.workflow_run_id)`. Show the returned query and lead count in the status line.

- [ ] **Step 6: Render real lead buckets**

Map backend buckets to display text:

```ts
const bucketLabel = {
  priority_recommendation: "Priority",
  needs_enrichment: "Needs enrichment",
  not_qualified: "Not qualified",
} as const;
```

The lead table shows company name, website, market/profile, source excerpt, score, and bucket. The priority filter should include only `priority_recommendation`.

- [ ] **Step 7: Add scoped CSS**

Add classes for product setup, compact form grids, empty state, error banner, lead evidence, and disabled CRM action. Keep the dashboard work-focused and consistent with the current blue/white operational UI.

- [ ] **Step 8: Run the e2e tests**

Run: `cd frontend && npm.cmd run test:e2e -- discovery-entry.spec.ts health.spec.ts`.

Expected: both tests pass.

---

### Task 4: Verification and Commit

**Files:**
- Verify all touched frontend files.
- Do not stage `.worktrees/`.

- [ ] **Step 1: Run frontend verification**

Run:

```powershell
cd frontend
npm.cmd run lint
npm.cmd run build
npm.cmd run test:e2e
```

Expected: all commands exit 0.

- [ ] **Step 2: Run backend smoke verification**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check app tests
```

Expected: backend test suite and lint exit 0.

- [ ] **Step 3: Browser QA**

Use the in-app browser at `http://127.0.0.1:3000/`:

1. Confirm dashboard renders with no framework overlay.
2. Create a product line.
3. Start discovery.
4. Confirm lead table updates or shows a clear connector error if Bocha is unavailable.
5. Confirm console has no relevant app errors.

- [ ] **Step 4: Commit only scoped files**

Stage the frontend API, dashboard, CSS, e2e tests, and plan file. Do not stage `.worktrees/` or local `.env` files.

Commit message:

```bash
git commit -m "feat: add product discovery entry"
```
