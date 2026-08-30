import os
import secrets
from calendar import monthrange
from datetime import datetime, date

from fastapi import FastAPI, Depends, HTTPException, Form
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import Base, engine, SessionLocal, get_db
from .models import (
    Stokvel,
    Member,
    Membership,
    Contribution,
    AuditEvent,
    Notification,
)
from .schemas import (
    CreateStokvelRequest,
    JoinStokvelRequest,
    CreateContributionRequest,
)
from .seed import seed_demo_data


# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="StockLink API",
    version="2.0.0",
    description="StockLink stokvel prototype with dynamic monthly contribution cycles.",
)


origins_raw = os.getenv("CORS_ORIGINS", "*")

origins = (
    ["*"]
    if origins_raw == "*"
    else [x.strip() for x in origins_raw.split(",")]
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False if origins == ["*"] else True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# DATABASE STARTUP
# =========================================================

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    try:
        seed_demo_data(db)

    finally:
        db.close()


# =========================================================
# DEMO MONTH ENGINE
# =========================================================

# 0 = actual/current month
# 1 = next month
# 2 = month after that
DEMO_MONTH_OFFSET = 0


def shift_month(year: int, month: int, offset: int):
    absolute_month = year * 12 + (month - 1) + offset

    new_year = absolute_month // 12
    new_month = absolute_month % 12 + 1

    return new_year, new_month


def current_cycle():
    today = date.today()

    year, month = shift_month(
        today.year,
        today.month,
        DEMO_MONTH_OFFSET,
    )

    cycle_date = date(year, month, 1)

    return {
        "code": cycle_date.strftime("%Y-%m"),
        "label": cycle_date.strftime("%B %Y"),
        "year": year,
        "month": month,
    }


def due_label(stokvel: Stokvel):
    cycle = current_cycle()

    last_day = monthrange(
        cycle["year"],
        cycle["month"],
    )[1]

    contribution_day = min(
        stokvel.contribution_day,
        last_day,
    )

    due = date(
        cycle["year"],
        cycle["month"],
        contribution_day,
    )

    return f"{due.day} {due.strftime('%b')}"


def pretty_month(month_code: str):
    try:
        parsed = datetime.strptime(
            month_code,
            "%Y-%m",
        )

        return parsed.strftime("%b %Y")

    except ValueError:
        return month_code


@app.get("/demo/cycle")
def get_demo_cycle():
    cycle = current_cycle()

    return {
        "month_code": cycle["code"],
        "month_label": cycle["label"],
        "offset": DEMO_MONTH_OFFSET,
    }


@app.post("/demo/advance-month")
def advance_demo_month():
    global DEMO_MONTH_OFFSET

    DEMO_MONTH_OFFSET += 1

    cycle = current_cycle()

    return {
        "status": "advanced",
        "month_code": cycle["code"],
        "month_label": cycle["label"],
        "offset": DEMO_MONTH_OFFSET,
    }


@app.post("/demo/reset-cycle")
def reset_demo_cycle():
    global DEMO_MONTH_OFFSET

    DEMO_MONTH_OFFSET = 0

    cycle = current_cycle()

    return {
        "status": "reset",
        "month_code": cycle["code"],
        "month_label": cycle["label"],
        "offset": DEMO_MONTH_OFFSET,
    }


# =========================================================
# HELPERS
# =========================================================

def money(value: float | None) -> float:
    return round(float(value or 0), 2)


def member_name(
    db: Session,
    member_id: int | None,
) -> str:

    if member_id is None:
        return "System"

    member = db.get(
        Member,
        member_id,
    )

    return (
        member.full_name
        if member
        else "Unknown member"
    )


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "stocklink-api",
        "cycle": current_cycle()["label"],
    }


# =========================================================
# MEMBER DASHBOARD
# =========================================================

