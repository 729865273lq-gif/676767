# AI Foreign Trade Sales Platform V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a production-oriented, multi-tenant V1 that discovers high-quality foreign-trade prospects, produces evidence-grounded outreach for human approval, and records email follow-up in CRM.

**Architecture:** Build a modular monolith: a Next.js workbench consumes a FastAPI API and worker. Business modules own their domain services and persistence; agents call those services through a registry, while LLM, search, email, and storage providers sit behind organization-configured connector interfaces. PostgreSQL is the system of record; pgvector supports knowledge retrieval and Redis backs durable background work.

**Tech Stack:** Next.js 15, TypeScript, React, TanStack Query, Tailwind CSS, FastAPI, Python 3.12, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 16 with pgvector, Redis, Celery, pytest, Playwright, Docker Compose, OpenAI-compatible LLM connector, Gmail API, Microsoft Graph API, S3-compatible storage.

---

## Delivery Map

| Phase | Outcome | Completion evidence |
| --- | --- | --- |
| 1. Foundation | Secure multi-tenant workspace, module boundaries, workflows, credentials | Isolation, role, state-machine, and audit tests pass |
| 2. Discovery and CRM | Evidence-backed lead discovery, scoring, batch CRM conversion | Priority gate and canonical-domain dedupe tests pass |
| 3. Knowledge and email quality | Retrieval-grounded drafts and hard quality gate | Failed-quality drafts cannot enter review queue |
| 4. Mail and pilot hardening | Human-approved send, sync, reply analysis, reliable operations | End-to-end approved-send/reply loop passes once only |

## File Structure

```text
frontend/
  app/(app)/dashboard/page.tsx               Dashboard route
  app/(app)/discovery/page.tsx               Customer Agent workbench
  app/(app)/crm/[companyId]/page.tsx         CRM company detail
  app/(app)/email-review/page.tsx            Draft approval queue
  app/(app)/inbox/page.tsx                   Reply triage
  app/(app)/settings/{knowledge,connectors,members}/page.tsx
  components/{discovery,crm,email,shared}/   Focused UI modules
  lib/{api,auth,types}.ts                    API client and shared types
  e2e/sales-loop.spec.ts                     Browser acceptance test
backend/
  app/main.py                                App factory and route registration
  app/shared/{config,db,errors,security}.py  Cross-cutting infrastructure
  app/platform/                              Organizations, membership, credentials, audit
  app/workflow/                              Runs, steps, state transitions, Celery dispatch
  app/connectors/                            Provider-neutral contracts and implementations
  app/agents/{base,customer,email}/          Registry and two V1 agents
  app/crm/                                   Leads, companies, contacts, mail timeline, tasks
  app/knowledge/                             Documents, chunks, retrieval
  app/dashboard/                             Organization-scoped metrics
  tests/{platform,workflow,crm,agents,knowledge,integration}/
database/alembic/versions/                   Schema migrations
docker-compose.yml                           Local PostgreSQL, Redis, MinIO, backend, worker, frontend
```

## Task 1: Repository, Local Runtime, and Test Harness

**Files:**
- Create: `.gitignore`, `.env.example`, `docker-compose.yml`, `Makefile`, `README.md`
- Create: `backend/pyproject.toml`, `backend/app/main.py`, `backend/app/shared/config.py`, `backend/tests/test_health.py`
- Create: `frontend/package.json`, `frontend/app/layout.tsx`, `frontend/app/page.tsx`, `frontend/e2e/health.spec.ts`

- [x] **Step 1: Write backend health test before adding an API route**

```python
# backend/tests/test_health.py
from fastapi.testclient import TestClient

from app.main import create_app


def test_health_reports_service_name() -> None:
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"service": "foreign-trade-api", "status": "ok"}
```

- [x] **Step 2: Verify the test fails because the application factory is missing**

Run: `cd backend && uv run pytest tests/test_health.py -q`

