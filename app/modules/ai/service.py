"""
AI Insights Service

Collects project data → computes the health score and insights → (optionally) calls the AI API.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.config import get_settings
from app.models.ai import AIMetric
from app.models.project import Project, ProjectMember
from app.models.sprint import Sprint
from app.models.task import Task, TaskDependency
from app.models.user import User
from app.modules.ai.schemas import (
    ActiveSprintInsight,
    AIInsightsResponse,
    AIMetricFeedback,
    AIMetricsResponse,
    FeatureStats,
    InsightCard,
    RecentMetric,
    TeamMemberInsight,
)

logger = logging.getLogger(__name__)
settings = get_settings()


# ──────────────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────────────


async def get_ai_insights(
    db: AsyncSession, project_id: UUID, lang: str = "vi"
) -> AIInsightsResponse:
    """Compute the AI insights of a project. lang: 'vi' | 'en'"""

    now = datetime.now(timezone.utc)

    # ── 1. Project info & Workspace type ──────────────────────────────
    from app.models.workspace import Workspace

    project_workspace = (
        await db.execute(
            select(Project, Workspace)
            .outerjoin(Workspace, Project.workspace_id == Workspace.id)
            .where(Project.id == project_id, Project.is_deleted.is_(False))
        )
    ).one_or_none()

    if not project_workspace:
        raise HTTPException(status_code=404, detail="project.not_found")

    project, workspace = project_workspace
    is_personal = workspace is not None and workspace.type == "personal"

    # ── 2. Task metrics ──────────────────────────────────────────────
    base = and_(Task.project_id == project_id, Task.is_deleted.is_(False))

    total_tasks = await db.scalar(select(func.count(Task.id)).where(base)) or 0
    done_tasks = (
        await db.scalar(select(func.count(Task.id)).where(base, Task.status == "done"))
        or 0
    )
    in_progress_tasks = (
        await db.scalar(
            select(func.count(Task.id)).where(base, Task.status == "in_progress")
        )
        or 0
    )
    review_tasks = (
        await db.scalar(
            select(func.count(Task.id)).where(base, Task.status == "review")
        )
        or 0
    )
    todo_tasks = (
        await db.scalar(select(func.count(Task.id)).where(base, Task.status == "todo"))
        or 0
    )

    overdue_tasks = (
        await db.scalar(
            select(func.count(Task.id)).where(
                base,
                Task.deadline.isnot(None),
                Task.deadline < now,
                Task.status != "done",
            )
        )
        or 0
    )

    # Blocked: unfinished tasks with at least one unfinished dependency
    DepTask = aliased(Task, name="dep_task")
    blocked_tasks = (
        await db.scalar(
            select(func.count(Task.id.distinct()))
            .where(
                base,
                Task.status != "done",
            )
            .join(TaskDependency, Task.id == TaskDependency.task_id)
            .join(
                DepTask,
                and_(
                    TaskDependency.depends_on_id == DepTask.id,
                    DepTask.status != "done",
                ),
            )
        )
        or 0
    )

    completion_rate = round(done_tasks / total_tasks * 100, 1) if total_tasks else 0.0

    # ── 3. Active sprint ─────────────────────────────────────────────
    active_sprint_row = (
        await db.execute(
            select(Sprint)
            .where(
                Sprint.project_id == project_id,
                Sprint.status == "active",
                Sprint.is_deleted.is_(False),
            )
            .limit(1)
        )
    ).scalar_one_or_none()

    active_sprint_insight: Optional[ActiveSprintInsight] = None
    active_sprint_rate: Optional[float] = None

    if active_sprint_row:
        sprint_total = (
            await db.scalar(
                select(func.count(Task.id)).where(
                    Task.sprint_id == active_sprint_row.id,
                    Task.is_deleted.is_(False),
                )
            )
            or 0
        )
        sprint_done = (
            await db.scalar(
                select(func.count(Task.id)).where(
                    Task.sprint_id == active_sprint_row.id,
                    Task.status == "done",
                    Task.is_deleted.is_(False),
                )
            )
            or 0
        )

        sprint_rate = (
            round(sprint_done / sprint_total * 100, 1) if sprint_total else 0.0
        )
        active_sprint_rate = sprint_rate

        # Days left
        days_remaining: Optional[int] = None
        is_on_track = True
        if active_sprint_row.end_date:
            end = datetime.combine(
                active_sprint_row.end_date, datetime.min.time()
            ).replace(tzinfo=timezone.utc)
            days_remaining = max(0, (end - now).days)

            # On track: once > 50% of the time has passed, > 50% of tasks must be done
            if active_sprint_row.start_date:
                start = datetime.combine(
                    active_sprint_row.start_date, datetime.min.time()
                ).replace(tzinfo=timezone.utc)
                total_days = max(1, (end - start).days)
                elapsed_pct = min(100, (now - start).days / total_days * 100)
                if elapsed_pct > 50 and sprint_rate < elapsed_pct * 0.7:
                    is_on_track = False

        active_sprint_insight = ActiveSprintInsight(
            sprint_id=active_sprint_row.id,
            sprint_name=active_sprint_row.name,
            completion_rate=sprint_rate,
            velocity=sprint_done,
            days_remaining=days_remaining,
            is_on_track=is_on_track,
        )

    # ── 4. Team workload ─────────────────────────────────────────────
    member_rows = (
        await db.execute(
            select(ProjectMember, User)
            .join(User, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id == project_id)
        )
    ).all()

    # The owner can also be a member
    owner_row = (
        await db.execute(select(User).where(User.id == project.owner_id))
    ).scalar_one_or_none()

    member_user_set = {row.User.id: row.User for row in member_rows}
    if owner_row:
        member_user_set.setdefault(owner_row.id, owner_row)

    team_insights: list[TeamMemberInsight] = []
    workload_counts: list[int] = []

    for uid, user_obj in member_user_set.items():
        m_total = (
            await db.scalar(
                select(func.count(Task.id)).where(
                    Task.project_id == project_id,
                    Task.assignee_id == uid,
                    Task.is_deleted.is_(False),
                    Task.status != "done",
                )
            )
            or 0
        )
        m_ip = (
            await db.scalar(
                select(func.count(Task.id)).where(
                    Task.project_id == project_id,
                    Task.assignee_id == uid,
                    Task.status == "in_progress",
                    Task.is_deleted.is_(False),
                )
            )
            or 0
        )
        m_ov = (
            await db.scalar(
                select(func.count(Task.id)).where(
                    Task.project_id == project_id,
                    Task.assignee_id == uid,
                    Task.deadline.isnot(None),
                    Task.deadline < now,
                    Task.status != "done",
                    Task.is_deleted.is_(False),
                )
            )
            or 0
        )

        level = _workload_level(m_total)
        workload_counts.append(m_total)

        team_insights.append(
            TeamMemberInsight(
                user_id=uid,
                full_name=user_obj.full_name,
                task_count=m_total,
                in_progress_count=m_ip,
                overdue_count=m_ov,
                workload_level=level,
            )
        )

    # ── 5. Health score ──────────────────────────────────────────────
    health_score = _compute_health_score(
        total_tasks=total_tasks,
        done_tasks=done_tasks,
        overdue_tasks=overdue_tasks,
        blocked_tasks=blocked_tasks,
        has_active_sprint=active_sprint_row is not None,
        sprint_rate=active_sprint_rate,
        sprint_on_track=active_sprint_insight.is_on_track
        if active_sprint_insight
        else True,
        workload_counts=workload_counts,
    )
    health_label, health_color = _health_label(health_score)

    # ── 6. Insight cards ─────────────────────────────────────────────
    insights = _build_insights(
        total_tasks=total_tasks,
        done_tasks=done_tasks,
        overdue_tasks=overdue_tasks,
        blocked_tasks=blocked_tasks,
        in_progress_tasks=in_progress_tasks,
        has_active_sprint=active_sprint_row is not None,
        active_sprint=active_sprint_insight,
        team_insights=team_insights,
        completion_rate=completion_rate,
    )

    # ── 7. AI summary (if API key configured) ────────────────────────
    ai_result = await _call_ai(
        project_name=project.name,
        health_score=health_score,
        total_tasks=total_tasks,
        done_tasks=done_tasks,
        overdue_tasks=overdue_tasks,
        blocked_tasks=blocked_tasks,
        active_sprint=active_sprint_insight,
        insights=insights,
        team_insights=team_insights,
        is_personal=is_personal,
        lang=lang,
    )
    ai_summary = ai_result["summary"]
    ai_recommendations = ai_result["recommendations"]
    ai_powered = ai_result["ai_powered"]

    # ── 8. Record AI metric for insights call ────────────────────────
    if ai_powered:
        try:
            metric = AIMetric(
                project_id=project_id,
                feature="insights",
                model_used=ai_result["model"],
                input_tokens=ai_result.get("input_tokens"),
                output_tokens=ai_result.get("output_tokens"),
                response_time_ms=ai_result.get("response_time_ms"),
                output_data={
                    "health_score": health_score,
                    "summary_length": len(ai_summary) if ai_summary else 0,
                    "recommendation_count": len(ai_recommendations),
                },
                status="applied",
            )
            db.add(metric)
            await db.flush()
        except Exception:
            logger.warning("Failed to record insights metric", exc_info=True)

    return AIInsightsResponse(
        project_id=project_id,
        project_name=project.name,
        health_score=health_score,
        health_label=health_label,
        health_color=health_color,
        generated_at=now,
        total_tasks=total_tasks,
        done_tasks=done_tasks,
        in_progress_tasks=in_progress_tasks,
        review_tasks=review_tasks,
        todo_tasks=todo_tasks,
        overdue_tasks=overdue_tasks,
        blocked_tasks=blocked_tasks,
        completion_rate=completion_rate,
        insights=insights,
        team_insights=team_insights,
        active_sprint=active_sprint_insight,
        ai_summary=ai_summary,
        ai_recommendations=ai_recommendations,
        ai_powered=ai_powered,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Private helpers
# ──────────────────────────────────────────────────────────────────────────────


def _workload_level(active_task_count: int) -> str:
    if active_task_count == 0:
        return "low"
    if active_task_count <= 3:
        return "normal"
    if active_task_count <= 6:
        return "high"
    return "critical"


def _compute_health_score(
    total_tasks: int,
    done_tasks: int,
    overdue_tasks: int,
    blocked_tasks: int,
    has_active_sprint: bool,
    sprint_rate: Optional[float],
    sprint_on_track: bool,
    workload_counts: list[int],
) -> int:
    score = 100

    if total_tasks == 0:
        return 75  # neutral while there are no tasks

    # Overdue penalty: -3 points per 5% overdue rate (max -25)
    overdue_rate = overdue_tasks / total_tasks
    score -= min(25, int(overdue_rate * 60))

    # Blocked penalty: -3 points per blocked task (max -15)
    score -= min(15, blocked_tasks * 3)

    # Sprint: no sprint while the project is running → -10
    if not has_active_sprint and done_tasks < total_tasks:
        score -= 10

    # Sprint behind schedule → -15
    if not sprint_on_track:
        score -= 15

    # Low completion rate although the project has been running for a while → -10
    if total_tasks >= 5 and done_tasks / total_tasks < 0.2:
        score -= 10

    # Team imbalance: max workload > 3x min (and min > 0) → -5
    active_counts = [c for c in workload_counts if c > 0]
    if len(active_counts) >= 2:
        if max(active_counts) > min(active_counts) * 3 + 2:
            score -= 5

    return max(0, min(100, score))


def _health_label(score: int) -> tuple[str, str]:
    """Returns (i18n_key, color). Frontend translates the key via ai_insights.health_label.{key}."""
    if score >= 80:
        return "excellent", "green"
    if score >= 60:
        return "good", "blue"
    if score >= 40:
        return "at_risk", "yellow"
    return "critical", "red"


def _insight(
    card_type: str,
    title_key: str,
    description_key: str,
    metric: Optional[str] = None,
    description_params: Optional[dict] = None,
) -> "InsightCard":
    """
    Helper: build an InsightCard where title/description fall back to the i18n key itself.
    This avoids any hardcoded natural language on the backend — the frontend is fully
    responsible for translating via t(title_key) / t(description_key, params).
    """
    return InsightCard(
        type=card_type,
        # Use the key as the fallback value — language-neutral and debuggable
        title=title_key,
        description=description_key,
        metric=metric,
        title_key=title_key,
        description_key=description_key,
        description_params=description_params,
    )


def _build_insights(
    total_tasks: int,
    done_tasks: int,
    overdue_tasks: int,
    blocked_tasks: int,
    in_progress_tasks: int,
    has_active_sprint: bool,
    active_sprint: Optional[ActiveSprintInsight],
    team_insights: list[TeamMemberInsight],
    completion_rate: float,
) -> list[InsightCard]:
    """
    Build the list of InsightCards.
    All natural language is delegated to the frontend via title_key / description_key.
    No Vietnamese (or any human language) is hardcoded here.
    """
    cards: list[InsightCard] = []

    if total_tasks == 0:
        cards.append(
            _insight(
                card_type="info",
                title_key="ai_insights.cards.no_tasks.title",
                description_key="ai_insights.cards.no_tasks.description",
            )
        )
        return cards

    # ── Completion rate ───────────────────────────────────────────────
    completion_pct = int(completion_rate)
    if completion_rate >= 70:
        cards.append(
            _insight(
                card_type="success",
                title_key="ai_insights.cards.completion_good.title",
                description_key="ai_insights.cards.completion_good.description",
                metric=f"{completion_pct}%",
                description_params={"rate": completion_pct},
            )
        )
    elif completion_rate < 30 and total_tasks >= 5:
        cards.append(
            _insight(
                card_type="warning",
                title_key="ai_insights.cards.completion_low.title",
                description_key="ai_insights.cards.completion_low.description",
                metric=f"{completion_pct}%",
                description_params={"rate": completion_pct},
            )
        )

    # ── Overdue ───────────────────────────────────────────────────────
    if overdue_tasks > 0:
        overdue_pct = int(overdue_tasks / total_tasks * 100)
        card_type = "risk" if overdue_pct > 20 else "warning"
        cards.append(
            _insight(
                card_type=card_type,
                title_key="ai_insights.cards.overdue.title",
                description_key="ai_insights.cards.overdue.description",
                metric=str(overdue_tasks),
                description_params={"count": overdue_tasks, "pct": overdue_pct},
            )
        )
    else:
        cards.append(
            _insight(
                card_type="success",
                title_key="ai_insights.cards.no_overdue.title",
                description_key="ai_insights.cards.no_overdue.description",
            )
        )

    # ── Blocked ───────────────────────────────────────────────────────
    if blocked_tasks > 0:
        cards.append(
            _insight(
                card_type="warning",
                title_key="ai_insights.cards.blocked.title",
                description_key="ai_insights.cards.blocked.description",
                metric=str(blocked_tasks),
                description_params={"count": blocked_tasks},
            )
        )

    # ── Sprint ────────────────────────────────────────────────────────
    if not has_active_sprint:
        cards.append(
            _insight(
                card_type="info",
                title_key="ai_insights.cards.no_sprint.title",
                description_key="ai_insights.cards.no_sprint.description",
            )
        )
    elif active_sprint:
        sprint_pct = int(active_sprint.completion_rate)
        if not active_sprint.is_on_track:
            cards.append(
                _insight(
                    card_type="risk",
                    title_key="ai_insights.cards.sprint_behind.title",
                    description_key="ai_insights.cards.sprint_behind.description",
                    metric=f"{sprint_pct}%",
                    description_params={
                        "name": active_sprint.sprint_name,
                        "rate": sprint_pct,
                    },
                )
            )
        elif (
            active_sprint.days_remaining is not None
            and active_sprint.days_remaining <= 2
        ):
            cards.append(
                _insight(
                    card_type="warning",
                    title_key="ai_insights.cards.sprint_ending.title",
                    description_key="ai_insights.cards.sprint_ending.description",
                    # metric is a plain number — frontend formats with unit via i18n
                    metric=str(active_sprint.days_remaining),
                    description_params={
                        "name": active_sprint.sprint_name,
                        "days": active_sprint.days_remaining,
                        "rate": sprint_pct,
                    },
                )
            )
        else:
            cards.append(
                _insight(
                    card_type="success",
                    title_key="ai_insights.cards.sprint_on_track.title",
                    description_key="ai_insights.cards.sprint_on_track.description",
                    metric=f"{sprint_pct}%",
                    description_params={
                        "name": active_sprint.sprint_name,
                        "rate": sprint_pct,
                    },
                )
            )

    # ── Team workload ─────────────────────────────────────────────────
    critical_members = [m for m in team_insights if m.workload_level == "critical"]
    if critical_members:
        names = ", ".join(m.full_name.split()[0] for m in critical_members[:2])
        cards.append(
            _insight(
                card_type="warning",
                title_key="ai_insights.cards.overloaded_member.title",
                description_key="ai_insights.cards.overloaded_member.description",
                metric=str(len(critical_members)),
                description_params={"names": names, "count": len(critical_members)},
            )
        )

    overdue_members = [m for m in team_insights if m.overdue_count > 2]
    if overdue_members:
        member_name = overdue_members[0].full_name.split()[0]
        cards.append(
            _insight(
                card_type="risk",
                title_key="ai_insights.cards.member_overdue.title",
                description_key="ai_insights.cards.member_overdue.description",
                metric=str(overdue_members[0].overdue_count),
                description_params={
                    "name": member_name,
                    "count": overdue_members[0].overdue_count,
                },
            )
        )

    return cards


async def _call_ai(
    project_name: str,
    health_score: int,
    total_tasks: int,
    done_tasks: int,
    overdue_tasks: int,
    blocked_tasks: int,
    active_sprint: Optional[ActiveSprintInsight],
    insights: list[InsightCard],
    team_insights: list[TeamMemberInsight],
    is_personal: bool = False,
    lang: str = "vi",
) -> dict:
    """Call NVIDIA / OpenAI API to generate narrative. Returns dict with summary, recommendations, timing, tokens."""

    api_key = settings.NVIDIA_API_KEY or settings.OPENAI_API_KEY
    if not api_key:
        return {
            "summary": None,
            "recommendations": [],
            "ai_powered": False,
            "model": "",
        }

    try:
        from openai import AsyncOpenAI

        # Use title_key (language-neutral) to build risk/positive context for the AI prompt.
        # Map i18n keys to readable English labels used inside the prompt.
        KEY_LABEL_EN = {
            "ai_insights.cards.completion_good.title": "good completion rate",
            "ai_insights.cards.completion_low.title": "low completion rate",
            "ai_insights.cards.overdue.title": "overdue tasks",
            "ai_insights.cards.no_overdue.title": "no overdue tasks",
            "ai_insights.cards.blocked.title": "blocked tasks",
            "ai_insights.cards.no_sprint.title": "no active sprint",
            "ai_insights.cards.sprint_behind.title": "sprint behind schedule",
            "ai_insights.cards.sprint_ending.title": "sprint ending soon",
            "ai_insights.cards.sprint_on_track.title": "sprint on track",
            "ai_insights.cards.overloaded_member.title": "overloaded members",
            "ai_insights.cards.member_overdue.title": "member with overdue tasks",
            "ai_insights.cards.no_tasks.title": "no tasks",
        }
        KEY_LABEL_VI = {
            "ai_insights.cards.completion_good.title": "good completion rate",
            "ai_insights.cards.completion_low.title": "low completion rate",
            "ai_insights.cards.overdue.title": "overdue tasks",
            "ai_insights.cards.no_overdue.title": "no overdue tasks",
            "ai_insights.cards.blocked.title": "blocked tasks",
            "ai_insights.cards.no_sprint.title": "no sprint",
            "ai_insights.cards.sprint_behind.title": "sprint behind schedule",
            "ai_insights.cards.sprint_ending.title": "sprint ending soon",
            "ai_insights.cards.sprint_on_track.title": "sprint on track",
            "ai_insights.cards.overloaded_member.title": "overloaded member",
            "ai_insights.cards.member_overdue.title": "member with overdue tasks",
            "ai_insights.cards.no_tasks.title": "no tasks yet",
        }

        is_vi = lang == "vi"
        label_map = KEY_LABEL_VI if is_vi else KEY_LABEL_EN

        def _label(key: str) -> str:
            return label_map.get(key, key.split(".")[-1].replace("_", " "))

        risk_items = [
            _label(c.title_key)
            for c in insights
            if c.title_key and c.type in ("risk", "warning")
        ]
        positive_items = [
            _label(c.title_key) for c in insights if c.title_key and c.type == "success"
        ]

        # ── Build lang-aware prompts ──────────────────────────────────────

        if is_personal:
            if is_vi:
                prompt = f"""You are an intelligent personal productivity assistant. Analyze the personal task data and provide a concise evaluation written in Vietnamese.

