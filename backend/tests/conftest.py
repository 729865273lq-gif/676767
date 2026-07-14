from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.platform.models import MembershipRole, Organization, User, UserMembership
from app.shared.db import Base


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    Base.metadata.drop_all(engine)


@pytest.fixture
def organizations(session: Session) -> dict[str, Organization]:
    acme = Organization(name="Acme Export")
    globex = Organization(name="Globex Import")
    session.add_all([acme, globex])
    session.flush()
    return {"acme": acme, "globex": globex}


@pytest.fixture
def members(session: Session, organizations: dict[str, Organization]) -> dict[str, UserMembership]:
    admin_user = User(email="admin@acme.example", display_name="Acme Admin")
    member_user = User(email="member@acme.example", display_name="Acme Member")
    session.add_all([admin_user, member_user])
    session.flush()
    admin = UserMembership(
        user_id=admin_user.id,
        organization_id=organizations["acme"].id,
        role=MembershipRole.ADMIN,
    )
    member = UserMembership(
        user_id=member_user.id,
        organization_id=organizations["acme"].id,
        role=MembershipRole.MEMBER,
    )
    session.add_all([admin, member])
    session.flush()
    return {"acme_admin": admin, "acme_member": member}
