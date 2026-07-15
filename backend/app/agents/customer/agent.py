from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.agents.base.contracts import AgentRunContext
from app.agents.customer.models import CustomerDiscoveryInput, CustomerDiscoveryOutput
from app.connectors.search import SearchConnector
from app.crm.scoring import qualify_lead
from app.crm.service import LeadService
from app.platform.product_lines import ProductLineService
from app.platform.service import OrganizationService
from app.workflow.models import WorkflowState
from app.workflow.service import WorkflowService


class CustomerAgent:
    agent_id = "customer"
    version = "1.0.0"
    input_model = CustomerDiscoveryInput
    output_model = CustomerDiscoveryOutput

    def __init__(self, session: Session, search_connector: SearchConnector):
        self.session = session
        self.search_connector = search_connector

    async def run(
        self, context: AgentRunContext, payload: CustomerDiscoveryInput
    ) -> CustomerDiscoveryOutput:
        product_line = ProductLineService(self.session).get_product_line(
            payload.product_line_id, context.organization_id
        )
        query = build_discovery_query(product_line.name, product_line.product_keywords, payload)
        results = await self.search_connector.search(query, payload.limit)
        lead_service = LeadService(self.session)
        for result in results:
            qualification = qualify_lead(
                website=result.url,
                fit_evidence=[result.snippet] if result.snippet else [],
                contact_channels=[],
                decision_maker_attempted=False,
            )
            lead_service.save_discovered_lead(
                organization_id=context.organization_id,
                workflow_run_id=context.workflow_run_id,
                product_line_id=product_line.id,
                target_market=payload.target_market,
                buyer_profile=payload.buyer_profile,
                result=result,
                qualification=qualification,
            )
        return CustomerDiscoveryOutput(
            workflow_run_id=context.workflow_run_id,
            query=query,
            lead_count=len(results),
        )


class CustomerDiscoveryInProgress(RuntimeError):
    """Raised when an idempotent discovery request is already executing."""


class CustomerDiscoveryService:
    def __init__(self, session: Session, search_connector: SearchConnector):
        self.session = session
        self.agent = CustomerAgent(session, search_connector)

    async def start(
        self,
        *,
        actor_user_id: str,
        organization_id: str,
        payload: CustomerDiscoveryInput,
        idempotency_key: str | None = None,
    ) -> CustomerDiscoveryOutput:
        OrganizationService(self.session).require_membership(actor_user_id, organization_id)
        workflow_service = WorkflowService(self.session)
        run = workflow_service.create_run(
            organization_id=organization_id,
            agent_id=self.agent.agent_id,
            agent_version=self.agent.version,
            input_payload=payload.model_dump(),
            idempotency_key=idempotency_key or str(uuid4()),
        )
        if run.state == WorkflowState.COMPLETED and run.output_json is not None:
            return CustomerDiscoveryOutput.model_validate(run.output_json)
        if run.state == WorkflowState.RUNNING:
            raise CustomerDiscoveryInProgress("customer discovery is already running")
        if run.state == WorkflowState.FAILED:
            workflow_service.transition(run.id, WorkflowState.QUEUED, organization_id=organization_id)
        if run.state == WorkflowState.QUEUED:
            workflow_service.transition(run.id, WorkflowState.RUNNING, organization_id=organization_id)
        try:
            output = await self.agent.run(
                AgentRunContext(organization_id=organization_id, workflow_run_id=run.id), payload
            )
        except Exception as error:
            workflow_service.transition(
                run.id,
                WorkflowState.FAILED,
                organization_id=organization_id,
                error_code="customer_discovery_failed",
                error_detail=str(error)[:500],
            )
            raise
        workflow_service.transition(
            run.id,
            WorkflowState.COMPLETED,
            organization_id=organization_id,
            output_payload=output.model_dump(),
        )
        return output


def build_discovery_query(
    product_line_name: str,
    keywords: list[str],
    payload: CustomerDiscoveryInput,
) -> str:
    product_terms = " ".join(keywords[:5]) or product_line_name
    buyer_profile = payload.buyer_profile or "buyer"
    return f"{product_terms} {buyer_profile} {payload.target_market}".strip()