@app.get("/demo/summary")
def demo_summary(
    member_id: int = 1,
    stokvel_id: int = 1,
    db: Session = Depends(get_db),
):

    cycle = current_cycle()

    member = db.get(
        Member,
        member_id,
    )

    stokvel = db.get(
        Stokvel,
        stokvel_id,
    )

    if not member or not stokvel:
        raise HTTPException(
            404,
            "Demo member or stokvel not found",
        )

    membership = (
        db.query(Membership)
        .filter(
            Membership.member_id == member_id,
            Membership.stokvel_id == stokvel_id,
            Membership.is_active == True,
        )
        .first()
    )

    if not membership:
        raise HTTPException(
            404,
            "Member does not belong to this stokvel",
        )

    # All money ever verified
    total_verified = (
        db.query(
            func.coalesce(
                func.sum(Contribution.amount),
                0,
            )
        )
        .filter(
            Contribution.stokvel_id == stokvel_id,
            Contribution.status == "verified",
        )
        .scalar()
    )

    # Member's lifetime total
    member_total = (
        db.query(
            func.coalesce(
                func.sum(Contribution.amount),
                0,
            )
        )
        .filter(
            Contribution.member_id == member_id,
            Contribution.stokvel_id == stokvel_id,
            Contribution.status == "verified",
        )
        .scalar()
    )

    # Has member paid ACTIVE month?
    current_verified = (
        db.query(Contribution)
        .filter(
            Contribution.member_id == member_id,
            Contribution.stokvel_id == stokvel_id,
            Contribution.contribution_month
            == cycle["code"],
            Contribution.status == "verified",
        )
        .first()
    )

    member_count = (
        db.query(Membership)
        .filter(
            Membership.stokvel_id == stokvel_id,
            Membership.is_active == True,
        )
        .count()
    )

    paid_count = (
        db.query(Contribution.member_id)
        .filter(
            Contribution.stokvel_id == stokvel_id,
            Contribution.contribution_month
            == cycle["code"],
            Contribution.status == "verified",
        )
        .distinct()
        .count()
    )

    return {
        "member": {
            "id": member.id,
            "name": member.full_name,
            "role": membership.role,
        },

        "stokvel": {
            "id": stokvel.id,
            "name": stokvel.name,
            "monthly_amount":
                stokvel.monthly_amount,
            "contribution_day":
                stokvel.contribution_day,
        },

        # lifetime ledger
        "group_balance":
            money(total_verified),

        "member_total":
            money(member_total),

        # ACTIVE MONTH
        "current_month":
            cycle["label"],

        "current_month_code":
            cycle["code"],

        "current_month_paid":
            bool(current_verified),

        "members_paid":
            paid_count,

        "members_total":
            member_count,

        "next_due_label":
            due_label(stokvel),
    }


# =========================================================
# STOKVEL
# =========================================================

@app.get("/stokvels/{stokvel_id}")
def get_stokvel(
    stokvel_id: int,
    db: Session = Depends(get_db),
):

    stokvel = db.get(
        Stokvel,
        stokvel_id,
    )

    if not stokvel:
        raise HTTPException(
            404,
            "Stokvel not found",
        )

    return stokvel


@app.post("/stokvels")
def create_stokvel(
    payload: CreateStokvelRequest,
    db: Session = Depends(get_db),
):

    creator = db.get(
        Member,
        payload.creator_member_id,
    )

    if not creator:
        raise HTTPException(
            404,
            "Creator member not found",
        )

    stokvel = Stokvel(
        name=payload.name,
        monthly_amount=
            payload.monthly_amount,
        contribution_day=
            payload.contribution_day,
    )

    db.add(stokvel)
    db.flush()

    db.add(
        Membership(
            member_id=creator.id,
            stokvel_id=stokvel.id,
            role="treasurer",
        )
    )

    db.add(
        AuditEvent(
            stokvel_id=stokvel.id,
            member_id=creator.id,
            event_type="stokvel_created",
            message=(
                f"{creator.full_name} "
                f"created {stokvel.name}."
            ),
        )
    )

    db.commit()
    db.refresh(stokvel)

    return stokvel


