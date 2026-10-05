"""DevForge ORM models.

Importing this package registers every table on ``Base.metadata`` — required for
``create_all`` (development/tests) and for Alembic autogenerate.
"""
from app.core.database import Base
from app.models.agent import Agent, Task
from app.models.approval import Approval
from app.models.artifact import Artifact, ArtifactVersion
from app.models.audit import AuditLog
from app.models.conversation import AgentMessage
from app.models.execution import AgentExecution
from app.models.knowledge import KnowledgeChunk
from app.models.project import Project
from app.models.repository import GitOperation, Repository
from app.models.security import SecurityFinding
from app.models.testing import TestResult, TestRun
from app.models.trace import TraceLink
from app.models.user import ProjectMember, User
from app.models.workflow import WorkflowRun, WorkflowState

__all__ = [
    "Base",
    "User",
    "ProjectMember",
    "Project",
    "Agent",
    "Task",
    "WorkflowRun",
    "WorkflowState",
    "Artifact",
    "ArtifactVersion",
    "Approval",
    "AgentMessage",
    "AgentExecution",
    "TestRun",
    "TestResult",
    "SecurityFinding",
    "Repository",
    "GitOperation",
    "AuditLog",
    "TraceLink",
    "KnowledgeChunk",
]