TASK DATA:
- Project/category name: {project_name}
- Productivity score: {health_score}/100
- Tasks: {total_tasks} total | {done_tasks} done | {overdue_tasks} overdue | {blocked_tasks} blocked
- Risks found: {", ".join(risk_items) if risk_items else "None"}
- Strengths: {", ".join(positive_items) if positive_items else "None"}

Reply with EXACTLY this JSON format, all text values in Vietnamese (no markdown, no text outside the JSON):
{{"summary": "a 2-3 sentence overall assessment of the work, encouraging and specific", "recommendations": ["concrete, feasible action 1", "action 2", "action 3"]}}"""
            else:
                prompt = f"""You are an intelligent personal productivity assistant. Analyze the personal task data and provide a concise evaluation in English.

TASK DATA:
- Project/Category: {project_name}
- Productivity score: {health_score}/100
- Tasks: {total_tasks} total | {done_tasks} done | {overdue_tasks} overdue | {blocked_tasks} blocked
- Risks detected: {", ".join(risk_items) if risk_items else "None"}
- Positive points: {", ".join(positive_items) if positive_items else "None"}

Reply EXACTLY in the following JSON format (no markdown, no extra text outside JSON):
{{"summary": "2-3 sentences evaluating overall work status, encouraging and specific", "recommendations": ["Actionable recommendation 1", "Actionable recommendation 2", "Actionable recommendation 3"]}}"""
        else:
            # Build context string
            if is_vi:
                sprint_info = "No active sprint"
                no_risk_label = "None"
                on_track_label = "on track"
                off_track_label = "NOT on track"
            else:
                sprint_info = "No active sprint"
                no_risk_label = "None"
                on_track_label = "on track"
                off_track_label = "BEHIND SCHEDULE"

            if active_sprint:
                sprint_info = (
                    f"Sprint '{active_sprint.sprint_name}': "
                    f"{active_sprint.completion_rate:.0f}% done, "
                    f"{active_sprint.days_remaining or 'N/A'} days left, "
                    f"{on_track_label if active_sprint.is_on_track else off_track_label}"
                )

            team_summary_parts = []
            for m in team_insights[:5]:
                team_summary_parts.append(
                    f"{m.full_name}: {m.task_count} active tasks, {m.overdue_count} overdue ({m.workload_level})"
                )

            if is_vi:
                prompt = f"""You are an Agile software project management expert. Analyze the project data and provide a concise evaluation written in Vietnamese.

