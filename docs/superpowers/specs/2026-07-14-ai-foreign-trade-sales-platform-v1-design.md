# AI Foreign Trade Sales Platform V1 Design

## Purpose

Build a production-oriented V1 for foreign-trade manufacturers and trading companies. The product closes the sales-development loop from product and market input through lead discovery, human-reviewed email outreach, reply analysis, follow-up, and CRM history.

V1 is a foundation for a broader AI Foreign Trade Platform. It is not an ERP, logistics, finance, customs, purchasing, factory, voice, or meeting product.

## Confirmed Product Decisions

- Target customers: manufacturers and trading companies.
- Lead discovery: public-web search and company website information first.
- Mail: Gmail/Google Workspace and Microsoft 365 through a shared email connector contract.
- External sending: every email requires human approval before it can be sent.
- Organization roles: `admin` and `member`.
- AI and search credentials: organization-provided API keys, encrypted at rest.
- Architecture: modular monolith with separate Next.js frontend and FastAPI backend.

## V1 Scope

## V1 Value Priorities

The V1 product outcome is prioritized in this order:

1. Customer accuracy: surface companies that are credible, relevant, reachable, and preferably associated with a buyer or decision-maker.
2. Development efficiency: let a member move qualified leads through review-ready outreach with batch actions and minimal repeated data entry.
3. Email quality: prepare concise, evidence-grounded, localized outreach that a sales team can confidently approve.
4. Follow-up standardization: preserve a consistent customer stage, next action, due date, and history after every interaction.

Dashboard and workflow metrics must expose the funnel for these outcomes: discovered leads, qualified leads, priority recommendations, saved CRM accounts, review-ready drafts, approved sends, replies, and created opportunities.

### Platform

- Authentication, organization workspaces, memberships, and role enforcement.
- Dashboard with daily new leads, sent emails, replies, total customers, reply rate, and opportunities.
- Knowledge base for PDF, Word, Excel, product catalog, product documentation, and FAQ.
- Product lines that support multiple product lines and suppliers for trading companies.
- Agent Center showing Customer Agent and Email Agent status, versions, and capabilities.
- Connection settings for AI, search, Gmail/Google Workspace, and Microsoft 365.
- Audit trail for agent actions, human approval, credential changes, and outbound email.

### Customer Agent

Input: product or product line, target country, optional language, industry, buyer type, and customer-size filters.

Behavior:

- Create a workflow run and collect public search results through a search connector.
- Extract public company name, website, country, contact details, and industry evidence.
- Normalize and deduplicate companies by canonical domain and organization-scoped identifiers.
- Match leads against the selected product line and knowledge base.
- Calculate explainable scores and recommendation reasons.
- Classify results into `priority_recommendation`, `needs_enrichment`, or `not_qualified` rather than treating every found company as a recommendation.
- Allow a member to save selected leads to CRM.

Output: company, website, email, country, contact, industry, score, recommendation, and source evidence.

Priority recommendation gate:

- A verified public website is required.
- Public evidence must establish a plausible product or business match.
- At least one usable contact channel is required, such as a public business email, a contact form URL, or a business phone number.
- The agent must attempt to identify a purchasing, sourcing, product, owner, or other decision-maker contact. Missing contact identity downgrades an otherwise valid lead to `needs_enrichment`; it does not discard it.
- A recommendation card must show the score breakdown and the exact website/source evidence supporting each positive qualification signal.

Scoring begins with four transparent dimensions: business fit, reachability, contact quality, and evidence confidence. Organization settings can adjust weights and the threshold for priority recommendations without changing agent code.

### Email Agent

- Generate multilingual outreach drafts from selected CRM contacts, product-line data, and relevant knowledge-base evidence.
- Preserve model inputs, generation metadata, and versioned drafts within the CRM email thread.
- Let a member change recipients, subject, body, and attachments before submission.
- Run a pre-review quality gate before a draft can enter `pending_review`.
- Enforce `draft -> pending_review -> approved -> sent`; no connector may send an unapproved draft.
- Synchronize sent mail and replies through the email connector.
- Classify reply intent, identify risks and next actions, produce a reply draft, and create a follow-up task when appropriate.

Pre-review email quality gate:

- Check the requested language, grammar, subject quality, and organization-configured length range.
- Require a traceable product claim sourced from the selected product line or knowledge base.
- Require a traceable personalization point sourced from the customer website or accepted lead evidence.
- Require one concrete value proposition and one single, unambiguous call to action.
- Flag unsupported performance claims, pricing or delivery promises without product evidence, spam-like phrasing, missing opt-out language where required, and unverified contact personalization.
- Return a quality report with pass/fail status, evidence references, and exact repair suggestions. A failed report prevents transition to `pending_review`; the member may edit and rerun the gate.

## Workflow

```text
Select product and target country
  -> Customer Agent discovers, enriches, scores, and recommends leads
  -> Member saves leads to CRM
  -> Email Agent prepares personalized email drafts
  -> Member reviews and approves each draft
  -> Email connector sends and records delivery state
  -> Email connector synchronizes replies
  -> Email Agent analyzes intent and suggests reply/follow-up
  -> CRM timeline records every transition
```

Workflow runs are durable and stateful. States are `queued`, `running`, `waiting_for_human`, `completed`, and `failed`. Retriable connector and document-processing failures retain their error record and do not discard completed prior steps.

## Architecture

```text
frontend/              Next.js + TypeScript application
backend/
  app/
    platform/          identity, organizations, credentials, audit
    dashboard/         organization-scoped sales metrics
    knowledge/         document ingestion, chunking, retrieval
    crm/               companies, contacts, opportunities, timeline
    workflow/          durable runs, steps, human gates, task dispatch
    agents/
      base/            agent contract and registry
      customer/        Customer Agent implementation
      email/           Email Agent implementation
    connectors/
      llm/             LLM provider implementations
      search/          public search implementations
      email/           Gmail and Microsoft 365 implementations
      storage/         object storage implementation
    shared/            configuration, database, errors, observability
database/              Alembic migrations and seed data
docs/                  architecture and operating documentation
tests/                 backend and end-to-end tests
```

Deployment remains a modular monolith: one backend API/worker deployment and one frontend deployment. Internal module boundaries use explicit service interfaces; modules may be extracted later without changing agent or connector callers.

### Agent Contract

Every agent implements a common contract with an identifier, version, declared input schema, declared output schema, and asynchronous `run` operation. Agents receive a narrow service context rather than direct database or provider access. The registry resolves an enabled agent by identifier and records the version on each workflow step.

### Connector Contract

LLM, Search, Email, and Storage connectors are interfaces selected per organization configuration. Implementations own vendor-specific authentication, requests, rate limits, retries, and response normalization. The rest of the system only consumes normalized domain objects.

Email sending is separate from draft generation. The sending operation requires an approved email-draft ID and validates approval server-side immediately before the connector call.

## Data Model

All tenant-owned tables carry `organization_id`; all queries are organization-scoped.

| Entity | Responsibility |
| --- | --- |
| `Organization` | Tenant, settings, approval policy |
| `UserMembership` | User-to-organization role (`admin` or `member`) |
| `ProductLine` | Product/supplier catalog unit |
| `KnowledgeDocument` | Uploaded source, status, chunks, source metadata |
| `ConnectorCredential` | Encrypted organization-provided vendor credential reference |
| `WorkflowRun` | Durable agent workflow state and input/output metadata |
| `Lead` | Discovered, scored, evidence-backed prospective company |
| `Company` | CRM customer account |
| `Contact` | Person or public contact channel linked to a company |
| `Opportunity` | Qualified commercial opportunity |
| `EmailDraft` | Versioned outbound/reply content and approval state |
| `EmailThread` | Provider thread correspondence associated with a company/contact |
| `EmailMessage` | Normalized inbound/outbound message record |
| `FollowUpTask` | Owner, due date, suggested next action, completion state |
| `TimelineEvent` | Immutable CRM activity history |
| `AuditEvent` | Security-sensitive and human-control actions |

```text
Lead: discovered -> scored -> saved -> contacted -> replied -> opportunity | disqualified
Email draft: draft -> pending_review -> approved -> sent -> replied | send_failed
Workflow: queued -> running -> waiting_for_human -> completed | failed
```

Invalid transitions return a domain error and create no external side effect.

## User Experience