@app.post("/stokvels/{stokvel_id}/join")
def join_stokvel(
    stokvel_id: int,
    payload: JoinStokvelRequest,
    db: Session = Depends(get_db),
):

    stokvel = db.get(
        Stokvel,
        stokvel_id,
    )

    member = db.get(
        Member,
        payload.member_id,
    )

    if not stokvel or not member:
        raise HTTPException(
            404,
            "Stokvel or member not found",
        )

    exists = (
        db.query(Membership)
        .filter(
            Membership.stokvel_id
            == stokvel_id,

            Membership.member_id
            == payload.member_id,
        )
        .first()
    )

    if exists:

        return {
            "status":
                "already_joined",

            "membership_id":
                exists.id,
        }

    membership = Membership(
        member_id=member.id,
        stokvel_id=stokvel.id,
        role="member",
    )

    db.add(membership)

    db.add(
        AuditEvent(
            stokvel_id=stokvel.id,
            member_id=member.id,
            event_type="member_joined",
            message=(
                f"{member.full_name} "
                f"joined {stokvel.name}."
            ),
        )
    )

    db.commit()
    db.refresh(membership)

    return {
        "status": "joined",
        "membership_id":
            membership.id,
    }


# =========================================================
# MEMBERS
# =========================================================

@app.get("/stokvels/{stokvel_id}/members")
def get_members(
    stokvel_id: int,
    db: Session = Depends(get_db),
):

    cycle = current_cycle()

    memberships = (
        db.query(Membership)
        .filter(
            Membership.stokvel_id
            == stokvel_id,

            Membership.is_active
            == True,
        )
        .all()
    )

    result = []

    for membership in memberships:

        verified = (
            db.query(Contribution)
            .filter(
                Contribution.member_id
                == membership.member_id,

                Contribution.stokvel_id
                == stokvel_id,

                Contribution.contribution_month
                == cycle["code"],

                Contribution.status
                == "verified",
            )
            .first()
        )

        status = (
            "paid"
            if verified
            else "outstanding"
        )

        result.append(
            {
                "id":
                    membership.member.id,

                "name":
                    membership.member.full_name,

                "role":
                    membership.role,

                # Keep this for existing
                # frontend compatibility.
                "august_status":
                    status,

                # New correct field.
                "current_status":
                    status,

                "current_month":
                    cycle["label"],

                "joined_at":
                    membership.joined_at.isoformat(),
            }
        )

    return result


# =========================================================
# CONTRIBUTION HISTORY
# =========================================================

@app.get("/members/{member_id}/contributions")
def get_member_contributions(
    member_id: int,
    stokvel_id: int = 1,
    db: Session = Depends(get_db),
):

    items = (
        db.query(Contribution)
        .filter(
            Contribution.member_id
            == member_id,

            Contribution.stokvel_id
            == stokvel_id,
        )
        .order_by(
            Contribution.created_at.desc()
        )
        .all()
    )

    return [
        {
            "id":
                item.id,

            "amount":
                money(item.amount),

            "month":
                item.contribution_month,

            "month_label":
                pretty_month(
                    item.contribution_month
                ),

            "status":
                item.status,

            "reference":
                item.reference,

            "created_at":
                item.created_at.isoformat(),

            "verified_at":
                (
                    item.verified_at.isoformat()
                    if item.verified_at
                    else None
                ),
        }

        for item in items
    ]


# =========================================================
# MOBILE CONTRIBUTION
# =========================================================