PROJECT DATA:
- Name: {project_name}
- Health score: {health_score}/100
- Tasks: {total_tasks} total | {done_tasks} done | {overdue_tasks} overdue | {blocked_tasks} blocked
- {sprint_info}
- Risks found: {", ".join(risk_items) if risk_items else no_risk_label}
- Strengths: {", ".join(positive_items) if positive_items else no_risk_label}
- Team ({len(team_insights)} members):
{chr(10).join("  " + s for s in team_summary_parts)}

Reply with EXACTLY this JSON format, all text values in Vietnamese (no markdown, no text outside the JSON):
{{"summary": "a 2-3 sentence overall assessment of the project, professional and specific", "recommendations": ["concrete, feasible action 1", "action 2", "action 3"]}}"""
            else:
                prompt = f"""You are an Agile software project management expert. Analyze the project data and provide a concise evaluation in English.

PROJECT DATA:
- Name: {project_name}
- Health score: {health_score}/100
- Tasks: {total_tasks} total | {done_tasks} done | {overdue_tasks} overdue | {blocked_tasks} blocked
- {sprint_info}
- Risks detected: {", ".join(risk_items) if risk_items else no_risk_label}
- Positive points: {", ".join(positive_items) if positive_items else no_risk_label}
- Team ({len(team_insights)} members):
{chr(10).join("  " + s for s in team_summary_parts)}

