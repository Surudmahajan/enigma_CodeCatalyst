import uuid
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.common.listings import PropertyImportance
from app.materials.models import PhysicalState, PropertyDataType


class PropertyDefinitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    unit: str | None
    data_type: PropertyDataType
    description: str | None
    valid_min: Decimal | None
    valid_max: Decimal | None


class MaterialPropertyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    property: PropertyDefinitionOut
    typical_min: Decimal | None
    typical_max: Decimal | None
    note: str | None


class MaterialSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    canonical_name: str
    category: str
    subcategory: str | None
    physical_state: PhysicalState


class MaterialOut(MaterialSummary):
    description: str | None
    synonyms: list[str]
    properties: list[MaterialPropertyOut]


class ApplicationTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    description: str | None
    applicable_industry_sectors: list[str]


class RequiredPropertyRule(BaseModel):
    property_key: str
    min: float | None = None
    max: float | None = None
    importance: PropertyImportance = PropertyImportance.REQUIRED


class MaterialApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    material: MaterialSummary
    application_type: ApplicationTypeOut
    description: str | None
    required_properties: list[dict[str, Any]]
    source_note: str | None


class CategoryOut(BaseModel):
    category: str
    subcategories: list[str]
    material_count: int


# --- Admin management inputs -------------------------------------------------------------

class MaterialPropertyIn(BaseModel):
    property_key: str
    typical_min: Decimal | None = None
    typical_max: Decimal | None = None
    note: str | None = None


class MaterialIn(BaseModel):
    canonical_name: str = Field(min_length=2, max_length=160)
    category: str = Field(min_length=2, max_length=80)
    subcategory: str | None = Field(default=None, max_length=80)
    physical_state: PhysicalState
    description: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    properties: list[MaterialPropertyIn] = Field(default_factory=list)


class MaterialUpdate(BaseModel):
    category: str | None = Field(default=None, min_length=2, max_length=80)
    subcategory: str | None = None
    physical_state: PhysicalState | None = None
    description: str | None = None
    synonyms: list[str] | None = None
    is_active: bool | None = None
    properties: list[MaterialPropertyIn] | None = None


class PropertyDefinitionIn(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=1, max_length=120)
    unit: str | None = Field(default=None, max_length=32)
    data_type: PropertyDataType = PropertyDataType.NUMERIC
    description: str | None = None
    valid_min: Decimal | None = None
    valid_max: Decimal | None = None
    aliases: list[str] = Field(default_factory=list)


class ApplicationTypeIn(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=2, max_length=160)
    description: str | None = None
    applicable_industry_sectors: list[str] = Field(default_factory=list)


class MaterialApplicationIn(BaseModel):
    material_id: uuid.UUID
    application_key: str
    description: str | None = None
    required_properties: list[RequiredPropertyRule] = Field(default_factory=list)
    source_note: str | None = None


class ClassificationRequest(BaseModel):
    text: str = Field(min_length=3, max_length=2000, examples=["Granulated slag from our blast furnace, 2k t/month"])


class ClassificationSuggestion(BaseModel):
    material: MaterialSummary
    confidence: float = Field(ge=0, le=1)
    reasons: list[str]
    source: Literal["KNOWLEDGE_BASE", "SEMANTIC", "AI_MODEL"]


class ClassificationResponse(BaseModel):
    suggestions: list[ClassificationSuggestion]
    note: str = "Suggestions only. Confirm the correct material before publishing."