- Dashboard: operational sales metrics and actionable queues, not a marketing home page.
- Lead discovery: dense search form, workflow progress, evidence-backed scored table, priority-recommendation queue, needs-enrichment queue, bulk save, and bulk draft action.
- CRM: company list plus detail page with contacts, product fit, email threads, AI findings, tasks, opportunities, and chronological history.
- Email review: bulk draft queue and an editable single-email review screen with unambiguous approval/send state.
- Email review: bulk draft queue, an editable single-email review screen, visible quality report/evidence, and unambiguous approval/send state.
- Inbox: synchronized replies, AI intent label, risks, suggested reply, and follow-up date.
- Knowledge and settings: document upload/status, product-line management, membership, and connector setup reserved for administrators.

## Security and Reliability

- Authenticate all users; authorize every operation by organization and role.
- Store secrets encrypted; never return raw credentials after initial entry.
- Persist provider identifiers and idempotency keys for email sends and synchronization to prevent duplicate communication.
- Record source URLs/evidence and model/agent version for generated lead scores and email content.
- Use background jobs for document ingestion, public search, LLM runs, mailbox synchronization, and retries.
- Log structured errors and workflow outcomes; expose actionable failures in the UI.
- Treat email approval, send, credential updates, and membership changes as auditable events.

## Acceptance Criteria

1. An administrator can create an organization, add a member, create multiple product lines, upload knowledge material, and configure organization-owned connector credentials.
2. A member can start a Customer Agent workflow with a product and target country, view normalized evidence-backed leads, and save selected leads to CRM without duplicates by canonical domain.
3. A lead cannot be a priority recommendation unless it has a verified website, product/business-fit evidence, a contact channel, and a recorded decision-maker identification attempt; lower-completeness leads remain visible in a needs-enrichment queue.
4. A member can bulk-save qualified leads, bulk-create outreach drafts, and generate a multilingual Email Agent draft using company, contact, product-line, and knowledge-base context.
5. A draft cannot enter the review queue until its quality report passes language, evidence, value proposition, personalization, call-to-action, and risk checks; a member can edit it and re-run the report.
6. The backend rejects any attempt to send a draft unless it is approved, and a successful approved send is represented in CRM timeline and message history exactly once.
7. A synchronized reply creates or updates an email thread, receives an intent analysis and suggested response, and can create a visible follow-up task.
8. A user from one organization cannot read or mutate another organization's business, credential, document, workflow, CRM, or mail data.
9. A new Agent or Connector implementation can be registered through its contract without modifying existing agent implementations.

## Pilot Success Metrics

The V1 pilot evaluates the three priority outcomes with these measurable targets:

1. One customer-development run produces at least 20 evidence-backed leads within 10 minutes, subject to external connector availability and rate limits.
2. Every priority recommendation satisfies the website, business-fit evidence, contact-channel, and decision-maker-identification-attempt gate.
3. A member can bulk-save at least 20 qualified leads and create their outreach drafts in one batch operation.
4. Every draft entering human review has a passing quality report that cites product and customer evidence.
5. Median member handling time from selecting a qualified lead to submitting its outreach for review is two minutes or less, excluding connector processing time and human writing time outside the product.

Metrics are recorded per organization and product line so pilot teams can compare discovery quality, throughput, draft quality, approval rate, send rate, reply rate, and opportunity conversion without exposing data across tenants.

## Delivery Phases

### Phase 1: Foundation (Weeks 1-3)

Repository, local runtime, identity, organizations, membership, database migrations, product lines, credentials, audit logging, agent registry, workflow persistence, connector interfaces, and baseline dashboard.

### Phase 2: Customer Development (Weeks 4-6)

Public-search connector, Customer Agent workflow, lead normalization/deduplication/scoring, CRM company/contact/detail/timeline, and source evidence.

### Phase 3: Outreach Loop (Weeks 7-9)

Knowledge ingestion/retrieval, Email Agent draft generation, approval queue, Gmail and Microsoft 365 connector implementations, sent-mail tracking, reply synchronization, intent analysis, suggested replies, and follow-up tasks.

### Phase 4: Pilot Hardening (Weeks 10-12)

Tenant-isolation tests, authorization audit, idempotency/retry behavior, connector failure paths, observability, operating documentation, end-to-end tests, responsive UI quality assurance, and pilot onboarding.

## Explicit Non-Goals

- ERP, purchasing, factory execution, logistics, shipping, finance, customs, order management, AI calling, and video meetings.
- Autonomous outbound emailing without human approval.
- Platform-managed AI/search billing in V1.
- Custom per-customer workflow builder UI; V1 stores extensible workflows but ships a fixed sales-development flow.