Expected: FAIL with an import error for `app.main`.

- [x] **Step 3: Implement the smallest app factory and health route**

```python
# backend/app/main.py
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="AI Foreign Trade Sales Platform")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"service": "foreign-trade-api", "status": "ok"}

    return app


app = create_app()
```

- [x] **Step 4: Verify backend health passes**

Run: `cd backend && uv run pytest tests/test_health.py -q`

Expected: `1 passed`.

- [x] **Step 5: Add a browser-visible frontend health assertion**

```ts
// frontend/e2e/health.spec.ts
import { expect, test } from "@playwright/test";

test("renders the sales workbench shell", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sales workspace" })).toBeVisible();
});
```

- [x] **Step 6: Implement the minimal frontend route and verify it**

```tsx
// frontend/app/page.tsx
export default function HomePage() {
  return <main><h1>Sales workspace</h1></main>;
}
```

Run: `cd frontend && npm run test:e2e -- health.spec.ts`

Expected: PASS.

- [x] **Step 7: Add deterministic local services and developer commands**

Create PostgreSQL 16 with `pgvector`, Redis 7, and MinIO in `docker-compose.yml`; set `DATABASE_URL`, `REDIS_URL`, `S3_ENDPOINT`, `CREDENTIAL_ENCRYPTION_KEY`, and `APP_SECRET` in `.env.example`. Add `make up`, `make test-backend`, `make test-frontend`, and `make lint` commands. Do not place real credentials in repository files.

- [x] **Step 8: Run the clean baseline and commit**

Run: `make test-backend && make test-frontend && make lint`

Expected: all commands exit 0.

Commit: `git add . && git commit -m "chore: scaffold sales platform runtime"`

## Task 2: Organization Isolation, Membership, Credentials, and Audit

**Files:**
- Create: `backend/app/platform/models.py`, `backend/app/platform/service.py`, `backend/app/platform/router.py`, `backend/app/platform/credentials.py`
- Create: `backend/tests/platform/test_tenant_access.py`, `backend/tests/platform/test_credentials.py`
- Modify: `backend/app/main.py`, `database/alembic/versions/0001_platform.py`

- [x] **Step 1: Write failing organization-access tests**

```python
# backend/tests/platform/test_tenant_access.py
import pytest

from app.platform.service import OrganizationService, TenantAccessDenied


def test_member_cannot_read_another_organization_company(session, organizations, members):
    service = OrganizationService(session)
    with pytest.raises(TenantAccessDenied):
        service.require_membership(members["acme_member"].user_id, organizations["globex"].id)


def test_admin_can_manage_members_but_member_cannot(session, organizations, members):
    service = OrganizationService(session)
    service.require_admin(members["acme_admin"].user_id, organizations["acme"].id)
    with pytest.raises(TenantAccessDenied):
        service.require_admin(members["acme_member"].user_id, organizations["acme"].id)
```

- [x] **Step 2: Verify isolation tests fail**

Run: `cd backend && uv run pytest tests/platform/test_tenant_access.py -q`

Expected: FAIL because platform service and models do not exist.

- [x] **Step 3: Implement the organization boundary**

```python
# backend/app/platform/service.py
class TenantAccessDenied(PermissionError):
    pass


class OrganizationService:
    def __init__(self, session): self.session = session

    def require_membership(self, user_id, organization_id):
        membership = self.session.scalar(
            select(UserMembership).where(
                UserMembership.user_id == user_id,
                UserMembership.organization_id == organization_id,
            )
        )
        if membership is None:
            raise TenantAccessDenied("organization membership required")
        return membership

    def require_admin(self, user_id, organization_id):
        membership = self.require_membership(user_id, organization_id)
        if membership.role != MembershipRole.ADMIN:
            raise TenantAccessDenied("administrator role required")
        return membership
```