@app.post("/contributions")
def create_contribution(
    payload: CreateContributionRequest,
    db: Session = Depends(get_db),
):

    cycle = current_cycle()

    member = db.get(
        Member,
        payload.member_id,
    )

    stokvel = db.get(
        Stokvel,
        payload.stokvel_id,
    )

    if not member or not stokvel:
        raise HTTPException(
            404,
            "Member or stokvel not found",
        )

    membership = (
        db.query(Membership)
        .filter(
            Membership.member_id
            == payload.member_id,

            Membership.stokvel_id
            == payload.stokvel_id,

            Membership.is_active
            == True,
        )
        .first()
    )

    if not membership:
        raise HTTPException(
            400,
            "Member does not belong to this stokvel",
        )

    # IMPORTANT:
    # We ignore the old hardcoded month
    # sent by the mobile app.
    # Backend controls the active cycle.
    contribution_month = cycle["code"]

    duplicate = (
        db.query(Contribution)
        .filter(
            Contribution.member_id
            == payload.member_id,

            Contribution.stokvel_id
            == payload.stokvel_id,

            Contribution.contribution_month
            == contribution_month,

            Contribution.status.in_(
                [
                    "pending",
                    "verified",
                ]
            ),
        )
        .first()
    )

    if duplicate:

        return {
            "id":
                duplicate.id,

            "status":
                duplicate.status,

            "reference":
                duplicate.reference,

            "month":
                duplicate.contribution_month,

            "message":
                "Existing contribution returned.",
        }

    reference = (
        f"STL-"
        f"{secrets.token_hex(4).upper()}"
    )

    contribution = Contribution(
        member_id=payload.member_id,
        stokvel_id=payload.stokvel_id,
        amount=payload.amount,
        contribution_month=
            contribution_month,
        status="pending",
        reference=reference,
    )

    db.add(contribution)

    db.add(
        AuditEvent(
            stokvel_id=
                payload.stokvel_id,

            member_id=
                payload.member_id,

            event_type=
                "contribution_started",

            message=(
                f"{member.full_name} "
                f"started an "
                f"R{payload.amount:.0f} "
                f"{cycle['label']} "
                f"contribution."
            ),
        )
    )

    db.commit()
    db.refresh(contribution)

    return {
        "id":
            contribution.id,

        "status":
            contribution.status,

        "reference":
            contribution.reference,

        "month":
            contribution.contribution_month,

        "message":
            "Mock payment initiated.",
    }


@app.post(
    "/contributions/"
    "{contribution_id}/verify"
)
def verify_contribution(
    contribution_id: int,
    db: Session = Depends(get_db),
):

    contribution = db.get(
        Contribution,
        contribution_id,
    )

    if not contribution:
        raise HTTPException(
            404,
            "Contribution not found",
        )

    if contribution.status == "verified":

        return {
            "id":
                contribution.id,

            "status":
                contribution.status,

            "reference":
                contribution.reference,

            "month":
                contribution.contribution_month,
        }

    contribution.status = "verified"
    contribution.verified_at = datetime.utcnow()

    name = member_name(
        db,
        contribution.member_id,
    )

    db.add(
        AuditEvent(
            stokvel_id=
                contribution.stokvel_id,

            member_id=
                contribution.member_id,

            event_type=
                "contribution_verified",

            message=(
                f"{name}'s "
                f"R{contribution.amount:.0f} "
                f"{pretty_month(contribution.contribution_month)} "
                f"contribution was verified."
            ),
        )
    )

    db.add(
        Notification(
            member_id=
                contribution.member_id,

            title=
                "Contribution verified",

            body=(
                f"Your "
                f"R{contribution.amount:.0f} "
                f"contribution is now "
                f"visible in the "
                f"group ledger."
            ),
        )
    )

    db.commit()

    return {
        "id":
            contribution.id,

        "status":
            contribution.status,

        "reference":
            contribution.reference,

        "month":
            contribution.contribution_month,

        "verified_at":
            contribution.verified_at.isoformat(),
    }


# =========================================================
# AUDIT TRAIL
# =========================================================

@app.get("/stokvels/{stokvel_id}/audit")
def get_audit(
    stokvel_id: int,
    db: Session = Depends(get_db),
):

    events = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.stokvel_id
            == stokvel_id
        )
        .order_by(
            AuditEvent.created_at.desc()
        )
        .limit(50)
        .all()
    )

    return [
        {
            "id":
                event.id,

            "type":
                event.event_type,

            "message":
                event.message,

            "created_at":
                event.created_at.isoformat(),
        }

        for event in events
    ]


# =========================================================
# NOTIFICATIONS
# =========================================================

