"""Authentication and organization-authorization dependencies.

Every protected business operation resolves, in order:

    authenticated user -> organization membership -> permission -> ownership

Ownership of a specific record is checked in the service layer against the
``OrgContext`` returned here.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import ForbiddenError, UnauthorizedError, ValidationFailedError
from app.core.security import decode_token
from app.organizations.models import MemberStatus, Organization, OrganizationMember
from app.organizations.permissions import Permission, role_has_permission
from app.users.models import User

_bearer = HTTPBearer(auto_error=False, description="JWT access token from /auth/login")

DB = Annotated[Session, Depends(get_db)]


def resolve_user_from_token(db: Session, token: str) -> User:
    payload = decode_token(token, "access")
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise UnauthorizedError("Invalid authentication token.", code="INVALID_TOKEN") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("This account is not active.", code="ACCOUNT_INACTIVE")
    return user


def get_current_user(
    db: DB,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError()
    return resolve_user_from_token(db, credentials.credentials)


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_platform_admin(user: CurrentUser) -> User:
    if not user.is_platform_admin:
        raise ForbiddenError("Platform administrator access is required.", code="ADMIN_REQUIRED")
    return user


PlatformAdmin = Annotated[User, Depends(get_platform_admin)]


@dataclass(frozen=True)
class OrgContext:
    user: User
    organization: Organization
    membership: OrganizationMember

    @property
    def org_id(self) -> uuid.UUID:
        return self.organization.id

    def can(self, permission: Permission) -> bool:
        return role_has_permission(self.membership.role, permission)

    def require(self, permission: Permission) -> None:
        if not self.can(permission):
            raise ForbiddenError(
                f"Your role ({self.membership.role}) does not allow this action.",
                code="INSUFFICIENT_ROLE",
                details={"required_permission": permission.value},
            )
        if not self.organization.is_active and permission != Permission.VIEW:
            raise ForbiddenError("This organization is suspended.", code="ORGANIZATION_SUSPENDED")


def resolve_org_context(db: Session, user: User, organization_id: uuid.UUID | None) -> OrgContext:
    query = select(OrganizationMember).where(
        OrganizationMember.user_id == user.id, OrganizationMember.status == MemberStatus.ACTIVE
    )
    if organization_id is not None:
        query = query.where(OrganizationMember.organization_id == organization_id)
    membership = db.scalars(query.order_by(OrganizationMember.created_at)).first()
    if membership is None:
        if organization_id is not None:
            # Same response whether the org exists or not: no membership enumeration.
            raise ForbiddenError("You are not a member of this organization.", code="NOT_A_MEMBER")
        raise ForbiddenError("Create or join an organization first.", code="NO_ORGANIZATION")
    return OrgContext(user=user, organization=membership.organization, membership=membership)


def get_org_context(
    db: DB,
    user: CurrentUser,
    x_organization_id: Annotated[str | None, Header(description="Organization to act as")] = None,
) -> OrgContext:
    org_id = None
    if x_organization_id:
        try:
            org_id = uuid.UUID(x_organization_id)
        except ValueError as exc:
            raise ValidationFailedError("X-Organization-Id must be a UUID.") from exc
    return resolve_org_context(db, user, org_id)


Org = Annotated[OrgContext, Depends(get_org_context)]