Add `Organization`, `User`, `UserMembership`, `ConnectorCredential`, and `AuditEvent` tables. Every subsequent tenant table must include a non-null foreign-key `organization_id` and repository methods must require it as a parameter.

- [x] **Step 4: Verify role and tenant tests pass**

Run: `cd backend && uv run pytest tests/platform/test_tenant_access.py -q`

Expected: `2 passed`.

- [x] **Step 5: Write failing encrypted-credential and raw-secret tests**

```python
# backend/tests/platform/test_credentials.py
from app.platform.credentials import CredentialCipher


def test_cipher_round_trips_secret_without_storing_plaintext():
    cipher = CredentialCipher("a" * 32)
    encrypted = cipher.encrypt("sk-test-secret")
    assert encrypted != "sk-test-secret"
    assert cipher.decrypt(encrypted) == "sk-test-secret"
```

- [x] **Step 6: Implement credential encryption and audit writing**

Use `cryptography.fernet.Fernet` with a base64-encoded 32-byte key from configuration. Store only `ciphertext`, connector type, key label, last-four display value, and timestamps. The create/update methods call `AuditService.record` with actor, organization, event type, and safe metadata; audit metadata must never contain plaintext secrets.

- [x] **Step 7: Run platform tests, migration, and commit**

Run: `cd backend && uv run pytest tests/platform -q && uv run alembic upgrade head`

Expected: all tests pass and the platform migration applies.

Commit: `git add backend database && git commit -m "feat: add tenant platform foundation"`

## Task 3: Workflow Runtime, Connector Contracts, and Agent Registry

**Files:**
- Create: `backend/app/workflow/{models,service,router,tasks}.py`
- Create: `backend/app/connectors/{base,llm,search,email,storage}/__init__.py`
- Create: `backend/app/agents/base/{contracts,registry}.py`
- Create: `backend/tests/workflow/test_state_machine.py`, `backend/tests/agents/test_registry.py`
- Modify: `database/alembic/versions/0002_workflow.py`

- [x] **Step 1: Write the invalid-transition test first**

```python
# backend/tests/workflow/test_state_machine.py
import pytest

from app.workflow.service import InvalidWorkflowTransition, WorkflowService


def test_completed_workflow_cannot_return_to_running(workflow_run):
    service = WorkflowService(workflow_run.session)
    service.transition(workflow_run.id, "completed")
    with pytest.raises(InvalidWorkflowTransition):
        service.transition(workflow_run.id, "running")
```

- [x] **Step 2: Verify the state-machine test fails**

Run: `cd backend && uv run pytest tests/workflow/test_state_machine.py -q`

Expected: FAIL because `WorkflowService` is missing.

- [x] **Step 3: Implement durable run and step transitions**

Create `WorkflowRun` and `WorkflowStep` with organization ID, agent ID/version, JSON input/output, error code/detail, idempotency key, timestamps, and states `queued`, `running`, `waiting_for_human`, `completed`, `failed`. Implement a transition map that permits only:

```python
ALLOWED = {
    "queued": {"running", "failed"},
    "running": {"waiting_for_human", "completed", "failed"},
    "waiting_for_human": {"running", "failed"},
    "completed": set(),
    "failed": {"queued"},
}
```

- [x] **Step 4: Verify the state machine passes**

Run: `cd backend && uv run pytest tests/workflow/test_state_machine.py -q`

Expected: `1 passed`.

- [x] **Step 5: Write a failing plug-in registration test**

```python
# backend/tests/agents/test_registry.py
from app.agents.base.registry import AgentRegistry


class ExampleAgent:
    agent_id = "example"
    version = "1.0.0"


def test_registry_resolves_registered_agent_without_switch_statement():
    registry = AgentRegistry()
    registry.register(ExampleAgent())
    assert registry.resolve("example").version == "1.0.0"
```

- [x] **Step 6: Implement contracts and registry**