@app.get("/notifications")
def notifications(
    member_id: int = 1,
    db: Session = Depends(get_db),
):

    items = (
        db.query(Notification)
        .filter(
            Notification.member_id
            == member_id
        )
        .order_by(
            Notification.created_at.desc()
        )
        .limit(20)
        .all()
    )

    return [
        {
            "id":
                item.id,

            "title":
                item.title,

            "body":
                item.body,

            "is_read":
                item.is_read,

            "created_at":
                item.created_at.isoformat(),
        }

        for item in items
    ]


# =========================================================
# TREASURER
# =========================================================

@app.get(
    "/treasurer/"
    "{stokvel_id}/dashboard"
)
def treasurer_dashboard(
    stokvel_id: int,
    db: Session = Depends(get_db),
):

    cycle = current_cycle()

    stokvel = db.get(
        Stokvel,
        stokvel_id,
    )

    if not stokvel:
        raise HTTPException(
            404,
            "Stokvel not found",
        )

    member_count = (
        db.query(Membership)
        .filter(
            Membership.stokvel_id
            == stokvel_id,

            Membership.is_active
            == True,
        )
        .count()
    )

    paid_member_ids = (
        db.query(
            Contribution.member_id
        )
        .filter(
            Contribution.stokvel_id
            == stokvel_id,

            Contribution.contribution_month
            == cycle["code"],

            Contribution.status
            == "verified",
        )
        .distinct()
        .all()
    )

    paid_ids = {
        row[0]
        for row in paid_member_ids
    }

    memberships = (
        db.query(Membership)
        .filter(
            Membership.stokvel_id
            == stokvel_id,

            Membership.is_active
            == True,
        )
        .all()
    )

    outstanding = [
        {
            "id":
                m.member.id,

            "name":
                m.member.full_name,

            "amount_due":
                stokvel.monthly_amount,
        }

        for m in memberships

        if m.member_id not in paid_ids
    ]

    # Current month's amount only
    month_total = (
        db.query(
            func.coalesce(
                func.sum(Contribution.amount),
                0,
            )
        )
        .filter(
            Contribution.stokvel_id
            == stokvel_id,

            Contribution.contribution_month
            == cycle["code"],

            Contribution.status
            == "verified",
        )
        .scalar()
    )

    # Lifetime ledger balance
    all_time_total = (
        db.query(
            func.coalesce(
                func.sum(Contribution.amount),
                0,
            )
        )
        .filter(
            Contribution.stokvel_id
            == stokvel_id,

            Contribution.status
            == "verified",
        )
        .scalar()
    )

    return {
        "stokvel_name":
            stokvel.name,

        "current_month":
            cycle["label"],

        "current_month_code":
            cycle["code"],

        "members_total":
            member_count,

        "members_paid":
            len(paid_ids),

        "members_outstanding":
            len(outstanding),

        "month_total":
            money(month_total),

        "all_time_total":
            money(all_time_total),

        "outstanding":
            outstanding,
    }


# =========================================================
# USSD HELPERS
# =========================================================

def _demo_member_for_ussd(
    db: Session,
    phone_number: str,
) -> Member:

    compact = (
        phone_number
        or ""
    ).replace(
        " ",
        "",
    ).replace(
        "-",
        "",
    )

    for candidate in (
        db.query(Member).all()
    ):

        saved = (
            candidate.phone
            or ""
        ).replace(
            " ",
            "",
        ).replace(
            "-",
            "",
        )

        if saved == compact:
            return candidate

    # Sandbox fallback
    return db.get(
        Member,
        1,
    )


def _member_membership(
    db: Session,
    member_id: int,
):

    return (
        db.query(Membership)
        .filter(
            Membership.member_id
            == member_id,

            Membership.is_active
            == True,
        )
        .order_by(
            Membership.id.asc()
        )
        .first()
    )


