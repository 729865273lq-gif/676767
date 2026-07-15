# Product Lines and Discovery Entry Design

## Purpose

This stage turns the authenticated dashboard into the first usable customer-development workflow. A user can define product lines, select one product line, start a customer discovery run for a target market, and inspect evidence-backed leads returned by the existing backend discovery APIs.

The scope is intentionally limited. CRM conversion, email drafting, and outbound approval remain follow-up stages. This stage prepares the data and user workflow those later stages need.

## User Workflow

1. A logged-in user opens the sales workspace.
2. The workspace reads the current session and organization ID from local storage.
3. The user creates or views product lines for the organization.
4. Each product line stores:
   - name
   - description
   - product keywords
   - buyer profiles
   - target regions
5. The user selects a product line, target market, and buyer profile.
6. The user starts customer discovery.
7. The UI shows workflow state while the backend searches and scores leads.
8. The result table separates priority recommendations from leads that need enrichment.
9. Each lead row shows company, website, market, buyer profile, score, bucket, reasons, missing signals, and source evidence.
10. A "Save to CRM" action is visible but may remain disabled or return a clear "coming next" state until CRM conversion is implemented.

## Frontend Design

The first implementation can stay inside the existing dashboard route to reduce navigation churn. It should replace static lead seed data with API-backed state and split the dashboard into focused local sections:

- product line setup: list existing product lines and create a new product line
- discovery controls: select product line, target market, and buyer profile
- run status: show queued, running, completed, and failed states
- lead results: tab or filter for priority recommendations and needs enrichment

Client-side API calls should use a shared authenticated API helper so every request includes the stored Bearer token. The page should keep clear loading, empty, error, and permission-denied states.

## Backend Usage

This stage should use existing backend routes where possible:

- `GET /platform/organizations/{organization_id}/product-lines`
- `POST /platform/organizations/{organization_id}/product-lines`
- `POST /discovery/organizations/{organization_id}/runs`
- `GET /discovery/organizations/{organization_id}/leads`
- `GET /discovery/organizations/{organization_id}/leads/{lead_id}`

If an existing backend response is missing a field needed by the UI, the backend contract should be extended with a focused test first.

## Data Flow

```text
local session
  -> organization_id and access_token
  -> product line list/create
  -> discovery run request
  -> persisted leads
  -> lead list with source evidence
  -> later CRM conversion
```

The selected product line should drive search keywords and buyer profile defaults. The user can still narrow a run by target market and buyer profile before starting discovery.

## Error Handling

- Missing session redirects to `/login`.
- Expired or invalid token clears session and redirects to `/login`.
- A member without admin rights can view product lines, but product line creation should show a permission error if the backend rejects it.
- Discovery connector failure should show the workflow failure message without deleting any leads from prior successful runs.
- Empty product line state should guide the user to create the first product line before starting discovery.

## Testing

Backend verification should cover any changed product-line or discovery API behavior. Frontend verification should include:

- logged-in user can create a product line
- product line appears in the selector
- discovery form requires a product line
- successful discovery shows lead rows from API data
- unauthenticated user is redirected to `/login`

Manual browser QA should verify the page renders without framework overlay, has no relevant console errors, and the create product line plus discovery interaction path works against the local API.

## Out of Scope

- CRM company/contact conversion implementation
- email draft generation
- email approval and send
- knowledge document upload
- connector settings UI
- multi-page navigation refactor