Define `Agent` and `Connector` protocols. An agent exposes `agent_id`, `version`, `input_model`, `output_model`, and async `run(context, payload)`. `AgentRegistry.register` rejects duplicate IDs and `resolve` raises a typed `AgentNotFound`. Define normalized `SearchResult`, `OutboundMessage`, `InboundMessage`, `RetrievedChunk`, and `LlmCompletion` Pydantic models before provider implementations.

- [x] **Step 7: Verify registry tests and commit**

Run: `cd backend && uv run pytest tests/workflow tests/agents -q`

Expected: all tests pass.

Commit: `git add backend database && git commit -m "feat: add workflow and extensibility contracts"`

## Task 4: Customer Agent, Lead Quality Gate, and CRM Conversion

**Files:**
- Create: `backend/app/crm/{models,service,router,scoring}.py`
- Create: `backend/app/agents/customer/{agent,models}.py`
- Create: `backend/app/connectors/search/{contract,serpapi}.py`
- Create: `backend/tests/crm/{test_dedupe,test_priority_gate,test_batch_save}.py`
- Create: `frontend/app/(app)/discovery/page.tsx`, `frontend/components/discovery/{discovery-form,lead-table,score-breakdown}.tsx`
- Modify: `database/alembic/versions/0003_crm.py`

- [x] **Step 1: Write the priority recommendation test**

```python
# backend/tests/crm/test_priority_gate.py
from app.crm.scoring import qualify_lead


def test_priority_recommendation_requires_site_fit_contact_and_decision_attempt():
    result = qualify_lead(
        website="https://buyer.example",
        fit_evidence=["Product range includes LED luminaires"],
        contact_channels=["sales@buyer.example"],
        decision_maker_attempted=True,
    )
    assert result.bucket == "priority_recommendation"


def test_missing_decision_attempt_is_needs_enrichment_not_priority():
    result = qualify_lead("https://buyer.example", ["LED distributor"], ["contact form"], False)
    assert result.bucket == "needs_enrichment"
```

- [x] **Step 2: Verify the quality-gate tests fail**

Run: `cd backend && uv run pytest tests/crm/test_priority_gate.py -q`

Expected: FAIL because `qualify_lead` is missing.

- [x] **Step 3: Implement transparent qualification and scoring**

Implement `LeadQualification` with `bucket`, `score`, `reasons`, and `missing_signals`. Require website, fit evidence, contact channel, and decision-maker attempt for `priority_recommendation`; do not require successfully named decision-maker. Score four 0-25 dimensions: business fit, reachability, contact quality, evidence confidence. Persist source URL, excerpt, capture time, and signal name on `LeadEvidence`.

- [x] **Step 4: Verify qualification tests pass**

Run: `cd backend && uv run pytest tests/crm/test_priority_gate.py -q`

Expected: `2 passed`.

- [x] **Step 5: Write canonical-domain dedupe and batch-save tests**

```python
# backend/tests/crm/test_dedupe.py
def test_save_lead_reuses_company_for_same_canonical_domain(crm_service, organization):
    first = crm_service.save_lead(organization.id, website="https://www.buyer.example/about")
    second = crm_service.save_lead(organization.id, website="https://buyer.example/contact")
    assert first.company_id == second.company_id
```

```python
# backend/tests/crm/test_batch_save.py
def test_batch_save_returns_one_result_per_selected_lead(crm_service, organization, qualified_leads):
    result = crm_service.batch_save_leads(organization.id, [lead.id for lead in qualified_leads])
    assert len(result.saved_company_ids) == len(qualified_leads)
```

- [x] **Step 6: Implement CRM conversion and Customer Agent**

Normalize domains with `urllib.parse.urlparse`, lowercase, remove `www.`, and use the normalized domain as the organization-scoped unique company key. Build `CustomerAgent.run` as workflow steps: query planning, search, company extraction, evidence collection, scoring, decision-maker attempt, and lead persistence. Each step records its agent version and source evidence; provider failures produce retryable workflow errors rather than partial data deletion.

