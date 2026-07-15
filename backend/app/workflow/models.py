from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.models import utcnow
from app.shared.db import Base


class WorkflowState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_HUMAN = "waiting_for_human"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_workflow_run_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(50), nullable=False)
    state: Mapped[WorkflowState] = mapped_column(
        Enum(WorkflowState, native_enum=False, length=30), default=WorkflowState.QUEUED, nullable=False
    )
    input_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    output_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    __table_args__ = (UniqueConstraint("workflow_run_id", "sequence", name="uq_workflow_step_sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workflow_run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(50), nullable=False)
    state: Mapped[WorkflowState] = mapped_column(
        Enum(WorkflowState, native_enum=False, length=30), default=WorkflowState.QUEUED, nullable=False
    )
    input_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    output_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
