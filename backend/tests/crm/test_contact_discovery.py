from app.connectors.contact_discovery import DiscoveredContact
from app.crm.models import CRMContact, FollowUpRecord
from app.crm.service import LeadService
from app.platform.models import ProductLine


def test_discovered_public_channels_merge_without_requiring_email(
    session,
    organizations,
    members,
) -> None:
    product_line = ProductLine(
        organization_id=organizations["acme"].id,
        name="Industrial Lighting",
        product_keywords=["LED"],
    )
    session.add(product_line)
    session.flush()
    service = LeadService(session)
    lead = service.create_manual_lead(
        organization_id=organizations["acme"].id,
        product_line_id=product_line.id,
        product_item_id=None,
        product_item_name="",
        company_name="Berlin Buyer GmbH",
        website="https://buyer.example",
        target_market="Germany",
        buyer_profile="distributor",
        notes="",
        actor_user_id=members["acme_member"].user_id,
    )
    existing = service.add_contact(
        organization_id=organizations["acme"].id,
        lead_id=lead.id,
        name="Sales Desk",
        title="",
        email="sales@buyer.example",
        phone="",
        linkedin_url="",
        whatsapp="",
        is_primary=True,
    )

    changed = service.add_discovered_contacts(
        organization_id=organizations["acme"].id,
        lead_id=lead.id,
        actor_user_id=members["acme_member"].user_id,
        discovered_contacts=[
            DiscoveredContact(
                name="Sales Desk",
                title="Public website contact",
                email="sales@buyer.example",
                phone="+49 30 123456",
                social_profiles=[
                    {"platform": "Instagram", "url": "https://instagram.com/buyer"}
                ],
                source_url="https://buyer.example/contact",
                source="Public website",
            ),
            DiscoveredContact(
                name="Berlin Buyer GmbH",
                title="Public website contact",
                email="",
                whatsapp="https://wa.me/49171123456",
                source_url="https://buyer.example",
                source="Public website",
            ),
        ],
    )

    contacts = session.query(CRMContact).filter(CRMContact.lead_id == lead.id).all()
    follow_up = session.query(FollowUpRecord).filter(
        FollowUpRecord.activity_type == "contact_discovery"
    ).one()
    assert len(changed) == 2
    assert len(contacts) == 2
    assert existing.phone == "+49 30 123456"
    assert existing.social_profiles == [
        {"platform": "Instagram", "url": "https://instagram.com/buyer"}
    ]
    assert existing.source_url == "https://buyer.example/contact"
    assert any(contact.whatsapp == "https://wa.me/49171123456" for contact in contacts)
    assert "Public website" in follow_up.content
