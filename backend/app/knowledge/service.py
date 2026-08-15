from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.knowledge.models import KnowledgeDocument


class KnowledgeService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_documents(self, organization_id: str) -> list[KnowledgeDocument]:
        return list(
            self.session.scalars(
                select(KnowledgeDocument)
                .where(KnowledgeDocument.organization_id == organization_id)
                .order_by(KnowledgeDocument.created_at.desc())
            )
        )
