"""
AI Insights Schemas

Pydantic models for the /api/v1/projects/{id}/ai-insights endpoint.
"""

import uuid
from datetime import datetime
from typing import Literal, List, Optional

from pydantic import BaseModel, Field


class InsightCard(BaseModel):
    """A single insight card (risk / success / warning / info)."""

    type: str  # "risk" | "success" | "warning" | "info"
    title: str  # fallback text (Vietnamese)
    description: str  # fallback text (Vietnamese)
    metric: Optional[str] = None  # e.g. "32%", "5 tasks", "2 members"
    # i18n keys: the frontend translates them with t(title_key)
    title_key: Optional[str] = None
    description_key: Optional[str] = None
    description_params: Optional[dict] = (
        None  # interpolation params for description_key
    )


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
    days_remaining: Optional[int]
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
    insights: List[InsightCard]

    # Team workload
    team_insights: List[TeamMemberInsight]

    # Sprint
    active_sprint: Optional[ActiveSprintInsight]

    # AI-generated narrative
    ai_summary: Optional[str]  # a 2-3 sentence assessment
    ai_recommendations: List[str]  # 3 concrete recommendations
    ai_powered: bool  # True when the AI API was called


# ── AI Metrics Schemas ──────────────────────────────────────────────


class AIMetricFeedback(BaseModel):
    status: Literal["applied", "rejected", "modified"]
    feedback_note: Optional[str] = Field(None, max_length=500)


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
    task_id: Optional[uuid.UUID]
    model_used: str
    response_time_ms: Optional[int]
    status: str
    output_data: Optional[dict]
    created_at: datetime


class AIMetricsResponse(BaseModel):
    project_id: uuid.UUID
    total_ai_calls: int
    overall_acceptance_rate: float
    avg_response_ms: float
    total_tokens_used: int
    by_feature: List[FeatureStats]
    recent: List[RecentMetric]
