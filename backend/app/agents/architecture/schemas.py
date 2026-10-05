"""Structured output contract of the Architecture Agent."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ArchitectureComponent(BaseModel):
    id: str = Field(description="Stable id such as ARCH-001")
    name: str
    layer: str = Field(description="presentation | application | domain | data | platform")
    responsibility: str
    technology: str = ""
    interfaces: list[str] = Field(default_factory=list)
    requirement_refs: list[str] = Field(default_factory=list)


class DataField(BaseModel):
    name: str
    type: str = "string"
    required: bool = False
    description: str = ""


class DataEntity(BaseModel):
    name: str
    table: str
    fields: list[DataField] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    requirement_refs: list[str] = Field(default_factory=list)


class ApiEndpoint(BaseModel):
    method: str
    path: str
    purpose: str
    auth: str = "Bearer JWT required"
    request: str = ""
    response: str = ""
    component_ref: str = ""
    requirement_refs: list[str] = Field(default_factory=list)


class ArchitectureDecision(BaseModel):
    id: str
    decision: str
    rationale: str
    alternatives: list[str] = Field(default_factory=list)
    consequences: str = ""


class ModuleSpec(BaseModel):
    path: str
    purpose: str
    component_ref: str = ""


class ArchitectureSpec(BaseModel):
    overview: str
    architecture_style: str = "Layered modular monolith"
    tech_stack: dict[str, str] = Field(default_factory=dict)
    components: list[ArchitectureComponent] = Field(default_factory=list)
    data_model: list[DataEntity] = Field(default_factory=list)
    api_endpoints: list[ApiEndpoint] = Field(default_factory=list)
    integrations: list[str] = Field(default_factory=list)
    security_requirements: list[str] = Field(default_factory=list)
    deployment: list[str] = Field(default_factory=list)
    modules: list[ModuleSpec] = Field(default_factory=list)
    decisions: list[ArchitectureDecision] = Field(default_factory=list)
    diagram_mermaid: str = ""
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
