from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.platform.router import current_principal, get_session
from app.platform.service import OrganizationService, TenantAccessDenied
from app.shared.security import SignedPrincipal
from app.workflow.models import WorkflowRun, WorkflowState
from app.workflow.service import InvalidWorkflowTransition, WorkflowNotFound, WorkflowService

router = APIRouter(prefix="/workflows", tags=["workflows"])


class CreateWorkflowRunRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=100)
    agent_version: str = Field(min_length=1, max_length=50)
    input: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=200)


class TransitionWorkflowRunRequest(BaseModel):
    target_state: WorkflowState
    output: dict[str, object] | None = None
    error_code: str | None = Field(default=None, max_length=100)
    error_detail: str | None = Field(default=None, max_length=500)


class WorkflowRunResponse(BaseModel):
    id: str
    organization_id: str
    agent_id: str
    agent_version: str
    state: WorkflowState
    input: dict[str, object]
    output: dict[str, object] | None
    error_code: str | None
    error_detail: str | None


def workflow_response(run: WorkflowRun) -> WorkflowRunResponse:
    return WorkflowRunResponse(
        id=run.id,
        organization_id=run.organization_id,
        agent_id=run.agent_id,
        agent_version=run.agent_version,
        state=run.state,
        input=run.input_json,
        output=run.output_json,
        error_code=run.error_code,
        error_detail=run.error_detail,
    )


def require_membership(principal: SignedPrincipal, organization_id: str, session: Session) -> None:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
    except TenantAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error


@router.post(
    "/organizations/{organization_id}/runs",
    response_model=WorkflowRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_run(
    organization_id: str,
    payload: CreateWorkflowRunRequest,
    request: Request,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> WorkflowRunResponse:
    require_membership(principal, organization_id, session)
    run = WorkflowService(session).create_run(
        organization_id=organization_id,
        agent_id=payload.agent_id,
        agent_version=payload.agent_version,
        input_payload=payload.input,
        idempotency_key=payload.idempotency_key,
    )
    session.commit()
    return workflow_response(run)


@router.get("/organizations/{organization_id}/runs/{workflow_run_id}", response_model=WorkflowRunResponse)
def get_workflow_run(
    organization_id: str,
    workflow_run_id: str,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> WorkflowRunResponse:
    require_membership(principal, organization_id, session)
    try:
        run = WorkflowService(session).get_run(workflow_run_id, organization_id)
    except WorkflowNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return workflow_response(run)


@router.post(
    "/organizations/{organization_id}/runs/{workflow_run_id}/transitions",
    response_model=WorkflowRunResponse,
)
def transition_workflow_run(
    organization_id: str,
    workflow_run_id: str,
    payload: TransitionWorkflowRunRequest,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> WorkflowRunResponse:
    require_membership(principal, organization_id, session)
    try:
        run = WorkflowService(session).transition(
            workflow_run_id,
            payload.target_state,
            organization_id=organization_id,
            output_payload=payload.output,
            error_code=payload.error_code,
            error_detail=payload.error_detail,
        )
    except WorkflowNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except InvalidWorkflowTransition as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    session.commit()
    return workflow_response(run)
