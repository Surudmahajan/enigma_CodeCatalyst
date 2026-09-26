"""Imports every ORM model so metadata is complete (Alembic, create_all, relationships)."""

from app.ai.models import AIOutputLog  # noqa: F401
from app.assessment.models import EmissionFactor  # noqa: F401
from app.audit.models import AuditLog  # noqa: F401
from app.auth.models import RefreshToken, UserToken  # noqa: F401
from app.connections.models import Connection  # noqa: F401
from app.documents.models import Document  # noqa: F401
from app.exchanges.models import Exchange  # noqa: F401
from app.impact.models import ImpactRecord  # noqa: F401
from app.materials.models import (  # noqa: F401
    ApplicationType,
    Material,
    MaterialApplication,
    MaterialProperty,
    PropertyDefinition,
)
from app.matching.models import Match, MatchingConfig  # noqa: F401
from app.messaging.models import Conversation, ConversationParticipant, Message, ReadReceipt  # noqa: F401
from app.notifications.models import Notification, PushToken  # noqa: F401
from app.organizations.models import Facility, Location, Organization, OrganizationMember  # noqa: F401
from app.pathways.models import ProcessingMethod, ProcessorCapability  # noqa: F401
from app.requirements.models import Requirement, RequirementPropertyConstraint  # noqa: F401
from app.resources.models import Resource, ResourcePropertyValue  # noqa: F401
from app.users.models import User  # noqa: F401
