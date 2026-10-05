"""Enumerations shared across models, schemas and services.

Stored as short strings so the schema stays portable between PostgreSQL and
SQLite and so migrations never require enum type surgery.
"""
from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.value


class Role(StrEnum):
    ADMIN = "ADMIN"
    DEVELOPER = "DEVELOPER"
    ARCHITECT = "ARCHITECT"
    TESTER = "TESTER"
    PROJECT_MANAGER = "PROJECT_MANAGER"


class ProjectRole(StrEnum):
    OWNER = "OWNER"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"


class Stage(StrEnum):
    """SDLC stages driven by the orchestration graph."""

    REQUIREMENTS = "REQUIREMENTS"
    ARCHITECTURE = "ARCHITECTURE"
    DEVELOPMENT = "DEVELOPMENT"
    TESTING = "TESTING"
    SECURITY = "SECURITY"
    DOCUMENTATION = "DOCUMENTATION"
    DELIVERY = "DELIVERY"


STAGE_ORDER: list[Stage] = [
    Stage.REQUIREMENTS,
    Stage.ARCHITECTURE,
    Stage.DEVELOPMENT,
    Stage.TESTING,
    Stage.SECURITY,
    Stage.DOCUMENTATION,
    Stage.DELIVERY,
]


class StageStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class WorkflowStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AgentStatus(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    WAITING = "WAITING"
    SKIPPED = "SKIPPED"


class ExecutionTrigger(StrEnum):
    WORKFLOW = "WORKFLOW"
    CHAT = "CHAT"
    MANUAL = "MANUAL"
    RETRY = "RETRY"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    CANCELLED = "CANCELLED"


class ApprovalDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class ArtifactType(StrEnum):
    REQUIREMENTS = "REQUIREMENTS"
    ARCHITECTURE = "ARCHITECTURE"
    ARCHITECTURE_DIAGRAM = "ARCHITECTURE_DIAGRAM"
    CHANGE_SET = "CHANGE_SET"
    SOURCE_FILE = "SOURCE_FILE"
    TEST_PLAN = "TEST_PLAN"
    TEST_RESULTS = "TEST_RESULTS"
    SECURITY_REPORT = "SECURITY_REPORT"
    DOCUMENTATION = "DOCUMENTATION"
    DELIVERY_PLAN = "DELIVERY_PLAN"
    CHAT_NOTE = "CHAT_NOTE"


class ArtifactStatus(StrEnum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class MessageRole(StrEnum):
    USER = "USER"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"


class TestStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class FindingStatus(StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FIXED = "FIXED"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class TaskStatus(StrEnum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    DONE = "DONE"


class TaskPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class GitOperationType(StrEnum):
    INIT = "INIT"
    CLONE = "CLONE"
    PULL = "PULL"
    BRANCH = "BRANCH"
    COMMIT = "COMMIT"
    PUSH = "PUSH"
    PULL_REQUEST = "PULL_REQUEST"
    STATUS = "STATUS"


class GitOperationStatus(StrEnum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class KnowledgeSource(StrEnum):
    REQUIREMENTS = "REQUIREMENTS"
    ARCHITECTURE = "ARCHITECTURE"
    SOURCE_CODE = "SOURCE_CODE"
    TEST_RESULTS = "TEST_RESULTS"
    SECURITY_FINDINGS = "SECURITY_FINDINGS"
    DOCUMENTATION = "DOCUMENTATION"
    CONVERSATION = "CONVERSATION"
    PROJECT_META = "PROJECT_META"


class TraceNodeType(StrEnum):
    REQUIREMENT = "REQUIREMENT"
    ARCHITECTURE = "ARCHITECTURE"
    CODE = "CODE"
    TEST = "TEST"
    SECURITY = "SECURITY"
    DOCUMENTATION = "DOCUMENTATION"


class ActorType(StrEnum):
    USER = "USER"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"