- [x] **Step 7: Build the discovery workbench and verify API/UI behavior**

Render product, country, and optional filters; poll workflow state; show distinct Priority Recommendations and Needs Enrichment tabs; make the score breakdown and evidence links visible; support selected-row bulk save and bulk draft actions. Add an API contract test that a member can only read organization-scoped leads.

Run: `cd backend && uv run pytest tests/crm -q && cd ../frontend && npm run test:e2e -- discovery.spec.ts`

Expected: all tests pass.

- [x] **Step 8: Commit the discovery milestone**

Commit: `git add backend frontend database && git commit -m "feat: add evidence-backed customer discovery"`

## Task 5: Knowledge Base and Retrieval Context

**Files:**
- Create: `backend/app/knowledge/{models,service,ingest,retrieval,router}.py`
- Create: `backend/app/connectors/storage/{contract,s3}.py`, `backend/app/connectors/llm/{contract,openai}.py`
- Create: `backend/tests/knowledge/{test_authorization,test_retrieval}.py`
- Create: `frontend/app/(app)/settings/knowledge/page.tsx`, `frontend/components/knowledge/document-table.tsx`
- Modify: `database/alembic/versions/0004_knowledge.py`

- [x] **Step 1: Write failing retrieval-isolation test**

```python
# backend/tests/knowledge/test_retrieval.py
def test_retrieval_returns_only_the_selected_organization_chunks(retriever, organizations, chunks):
    results = retriever.search(organizations["acme"].id, "dimmable LED driver", limit=5)
    assert {chunk.organization_id for chunk in results} == {organizations["acme"].id}
```

- [x] **Step 2: Verify the test fails**

Run: `cd backend && uv run pytest tests/knowledge/test_retrieval.py -q`

Expected: FAIL because the retriever is missing.

- [x] **Step 3: Implement ingestion and retrieval**

Store source files in an organization-prefixed object path. Create `KnowledgeDocument` and `KnowledgeChunk` records with ingestion status `uploaded`, `processing`, `ready`, or `failed`. Extract PDF/DOCX/XLSX text with explicit parser adapters, chunk by token count with overlap, generate embeddings through the LLM connector, and query pgvector with `organization_id` and optional `product_line_id` filters. Preserve document ID, page/sheet, and excerpt for citations.

- [x] **Step 4: Verify retrieval, authorization, and migration**

Run: `cd backend && uv run pytest tests/knowledge -q && uv run alembic upgrade head`

Expected: all tests pass.

- [x] **Step 5: Implement knowledge UI and commit**

Allow administrators to upload a document, view parsing/embedding status, product-line association, and failure message. Members may search/use ready knowledge but may not upload or configure sources.

Commit: `git add backend frontend database && git commit -m "feat: add organization knowledge retrieval"`

## Task 6: Email Agent, Quality Gate, Human Approval, and Idempotent Send

**Files:**
- Create: `backend/app/agents/email/{agent,models,quality}.py`
- Create: `backend/app/crm/{email_service,mail_models}.py`
- Create: `backend/app/connectors/email/{contract,gmail,microsoft}.py`
- Create: `backend/tests/agents/test_email_quality.py`, `backend/tests/crm/test_email_send.py`
- Create: `frontend/app/(app)/email-review/page.tsx`, `frontend/components/email/{draft-editor,quality-report,approval-queue}.tsx`
- Modify: `database/alembic/versions/0005_email.py`

- [ ] **Step 1: Write the failing email-quality tests**

