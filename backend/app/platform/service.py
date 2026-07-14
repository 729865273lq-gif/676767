from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform.models import AuditEvent, MembershipRole, UserMembership


class TenantAccessDenied(PermissionError):
    """Raised when a user is outside the requested organization boundary."""


class OrganizationService:
    def __init__(self, session: Session):
        self.session = session

    def require_membership(self, user_id: str, organization_id: str) -> UserMembership:
        membership = self.session.scalar(
            select(UserMembership).where(
                UserMembership.user_id == user_id,
                UserMembership.organization_id == organization_id,
            )
        )
        if membership is None:
            raise TenantAccessDenied("organization membership required")
        return membership

    def require_admin(self, user_id: str, organization_id: str) -> UserMembership:
        membership = self.require_membership(user_id, organization_id)
        if membership.role != MembershipRole.ADMIN:
            raise TenantAccessDenied("administrator role required")
        return membership


class AuditService:
    def __init__(self, session: Session):
        self.session = session

    def record(
        self,
        *,
        actor_user_id: str | None,
        organization_id: str,
        event_type: str,
        metadata: dict[str, object],
    ) -> AuditEvent:
        event = AuditEvent(
            actor_user_id=actor_user_id,
            organization_id=organization_id,
            event_type=event_type,
            metadata_json=metadata,
        )
        self.session.add(event)
        return event
