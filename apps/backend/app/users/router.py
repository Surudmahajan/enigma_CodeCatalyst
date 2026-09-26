from fastapi import APIRouter

from app.core.dependencies import DB, CurrentUser
from app.organizations.models import MemberStatus
from app.organizations.permissions import permissions_for
from app.users.schemas import MembershipSummary, MeOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


def build_me(user) -> MeOut:
    memberships = [
        MembershipSummary(
            organization_id=m.organization_id,
            organization_name=m.organization.display_name,
            operating_mode=m.organization.operating_mode,
            verification_status=m.organization.verification_status,
            role=m.role,
            permissions=permissions_for(m.role),
        )
        for m in user.memberships
        if m.status == MemberStatus.ACTIVE
    ]
    return MeOut(
        id=user.id, email=user.email, phone=user.phone, first_name=user.first_name, last_name=user.last_name,
        is_verified=user.is_verified, is_platform_admin=user.is_platform_admin, created_at=user.created_at,
        memberships=memberships,
    )


@router.get("/me", response_model=MeOut, summary="Current user with organization memberships")
def get_me(user: CurrentUser, db: DB) -> MeOut:
    db.refresh(user)
    return build_me(user)


@router.patch("/me", response_model=MeOut)
def update_me(body: UserUpdate, user: CurrentUser, db: DB) -> MeOut:
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return build_me(user)
