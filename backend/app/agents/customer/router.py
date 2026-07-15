from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import Field
from sqlalchemy.orm import Session

from app.agents.customer.agent import CustomerDiscoveryService
from app.agents.customer.models import CustomerDiscoveryInput, CustomerDiscoveryOutput
from app.connectors.search.bocha import BochaSearchConnector
from app.platform.router import current_principal, get_session
from app.shared.security import SignedPrincipal
from app.workflow.models import WorkflowState

router = APIRouter(prefix="/discovery", tags=["discovery"])


class StartDiscoveryRequest(CustomerDiscoveryInput):
    idempotency_key: str = Field(min_length=1, max_length=200)


class StartDiscoveryResponse(CustomerDiscoveryOutput):
    state: str


@router.post(
    "/organizations/{organization_id}/runs",
    response_model=StartDiscoveryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_discovery(
    organization_id: str,
    payload: StartDiscoveryRequest,
    request: Request,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> StartDiscoveryResponse:
    api_key = request.app.state.settings.bocha_api_key
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bocha search connector is not configured",
        )
    service = CustomerDiscoveryService(session, BochaSearchConnector(api_key))
    try:
        output = await service.start(
            actor_user_id=principal.user_id,
            organization_id=organization_id,
            payload=CustomerDiscoveryInput.model_validate(payload.model_dump()),
            idempotency_key=payload.idempotency_key,
        )
        session.commit()
    except PermissionError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except Exception as error:
        session.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="customer discovery failed") from error
    return StartDiscoveryResponse(**output.model_dump(), state=WorkflowState.COMPLETED)
