from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.workflow.models import WorkflowRun, WorkflowState, WorkflowStep


class WorkflowNotFound(LookupError):
    """Raised when a requested workflow is unavailable."""


class InvalidWorkflowTransition(ValueError):
    """Raised when a workflow is asked to move outside its state machine."""


ALLOWED_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.QUEUED: {WorkflowState.RUNNING, WorkflowState.FAILED},
    WorkflowState.RUNNING: {
        WorkflowState.WAITING_FOR_HUMAN,
        WorkflowState.COMPLETED,
        WorkflowState.FAILED,
    },
    WorkflowState.WAITING_FOR_HUMAN: {WorkflowState.RUNNING, WorkflowState.FAILED},
    WorkflowState.COMPLETED: set(),
    WorkflowState.FAILED: {WorkflowState.QUEUED},
}


class WorkflowService:
    def __init__(self, session: Session):
        self.session = session

    def create_run(
        self,
        *,
        organization_id: str,
        agent_id: str,
        agent_version: str,
        input_payload: dict[str, object],
        idempotency_key: str,
    ) -> WorkflowRun:
        existing = self.session.scalar(
            select(WorkflowRun).where(
                WorkflowRun.organization_id == organization_id,
                WorkflowRun.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing

        run = WorkflowRun(
            organization_id=organization_id,
            agent_id=agent_id,
            agent_version=agent_version,
            input_json=input_payload,
            idempotency_key=idempotency_key,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def get_run(self, workflow_run_id: str, organization_id: str | None = None) -> WorkflowRun:
        statement = select(WorkflowRun).where(WorkflowRun.id == workflow_run_id)
        if organization_id is not None:
            statement = statement.where(WorkflowRun.organization_id == organization_id)
        run = self.session.scalar(statement)
        if run is None:
            raise WorkflowNotFound("workflow run not found")
        return run

    def transition(
        self,
        workflow_run_id: str,
        target_state: WorkflowState | str,
        *,
        organization_id: str | None = None,
        output_payload: dict[str, object] | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> WorkflowRun:
        run = self.get_run(workflow_run_id, organization_id)
        target = WorkflowState(target_state)
        if target not in ALLOWED_TRANSITIONS[run.state]:
            raise InvalidWorkflowTransition(f"cannot transition {run.state} to {target}")

        run.state = target
        if output_payload is not None:
            run.output_json = output_payload
        if target == WorkflowState.FAILED:
            run.error_code = error_code
            run.error_detail = error_detail
        else:
            run.error_code = None
            run.error_detail = None
        self.session.flush()
        return run

    def add_step(
        self,
        *,
        workflow_run_id: str,
        name: str,
        input_payload: dict[str, object],
    ) -> WorkflowStep:
        run = self.get_run(workflow_run_id)
        sequence = (
            self.session.scalar(
                select(WorkflowStep.sequence)
                .where(WorkflowStep.workflow_run_id == workflow_run_id)
                .order_by(WorkflowStep.sequence.desc())
                .limit(1)
            )
            or 0
        ) + 1
        step = WorkflowStep(
            workflow_run_id=run.id,
            organization_id=run.organization_id,
            sequence=sequence,
            name=name,
            agent_id=run.agent_id,
            agent_version=run.agent_version,
            input_json=input_payload,
        )
        self.session.add(step)
        self.session.flush()
        return step
