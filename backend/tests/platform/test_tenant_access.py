import pytest

from app.platform.service import OrganizationService, TenantAccessDenied


def test_member_cannot_read_another_organization_company(session, organizations, members):
    service = OrganizationService(session)

    with pytest.raises(TenantAccessDenied):
        service.require_membership(members["acme_member"].user_id, organizations["globex"].id)


def test_admin_can_manage_members_but_member_cannot(session, organizations, members):
    service = OrganizationService(session)

    service.require_admin(members["acme_admin"].user_id, organizations["acme"].id)

    with pytest.raises(TenantAccessDenied):
        service.require_admin(members["acme_member"].user_id, organizations["acme"].id)