```python
# backend/tests/agents/test_email_quality.py
from app.agents.email.quality import evaluate_draft


def test_quality_gate_blocks_generic_draft_without_product_or_customer_evidence():
    report = evaluate_draft(subject="Hello", body="We offer good products. Please reply.", evidence=[])
    assert report.passed is False
    assert {issue.code for issue in report.issues} >= {"missing_product_evidence", "missing_personalization"}


def test_quality_gate_accepts_one_value_proposition_and_one_cta_with_citations():
    report = evaluate_draft(
        subject="Dimmable LED drivers for your retail lighting range",
        body="Your LED retail fixtures match our 0-10V dimmable drivers. We can share tested specifications for your next range review. Would a 15-minute call next week be useful?",
        evidence=["product: 0-10V dimmable driver", "company: LED retail fixtures"],
    )
    assert report.passed is True
```

- [ ] **Step 2: Verify the quality tests fail**

Run: `cd backend && uv run pytest tests/agents/test_email_quality.py -q`

Expected: FAIL because the quality module is missing.

- [ ] **Step 3: Implement the quality report and guarded state transition**

Create `EmailDraft`, `EmailQualityReport`, and `EmailQualityIssue`. A quality report checks requested language, configured length, cited product context, cited customer context, one value proposition, exactly one CTA, unsupported claims, pricing/delivery promises, spam-like phrases, and contact-personalization confidence. `EmailService.submit_for_review` must re-run the report and reject drafts that fail; the API returns issue codes and repair suggestions.

- [ ] **Step 4: Verify the quality gate passes**

Run: `cd backend && uv run pytest tests/agents/test_email_quality.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Write a failing approval and idempotent-send test**

```python
# backend/tests/crm/test_email_send.py
import pytest

from app.crm.email_service import DraftNotApproved, EmailService


def test_unapproved_draft_never_reaches_connector(email_service: EmailService, draft, connector):
    with pytest.raises(DraftNotApproved):
        email_service.send(draft.id)
    assert connector.sent_messages == []


def test_approved_draft_sends_once_for_same_idempotency_key(email_service, approved_draft, connector):
    email_service.send(approved_draft.id)
    email_service.send(approved_draft.id)
    assert len(connector.sent_messages) == 1
```

- [ ] **Step 6: Implement approval and sending contract**

Define the email connector method `send(message: OutboundMessage, idempotency_key: str) -> ProviderSendResult`. `EmailService.approve` writes actor/time audit data. `send` locks the draft row, verifies `approved`, derives a stable key from draft ID and version, invokes the selected connector once, persists provider message/thread IDs, writes `EmailMessage` and `TimelineEvent`, then marks `sent`. A duplicate request returns the existing send result.

- [ ] **Step 7: Build the approval workbench and test it**

Show batch queue, editable recipient/subject/body/attachment controls, product/customer evidence citations, quality status, repair suggestions, and explicit approve/send actions. Never render “sent” until the API reports a provider result. Add browser tests for failed-quality edit/recheck and unapproved-send rejection.

Run: `cd backend && uv run pytest tests/agents/test_email_quality.py tests/crm/test_email_send.py -q && cd ../frontend && npm run test:e2e -- email-review.spec.ts`

Expected: all tests pass.

- [ ] **Step 8: Commit the outreach quality milestone**

Commit: `git add backend frontend database && git commit -m "feat: add quality-gated email outreach"`

## Task 7: Gmail/Microsoft Sync, Reply Analysis, Follow-Up, Metrics, and Pilot QA

**Files:**
- Create: `backend/app/connectors/email/{gmail_sync,microsoft_sync}.py`
- Create: `backend/app/agents/email/reply_analysis.py`, `backend/app/dashboard/{service,router}.py`
- Create: `backend/tests/integration/test_sales_loop.py`, `backend/tests/dashboard/test_metrics.py`
- Create: `frontend/app/(app)/{dashboard,inbox}/page.tsx`, `frontend/components/{dashboard,inbox}/`
- Create: `frontend/e2e/sales-loop.spec.ts`, `docs/operations/pilot-runbook.md`

- [ ] **Step 1: Write the failing end-to-end domain test**

```python
# backend/tests/integration/test_sales_loop.py
def test_reply_sync_creates_analysis_follow_up_and_timeline(sales_loop, inbound_message):
    outcome = sales_loop.sync_reply(inbound_message)
    assert outcome.thread_id is not None
    assert outcome.analysis.intent in {"interested", "question", "not_now", "not_interested", "out_of_office"}
    assert outcome.follow_up_task_id is not None
    assert sales_loop.timeline_contains("reply_analyzed")
