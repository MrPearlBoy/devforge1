"""Structured output contract of the Requirement Agent."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Requirement(BaseModel):
    id: str = Field(description="Stable identifier such as REQ-001")
    title: str
    description: str
    priority: str = Field(default="MEDIUM", description="HIGH | MEDIUM | LOW")
    category: str = Field(default="Functional")
    acceptance_criteria: list[str] = Field(default_factory=list)


class NonFunctionalRequirement(BaseModel):
    id: str
    category: str = Field(description="Performance | Security | Usability | Reliability | "
                                     "Maintainability | Scalability | Compliance")
    description: str
    target: str = Field(default="", description="Measurable target, if determinable")


class UserRole(BaseModel):
    id: str
    name: str
    description: str
    capabilities: list[str] = Field(default_factory=list)


class UseCase(BaseModel):
    id: str
    name: str
    actors: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    main_flow: list[str] = Field(default_factory=list)
    alternative_flow: list[str] = Field(default_factory=list)
    requirement_refs: list[str] = Field(default_factory=list)


class OpenQuestion(BaseModel):
    question: str
    why_it_matters: str = ""
    blocks_progress: bool = False


class RequirementsSpec(BaseModel):
    """The full requirement analysis produced before human approval."""

    project_overview: str
    scope_in: list[str] = Field(default_factory=list)
    scope_out: list[str] = Field(default_factory=list)
    functional_requirements: list[Requirement] = Field(default_factory=list)
    non_functional_requirements: list[NonFunctionalRequirement] = Field(default_factory=list)
    user_roles: list[UserRole] = Field(default_factory=list)
    use_cases: list[UseCase] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    out_of_scope_risks: list[str] = Field(default_factory=list)
