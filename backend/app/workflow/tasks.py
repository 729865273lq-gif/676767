from __future__ import annotations

from typing import Protocol


class WorkflowTaskDispatcher(Protocol):
    """Dispatches a durable workflow run to the background worker."""

    def dispatch(self, workflow_run_id: str) -> None: ...