Reply EXACTLY in the following JSON format (no markdown, no extra text outside JSON):
{{"summary": "2-3 sentences evaluating overall project status, professional and specific", "recommendations": ["Actionable recommendation 1", "Actionable recommendation 2", "Actionable recommendation 3"]}}"""

        import time as _time

        if settings.NVIDIA_API_KEY:
            client = AsyncOpenAI(
                base_url=settings.NVIDIA_BASE_URL,
                api_key=settings.NVIDIA_API_KEY,
            )
            model = "meta/llama-3.1-8b-instruct"
        else:
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            model = "gpt-4o-mini"

        t0 = _time.monotonic()
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.4,
        )
        elapsed_ms = int((_time.monotonic() - t0) * 1000)
        usage = response.usage

        content = response.choices[0].message.content or ""
        if "```" in content:
            import re

            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
            if match:
                content = match.group(1)

        data = json.loads(content)
        summary = data.get("summary", "")
        recommendations = data.get("recommendations", [])

        if not isinstance(recommendations, list):
            recommendations = []

        return {
            "summary": summary,
            "recommendations": recommendations[:3],
            "ai_powered": True,
            "model": model,
            "response_time_ms": elapsed_ms,
            "input_tokens": usage.prompt_tokens if usage else None,
            "output_tokens": usage.completion_tokens if usage else None,
        }

    except Exception as exc:
        logger.warning("AI insights call failed: %s", exc)
        return {
            "summary": None,
            "recommendations": [],
            "ai_powered": False,
            "model": "",
        }


# ──────────────────────────────────────────────────────────────────────────────
# AI Metrics
# ──────────────────────────────────────────────────────────────────────────────


async def get_ai_metrics(db: AsyncSession, project_id: UUID) -> AIMetricsResponse:
    base = AIMetric.project_id == project_id

    total = await db.scalar(select(func.count(AIMetric.id)).where(base)) or 0

    avg_ms = (
        await db.scalar(select(func.avg(AIMetric.response_time_ms)).where(base)) or 0.0
    )

    applied = (
        await db.scalar(
            select(func.count(AIMetric.id)).where(base, AIMetric.status == "applied")
        )
        or 0
    )
    with_feedback = (
        await db.scalar(
            select(func.count(AIMetric.id)).where(
                base, AIMetric.status.in_(["applied", "rejected"])
            )
        )
        or 0
    )

    overall_rate = round(applied / with_feedback * 100, 1) if with_feedback else 0.0

    total_input = (
        await db.scalar(
            select(func.coalesce(func.sum(AIMetric.input_tokens), 0)).where(base)
        )
        or 0
    )
    total_output = (
        await db.scalar(
            select(func.coalesce(func.sum(AIMetric.output_tokens), 0)).where(base)
        )
        or 0
    )

    features_rows = (
        await db.execute(
            select(
                AIMetric.feature,
                func.count(AIMetric.id).label("total"),
                func.avg(AIMetric.response_time_ms).label("avg_ms"),
                func.sum(case((AIMetric.status == "applied", 1), else_=0)).label(
                    "applied"
                ),
                func.sum(case((AIMetric.status == "rejected", 1), else_=0)).label(
                    "rejected"
                ),
                func.coalesce(func.sum(AIMetric.input_tokens), 0).label("inp"),
                func.coalesce(func.sum(AIMetric.output_tokens), 0).label("out"),
            )
            .where(base)
            .group_by(AIMetric.feature)
        )
    ).all()

    by_feature = []
    for row in features_rows:
        fb = (row.applied or 0) + (row.rejected or 0)
        by_feature.append(
            FeatureStats(
                feature=row.feature,
                total_calls=row.total,
                avg_response_ms=round(float(row.avg_ms or 0), 1),
                applied_count=row.applied or 0,
                rejected_count=row.rejected or 0,
                acceptance_rate=round((row.applied or 0) / fb * 100, 1) if fb else 0.0,
                total_input_tokens=row.inp,
                total_output_tokens=row.out,
            )
        )

    recent_rows = (
        (
            await db.execute(
                select(AIMetric)
                .where(base)
                .order_by(AIMetric.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )

    recent = [
        RecentMetric(
            id=m.id,
            feature=m.feature,
            task_id=m.task_id,
            model_used=m.model_used,
            response_time_ms=m.response_time_ms,
            status=m.status,
            output_data=m.output_data,
            created_at=m.created_at,
        )
        for m in recent_rows
    ]

    return AIMetricsResponse(
        project_id=project_id,
        total_ai_calls=total,
        overall_acceptance_rate=overall_rate,
        avg_response_ms=round(float(avg_ms), 1),
        total_tokens_used=total_input + total_output,
        by_feature=by_feature,
        recent=recent,
    )


async def update_metric_feedback(
    db: AsyncSession, metric_id: UUID, body: AIMetricFeedback
) -> dict:
    metric = await db.get(AIMetric, metric_id)
    if not metric:
        raise HTTPException(status_code=404, detail="metric.not_found")

    metric.status = body.status
    metric.feedback_note = body.feedback_note
    metric.feedback_at = datetime.now(timezone.utc)

    # If user rejects a breakdown, soft-delete the AI-generated subtasks
    if body.status == "rejected" and metric.feature == "breakdown" and metric.task_id:
        from app.models.task import Task
        from sqlalchemy import update as sa_update

        result = await db.execute(
            sa_update(Task)
            .where(
                Task.parent_task_id == metric.task_id,
                Task.is_deleted.is_(False),
            )
            .values(
                is_deleted=True,
                deleted_at=datetime.now(timezone.utc),
            )
            .returning(Task.id)
        )
        deleted_ids = [row[0] for row in result.fetchall()]
        logger.info(
            "Rejected breakdown metric=%s task=%s → soft-deleted %d subtasks: %s",
            metric_id,
            metric.task_id,
            len(deleted_ids),
            deleted_ids,
        )

    await db.commit()

    return {"id": str(metric.id), "status": metric.status}