```

- [ ] **Step 2: Verify the integration test fails**

Run: `cd backend && uv run pytest tests/integration/test_sales_loop.py -q`

Expected: FAIL because reply synchronization is missing.

- [ ] **Step 3: Implement normalized mailbox synchronization and reply analysis**

Use Gmail history IDs and Microsoft Graph delta links; store provider cursor per organization mailbox. Normalize each inbound message by provider message ID, thread ID, sender, recipients, headers, body, received time, and attachments. Upsert idempotently, associate to CRM company/contact by canonical email/domain, run Email Agent reply classification, store confidence/rationale/suggested reply, create a due follow-up for non-terminal intent, and append timeline events.

- [ ] **Step 4: Verify reply loop passes**

Run: `cd backend && uv run pytest tests/integration/test_sales_loop.py -q`

Expected: `1 passed`.

- [ ] **Step 5: Write metric tests for the accepted pilot funnel**

```python
# backend/tests/dashboard/test_metrics.py
def test_metrics_count_only_current_organization(dashboard_service, organizations, funnel_data):
    metrics = dashboard_service.summary(organizations["acme"].id, funnel_data.day)
    assert metrics.priority_recommendations == 8
    assert metrics.review_ready_drafts == 6
    assert metrics.replies == 2
```

- [ ] **Step 6: Implement dashboard and inbox**

Expose discovered, qualified, priority, saved, review-ready, approved, sent, replied, and opportunity metrics; show reply rate and conversion per product line. Build inbox filters by intent and due date, suggested reply editor, task completion, and company timeline links. UI must render stable empty, loading, connector-error, and permission-denied states.

- [ ] **Step 7: Verify pilot acceptance in browser and API suites**

Implement `sales-loop.spec.ts` to create a qualifying lead, bulk save it, generate a draft, fail then pass quality gate, approve/send once through a fake connector, sync a reply, and observe resulting inbox task/timeline. Run responsive assertions at 1440x900 and 390x844.

Run: `cd backend && uv run pytest -q && cd ../frontend && npm run lint && npm run test:e2e -- sales-loop.spec.ts`

Expected: all backend tests, lint, and browser tests pass.

- [ ] **Step 8: Run security and operational release checks, then commit**

Verify tenant isolation for all routers, secret redaction in logs/audit output, connector retry/idempotency behavior, and a cold-start local Docker Compose run. Write the pilot runbook with connector OAuth setup, organization onboarding, failure recovery, backup policy, and support escalation. Capture desktop/mobile screenshots for dashboard, discovery, CRM detail, email review, and inbox.

Commit: `git add backend frontend docs && git commit -m "feat: complete pilot-ready sales workflow"`

## Final Verification Checklist

- [ ] `docker compose up --build` starts frontend, API, worker, PostgreSQL, Redis, and object storage without errors.
- [ ] `cd backend && uv run pytest -q` passes.
- [ ] `cd frontend && npm run lint && npm run test:e2e` passes.
- [ ] The API rejects cross-organization reads/writes and an unapproved email send.
- [ ] One approved draft creates one provider send, one CRM message, and one timeline event even when retried.
- [ ] The discovery UI separates priority recommendations from leads needing enrichment and explains every score.
- [ ] The email review UI displays a passing quality report with product/customer citations before approval becomes available.
- [ ] The inbox displays synchronized reply intent, suggested response, and follow-up task.
- [ ] Pilot funnel metrics are organization- and product-line-scoped and include the accepted targets.
