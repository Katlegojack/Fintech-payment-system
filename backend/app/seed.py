from datetime import datetime, timedelta, date
from sqlalchemy.orm import Session

from .models import (
    Stokvel,
    Member,
    Membership,
    Contribution,
    AuditEvent,
    Notification,
)


def seed_demo_data(db: Session) -> None:
    if db.query(Member).count() > 0:
        return

    stokvel = Stokvel(
        name="Ubuntu Savings Circle",
        monthly_amount=500.0,
        contribution_day=25,
    )
    db.add(stokvel)
    db.flush()

    members = [
        Member(full_name="Lerato Mokoena", phone="+27 71 000 1001"),
        Member(full_name="Karabo Dube", phone="+27 71 000 1002"),
        Member(full_name="Naledi Molefe", phone="+27 71 000 1003"),
        Member(full_name="Thabo Maseko", phone="+27 71 000 1004"),
        Member(full_name="Anele Jacobs", phone="+27 71 000 1005"),
    ]
    db.add_all(members)
    db.flush()

    memberships = [
        Membership(member_id=members[0].id, stokvel_id=stokvel.id, role="member", joined_at=date(2026, 1, 10)),
        Membership(member_id=members[1].id, stokvel_id=stokvel.id, role="treasurer", joined_at=date(2026, 1, 10)),
        Membership(member_id=members[2].id, stokvel_id=stokvel.id, role="member", joined_at=date(2026, 2, 3)),
        Membership(member_id=members[3].id, stokvel_id=stokvel.id, role="member", joined_at=date(2026, 2, 6)),
        Membership(member_id=members[4].id, stokvel_id=stokvel.id, role="member", joined_at=date(2026, 3, 1)),
    ]
    db.add_all(memberships)

    # Historical demo contributions for Lerato.
    months = ["2026-04", "2026-05", "2026-06", "2026-07"]
    for i, month in enumerate(months, start=1):
        c = Contribution(
            member_id=members[0].id,
            stokvel_id=stokvel.id,
            amount=500.0,
            contribution_month=month,
            status="verified",
            reference=f"STL-DEMO-{i:03d}",
            created_at=datetime.utcnow() - timedelta(days=(5-i)*30),
            verified_at=datetime.utcnow() - timedelta(days=(5-i)*30),
        )
        db.add(c)

    # Current-month contributions from other members.
    current = [
        (members[1], 500.0, "verified"),
        (members[2], 500.0, "verified"),
        (members[3], 500.0, "verified"),
        (members[4], 500.0, "pending"),
    ]
    for i, (member, amount, status) in enumerate(current, start=20):
        c = Contribution(
            member_id=member.id,
            stokvel_id=stokvel.id,
            amount=amount,
            contribution_month="2026-08",
            status=status,
            reference=f"STL-DEMO-{i:03d}",
            created_at=datetime.utcnow() - timedelta(days=i % 5),
            verified_at=datetime.utcnow() - timedelta(days=i % 5) if status == "verified" else None,
        )
        db.add(c)

    db.add_all([
        AuditEvent(
            stokvel_id=stokvel.id,
            member_id=members[1].id,
            event_type="member_joined",
            message="Karabo joined Ubuntu Savings Circle as treasurer.",
            created_at=datetime.utcnow() - timedelta(days=200),
        ),
        AuditEvent(
            stokvel_id=stokvel.id,
            member_id=members[0].id,
            event_type="contribution_verified",
            message="Lerato's July contribution of R500 was verified.",
            created_at=datetime.utcnow() - timedelta(days=30),
        ),
        AuditEvent(
            stokvel_id=stokvel.id,
            member_id=members[2].id,
            event_type="contribution_verified",
            message="Naledi's August contribution of R500 was verified.",
            created_at=datetime.utcnow() - timedelta(days=2),
        ),
    ])

    db.add_all([
        Notification(
            member_id=members[0].id,
            title="August contribution due",
            body="Your R500 contribution is due on 25 August.",
        ),
        Notification(
            member_id=members[0].id,
            title="Group update",
            body="3 of 5 members have completed the August contribution.",
        ),
    ])

    db.commit()
