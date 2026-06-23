"""Importing all model modules so Base.metadata sees them at alembic time."""

from app.models.attachment import TaskAttachment
from app.models.custom_field import CustomFieldDefinition, TaskCustomFieldValue
from app.models.dependency import TaskDependency
from app.models.notification import Notification, NotificationPreferences
from app.models.project import Project, ProjectMember
from app.models.push_subscription import PushSubscription
from app.models.rate_limit import RateLimit
from app.models.section import Section
from app.models.shadow import ShadowTenant, ShadowUser
from app.models.share import PublicShareToken
from app.models.sync_state import SyncState
from app.models.task import (
    Task,
    TaskActivity,
    TaskComment,
    TaskLabel,
    TaskLabelAssignment,
    TaskWatcher,
)

__all__ = [
    "CustomFieldDefinition",
    "Notification",
    "NotificationPreferences",
    "Project",
    "ProjectMember",
    "PublicShareToken",
    "PushSubscription",
    "RateLimit",
    "Section",
    "ShadowTenant",
    "ShadowUser",
    "SyncState",
    "Task",
    "TaskActivity",
    "TaskAttachment",
    "TaskComment",
    "TaskCustomFieldValue",
    "TaskDependency",
    "TaskLabel",
    "TaskLabelAssignment",
    "TaskWatcher",
]
