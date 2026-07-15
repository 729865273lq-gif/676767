import pytest

from app.workflow.models import WorkflowRun, WorkflowState
from app.workflow.service import InvalidWorkflowTransition, WorkflowService


@pytest.fixture
def workflow_run(session, organizations) -> WorkflowRun:
    run = WorkflowRun(
        organization_id=organizations["acme"].id,
        agent_id="customer",
        agent_version="1.0.0",
        input_json={"country": "Germany"},
        idempotency_key="customer-germany-1",
    )
    session.add(run)
    session.flush()
    return run


def test_completed_workflow_cannot_return_to_running(session, workflow_run) -> None:
    service = WorkflowService(session)
    service.transition(workflow_run.id, WorkflowState.RUNNING)
    service.transition(workflow_run.id, WorkflowState.COMPLETED)

    with pytest.raises(InvalidWorkflowTransition):
        service.transition(workflow_run.id, WorkflowState.RUNNING)


def test_workflow_run_is_scoped_to_its_organization(session, workflow_run, organizations) -> None:
    service = WorkflowService(session)

    with pytest.raises(LookupError):
        service.get_run(workflow_run.id, organizations["globex"].id)
