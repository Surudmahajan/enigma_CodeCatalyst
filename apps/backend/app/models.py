"""Imports every ORM model so metadata is complete (Alembic, create_all, relationships)."""

from app.audit.models import AuditLog  # noqa: F401
from app.auth.models import RefreshToken, UserToken  # noqa: F401
from app.materials.models import (  # noqa: F401
    ApplicationType,
    Material,
    MaterialApplication,
    MaterialProperty,
    PropertyDefinition,
)
from app.organizations.models import Facility, Location, Organization, OrganizationMember  # noqa: F401
from app.requirements.models import Requirement, RequirementPropertyConstraint  # noqa: F401
from app.resources.models import Resource, ResourcePropertyValue  # noqa: F401
from app.users.models import User  # noqa: F401