def _current_demo_contribution(
    db: Session,
    member_id: int,
    stokvel_id: int,
):

    cycle = current_cycle()

    return (
        db.query(Contribution)
        .filter(
            Contribution.member_id
            == member_id,

            Contribution.stokvel_id
            == stokvel_id,

            Contribution.contribution_month
            == cycle["code"],

            Contribution.status.in_(
                [
                    "pending",
                    "verified",
                ]
            ),
        )
        .order_by(
            Contribution.id.desc()
        )
        .first()
    )


# =========================================================
# AFRICA'S TALKING USSD
# =========================================================

@app.post(
    "/ussd",
    response_class=PlainTextResponse,
)
def ussd_callback(
    sessionId: str = Form(""),
    serviceCode: str = Form(""),
    phoneNumber: str = Form(""),
    text: str = Form(""),
    db: Session = Depends(get_db),
):

    cycle = current_cycle()

    member = _demo_member_for_ussd(
        db,
        phoneNumber,
    )

    if not member:
        return (
            "END StockLink demo "
            "member not found."
        )

    membership = _member_membership(
        db,
        member.id,
    )

    if not membership:
        return (
            "END You are not linked "
            "to a StockLink group."
        )

    stokvel = membership.stokvel

    inputs = (
        []
        if not text
        else text.split("*")
    )

    # =====================================================
    # MAIN MENU
    # =====================================================

    if len(inputs) == 0:

        first_name = (
            member.full_name
            .split(" ")[0]
        )

        return (
            f"CON StockLink - Hi {first_name}\n"
            f"{cycle['label']}\n"
            "1. My balance\n"
            f"2. Contribute R{stokvel.monthly_amount:.0f}\n"
            "3. Contribution history\n"
            "4. Group status\n"
            "5. Help"
        )

    # =====================================================
    # BALANCE
    # =====================================================

    if inputs == ["1"]:

        member_total = (
            db.query(
                func.coalesce(
                    func.sum(
                        Contribution.amount
                    ),
                    0,
                )
            )
            .filter(
                Contribution.member_id
                == member.id,

                Contribution.stokvel_id
                == stokvel.id,

                Contribution.status
                == "verified",
            )
            .scalar()
        )

        current = (
            _current_demo_contribution(
                db,
                member.id,
                stokvel.id,
            )
        )

        status = (
            "Paid"
            if (
                current
                and current.status
                == "verified"
            )
            else "Outstanding"
        )

        return (
            "END StockLink balance\n"
            f"Verified total: "
            f"R{money(member_total):.0f}\n"
            f"{cycle['label']}: "
            f"{status}"
        )

    # =====================================================
    # CONTRIBUTE
    # =====================================================

    if inputs == ["2"]:

        current = (
            _current_demo_contribution(
                db,
                member.id,
                stokvel.id,
            )
        )

        if (
            current
            and current.status
            == "verified"
        ):

            return (
                f"END Your "
                f"{cycle['label']} "
                f"R{stokvel.monthly_amount:.0f} "
                f"contribution is "
                f"already verified.\n"
                f"Ref: {current.reference}"
            )

        return (
            f"CON {cycle['label']}\n"
            f"Contribute "
            f"R{stokvel.monthly_amount:.0f} "
            f"to\n"
            f"{stokvel.name}?\n"
            "1. Confirm\n"
            "2. Cancel"
        )

    # =====================================================
    # CANCEL
    # =====================================================

    if inputs == [
        "2",
        "2",
    ]:

        return (
            "END Contribution cancelled. "
            "No money was moved."
        )

    # =====================================================
    # CONFIRM PAYMENT
    # =====================================================

    if inputs == [
        "2",
        "1",
    ]:

        contribution = (
            _current_demo_contribution(
                db,
                member.id,
                stokvel.id,
            )
        )

        if (
            contribution
            and contribution.status
            == "verified"
        ):

            return (
                "END Already verified.\n"
                f"R{contribution.amount:.0f}\n"
                f"{cycle['label']}\n"
                f"Ref: "
                f"{contribution.reference}"
            )

        if not contribution:

            contribution = Contribution(
                member_id=
                    member.id,

                stokvel_id=
                    stokvel.id,

                amount=
                    stokvel.monthly_amount,

                # ACTIVE MONTH
                contribution_month=
                    cycle["code"],

                status=
                    "pending",

                reference=(
                    "USSD-"
                    + secrets
                    .token_hex(4)
                    .upper()
                ),
            )

            db.add(contribution)
            db.flush()

            db.add(
                AuditEvent(
                    stokvel_id=
                        stokvel.id,

                    member_id=
                        member.id,

                    event_type=
                        "ussd_contribution_started",

                    message=(
                        f"{member.full_name} "
                        f"started an "
                        f"R{stokvel.monthly_amount:.0f} "
                        f"{cycle['label']} "
                        f"contribution via USSD."
                    ),
                )
            )

        # Mock banking payment confirmation.
        contribution.status = "verified"

        contribution.verified_at = (
            datetime.utcnow()
        )

        db.add(
            AuditEvent(
                stokvel_id=
                    stokvel.id,

                member_id=
                    member.id,

                event_type=
                    "contribution_verified",

                message=(
                    f"{member.full_name}'s "
                    f"R{contribution.amount:.0f} "
                    f"{cycle['label']} "
                    f"USSD contribution "
                    f"was verified."
                ),
            )
        )

        db.add(
            Notification(
                member_id=
                    member.id,

                title=(
                    f"{cycle['label']} "
                    f"contribution verified"
                ),

                body=(
                    f"Your "
                    f"R{contribution.amount:.0f} "
                    f"contribution is now "
                    f"visible in the "
                    f"StockLink shared ledger."
                ),
            )
        )

        db.commit()

        return (
            "END Payment verified!\n"
            f"{cycle['label']}\n"
            f"R{contribution.amount:.0f} "
            f"recorded.\n"
            f"Ref: "
            f"{contribution.reference}"
        )

    # =====================================================
    # CONTRIBUTION HISTORY
    # =====================================================

    if inputs == ["3"]:

        recent = (
            db.query(Contribution)
            .filter(
                Contribution.member_id
                == member.id,

                Contribution.stokvel_id
                == stokvel.id,

                Contribution.status
                == "verified",
            )
            .order_by(
                Contribution.verified_at.desc(),
                Contribution.id.desc(),
            )
            .limit(4)
            .all()
        )

        if not recent:

            return (
                "END No verified "
                "contributions yet."
            )

        lines = [
            "END Recent contributions"
        ]

        for item in recent:

            lines.append(
                f"{pretty_month(item.contribution_month)}: "
                f"R{item.amount:.0f} - Paid"
            )

        return "\n".join(lines)

    # =====================================================
    # GROUP STATUS
    # =====================================================

    if inputs == ["4"]:

        member_count = (
            db.query(Membership)
            .filter(
                Membership.stokvel_id
                == stokvel.id,

                Membership.is_active
                == True,
            )
            .count()
        )

        paid_count = (
            db.query(
                Contribution.member_id
            )
            .filter(
                Contribution.stokvel_id
                == stokvel.id,

                Contribution.contribution_month
                == cycle["code"],

                Contribution.status
                == "verified",
            )
            .distinct()
            .count()
        )

        group_total = (
            db.query(
                func.coalesce(
                    func.sum(
                        Contribution.amount
                    ),
                    0,
                )
            )
            .filter(
                Contribution.stokvel_id
                == stokvel.id,

                Contribution.status
                == "verified",
            )
            .scalar()
        )

        return (
            f"END {stokvel.name}\n"
            f"{cycle['label']}: "
            f"{paid_count}/{member_count} paid\n"
            f"Verified ledger: "
            f"R{money(group_total):.0f}"
        )

    # =====================================================
    # HELP
    # =====================================================

    if inputs == ["5"]:

        return (
            "END StockLink works "
            "without mobile data.\n"
            "Use USSD to view or make "
            "your monthly contribution."
        )

    return (
        "END Invalid option. "
        "Please dial StockLink again."
    )