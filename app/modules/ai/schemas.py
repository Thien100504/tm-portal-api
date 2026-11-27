"""
AI Insights Schemas

Pydantic models for the /api/v1/projects/{id}/ai-insights endpoint.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InsightCard(BaseModel):
    """A single insight card (risk / success / warning / info)."""

    type: str  # "risk" | "success" | "warning" | "info"
    title: str  # fallback text (Vietnamese)
    description: str  # fallback text (Vietnamese)
    metric: str | None = None  # e.g. "32%", "5 tasks", "2 members"
    # i18n keys: the frontend translates them with t(title_key)
    title_key: str | None = None
    description_key: str | None = None
    description_params: dict | None = None  # interpolation params for description_key


class TeamMemberInsight(BaseModel):
    """Workload of one project member."""

    user_id: uuid.UUID
    full_name: str
    task_count: int  # tasks assigned in total
    in_progress_count: int
    overdue_count: int
    workload_level: str  # "low" | "normal" | "high" | "critical"


class ActiveSprintInsight(BaseModel):
    """The active sprint."""

    sprint_id: uuid.UUID
    sprint_name: str
    completion_rate: float  # 0–100
    velocity: int  # number of done tasks
    days_remaining: int | None
    is_on_track: bool


class AIInsightsResponse(BaseModel):
    """Full response of the AI Insights endpoint."""

    project_id: uuid.UUID
    project_name: str
    health_score: int  # 0–100
    health_label: str  # "Excellent" | "Good" | "At risk" | "Critical"
    health_color: str  # "green" | "blue" | "yellow" | "red"
    generated_at: datetime

    # Core task metrics
    total_tasks: int
    done_tasks: int
    in_progress_tasks: int
    review_tasks: int
    todo_tasks: int
    overdue_tasks: int
    blocked_tasks: int
    completion_rate: float  # % done/total

    # Insights cards
    insights: list[InsightCard]

    # Team workload
    team_insights: list[TeamMemberInsight]

    # Sprint
    active_sprint: ActiveSprintInsight | None

    # AI-generated narrative
    ai_summary: str | None  # a 2-3 sentence assessment
    ai_recommendations: list[str]  # 3 concrete recommendations
    ai_powered: bool  # True when the AI API was called


# ── AI Metrics Schemas ──────────────────────────────────────────────


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatMessageInput(BaseModel):
    content: str
    lang: str = "vi"


class AIMetricFeedback(BaseModel):
    status: Literal["applied", "rejected", "modified"]
    feedback_note: str | None = Field(None, max_length=500)


class FeatureStats(BaseModel):
    feature: str
    total_calls: int
    avg_response_ms: float
    applied_count: int
    rejected_count: int
    acceptance_rate: float
    total_input_tokens: int
    total_output_tokens: int


class RecentMetric(BaseModel):
    id: uuid.UUID
    feature: str
    task_id: uuid.UUID | None
    model_used: str
    response_time_ms: int | None
    status: str
    output_data: dict | None
    created_at: datetime


class AIMetricsResponse(BaseModel):
    project_id: uuid.UUID
    total_ai_calls: int
    overall_acceptance_rate: float
    avg_response_ms: float
    total_tokens_used: int
    by_feature: list[FeatureStats]
    recent: list[RecentMetric]


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatSessionResponse(BaseModel):
    id: uuid.UUID
    title: str | None = None
    # empty project_id = a workspace-wide conversation
    project_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatSessionCreate(BaseModel):
    title: str | None = None


class ChatSessionScopeCreate(BaseModel):
    workspace_id: uuid.UUID
    project_id: uuid.UUID | None = None
    title: str | None = Field(None, max_length=255)


class ChatSessionRename(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


class ChatActionDecision(BaseModel):
    confirm: bool
    lang: str = "vi"


class ChatActionResult(BaseModel):
    status: Literal["done", "cancelled"]
    kind: str | None = None
    count: int = 0
    name: str | None = None


class ChatStatusResponse(BaseModel):
    # false: the server has no AI API key, so the assistant cannot answer
    configured: bool
