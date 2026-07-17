"""Importing all model modules so Base.metadata sees them at alembic time."""

from app.models.attachment import TaskAttachment
from app.models.audience import Audience, AudienceMember, AudienceRule
from app.models.audit import AuditLog
from app.models.custom_field import CustomFieldDefinition, TaskCustomFieldValue
from app.models.dependency import TaskDependency
from app.models.employee_profile import EmployeeProfile, TuStoreAssignment
from app.models.engagement import Favorite, SearchQueryLog
from app.models.learning_settings import LearningSettings
from app.models.library import (
    LibraryMaterial,
    LibrarySection,
    MaterialAcknowledgement,
    MaterialVersion,
    ViewHistory,
)
from app.models.news import NewsAcknowledgement, NewsComment, NewsPost, NewsReaction
from app.models.notification import Notification, NotificationPreferences
from app.models.org import (
    Department,
    Franchisee,
    FranchiseeGroup,
    FranchiseeGroupMember,
    Position,
    PositionGroup,
    PositionGroupMember,
    Store,
    StoreGroup,
    StoreGroupMember,
    UserGroup,
    UserGroupMember,
)
from app.models.project import Project, ProjectMember
from app.models.push_subscription import PushSubscription
from app.models.rate_limit import RateLimit
from app.models.search_document import SearchDocument, TextExtractionJob
from app.models.section import Section
from app.models.shadow import ShadowTenant, ShadowUser
from app.models.share import PublicShareToken
from app.models.survey import (
    Survey,
    SurveyAnswer,
    SurveyAnswerSet,
    SurveyParticipation,
    SurveyQuestion,
)
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
    "Audience",
    "AudienceMember",
    "AudienceRule",
    "AuditLog",
    "CustomFieldDefinition",
    "Department",
    "EmployeeProfile",
    "Favorite",
    "Franchisee",
    "FranchiseeGroup",
    "FranchiseeGroupMember",
    "LearningSettings",
    "LibraryMaterial",
    "LibrarySection",
    "MaterialAcknowledgement",
    "MaterialVersion",
    "NewsAcknowledgement",
    "NewsComment",
    "NewsPost",
    "NewsReaction",
    "Notification",
    "NotificationPreferences",
    "Position",
    "PositionGroup",
    "PositionGroupMember",
    "Project",
    "ProjectMember",
    "PublicShareToken",
    "PushSubscription",
    "RateLimit",
    "SearchDocument",
    "SearchQueryLog",
    "Section",
    "ShadowTenant",
    "ShadowUser",
    "Store",
    "StoreGroup",
    "StoreGroupMember",
    "Survey",
    "SurveyAnswer",
    "SurveyAnswerSet",
    "SurveyParticipation",
    "SurveyQuestion",
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
    "TextExtractionJob",
    "TuStoreAssignment",
    "ViewHistory",
    "UserGroup",
    "UserGroupMember",
]
