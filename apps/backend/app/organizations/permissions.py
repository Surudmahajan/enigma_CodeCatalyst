"""Organization-level permissions.

The single source of truth for which organization role may do what. Routes
declare the permission they need; they never compare roles themselves.
"""

from enum import StrEnum

from app.organizations.models import MemberRole

# Higher number = more privilege.
ROLE_RANK: dict[MemberRole, int] = {
    MemberRole.VIEWER: 10,
    MemberRole.MEMBER: 20,
    MemberRole.MANAGER: 30,
    MemberRole.ADMIN: 40,
    MemberRole.OWNER: 50,
}


class Permission(StrEnum):
    VIEW = "VIEW"                          # read org data, listings, matches, messages
    MANAGE_LISTINGS = "MANAGE_LISTINGS"    # create/edit resources & requirements
    SEND_MESSAGES = "SEND_MESSAGES"        # chat and upload documents in connected channels
    MANAGE_CONNECTIONS = "MANAGE_CONNECTIONS"  # request/accept/reject/revoke connections
    MANAGE_EXCHANGES = "MANAGE_EXCHANGES"  # create exchanges and change their status
    MANAGE_ORGANIZATION = "MANAGE_ORGANIZATION"  # profile, facilities, members
    TRANSFER_OWNERSHIP = "TRANSFER_OWNERSHIP"


MINIMUM_ROLE: dict[Permission, MemberRole] = {
    Permission.VIEW: MemberRole.VIEWER,
    Permission.MANAGE_LISTINGS: MemberRole.MEMBER,
    Permission.SEND_MESSAGES: MemberRole.MEMBER,
    Permission.MANAGE_CONNECTIONS: MemberRole.MANAGER,
    Permission.MANAGE_EXCHANGES: MemberRole.MANAGER,
    Permission.MANAGE_ORGANIZATION: MemberRole.ADMIN,
    Permission.TRANSFER_OWNERSHIP: MemberRole.OWNER,
}


def role_has_permission(role: MemberRole, permission: Permission) -> bool:
    return ROLE_RANK[role] >= ROLE_RANK[MINIMUM_ROLE[permission]]


def permissions_for(role: MemberRole) -> list[str]:
    return [p.value for p in Permission if role_has_permission(role, p)]
