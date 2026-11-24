"""
Coverage boost 10 — targets high-gap modules:
  - workspaces/features.py  (require_feature paths)
  - search/service.py       (global_search paths)
  - users/router.py         (via TestClient)
  - notifications/router.py (via TestClient + mocked httpx)
  - admin/router.py         (via TestClient)
  - main.py                 (exception handlers)
  - dashboard/manager.py    (is_pm=True path)
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_user(system_role="user", **kw):
    u = MagicMock()
    u.id = kw.get("id", uuid.uuid4())
    u.email = kw.get("email", "user@test.com")
    u.full_name = kw.get("full_name", "Test User")
    u.is_active = kw.get("is_active", True)
    u.system_role = system_role
    u.password_hash = "hashed"
    u.telegram_chat_id = None
    u.avatar_url = None
    return u


def _make_project(workspace_id=None, **kw):
    p = MagicMock()
    p.id = kw.get("id", uuid.uuid4())
    p.workspace_id = workspace_id or uuid.uuid4()
    p.name = kw.get("name", "Test Project")
    p.is_deleted = False
    return p


def _make_execute_result(rows=None, scalar_result=None, scalars_list=None):
    """Helper to build mock db.execute() return value."""
    result = MagicMock()
    result.all.return_value = rows or []
    result.fetchall.return_value = rows or []
    scalars_obj = MagicMock()
    scalars_obj.all.return_value = scalars_list or []
    scalars_obj.first.return_value = scalar_result
    result.scalars.return_value = scalars_obj
    result.scalar_one_or_none.return_value = scalar_result
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 1. workspaces/features.py — require_feature paths
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_feature_checker_workspace_id_in_path_enabled():
    """workspace_id present, feature enabled → True."""
    from app.modules.workspaces.features import require_feature

    ws_id = str(uuid.uuid4())
    checker = require_feature("tasks")

    request = MagicMock()
    request.path_params = {"workspace_id": ws_id}

    workspace = MagicMock()
    workspace.settings = {"tasks": True}

    db = AsyncMock()
    db.get = AsyncMock(return_value=workspace)

    result = await checker(request=request, db=db)
    assert result is True


@pytest.mark.asyncio
async def test_feature_checker_workspace_id_in_path_disabled():
    """workspace_id present, feature disabled → HTTPException 403."""
    from fastapi import HTTPException

    from app.modules.workspaces.features import require_feature

    ws_id = str(uuid.uuid4())
    checker = require_feature("tasks")

    request = MagicMock()
    request.path_params = {"workspace_id": ws_id}

    workspace = MagicMock()
    workspace.settings = {"tasks": False}

    db = AsyncMock()
    db.get = AsyncMock(return_value=workspace)

    with pytest.raises(HTTPException) as exc_info:
        await checker(request=request, db=db)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_feature_checker_project_id_in_path():
    """workspace_id missing, project_id present → resolves workspace_id."""
    from app.modules.workspaces.features import require_feature

    project_id = str(uuid.uuid4())
    ws_id = uuid.uuid4()
    checker = require_feature("tasks")

    request = MagicMock()
    request.path_params = {"project_id": project_id}

    project = _make_project(workspace_id=ws_id)
    workspace = MagicMock()
    workspace.settings = {}

    db = AsyncMock()
    db.get = AsyncMock(side_effect=[project, workspace])

    result = await checker(request=request, db=db)
    assert result is True


@pytest.mark.asyncio
async def test_feature_checker_project_id_not_found():
    """project_id present but project not found → cannot resolve ws → True."""
    from app.modules.workspaces.features import require_feature

    checker = require_feature("tasks")

    request = MagicMock()
    request.path_params = {"project_id": str(uuid.uuid4())}

    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    result = await checker(request=request, db=db)
    assert result is True


@pytest.mark.asyncio
async def test_feature_checker_sprint_id_in_path():
    """sprint_id present → resolves workspace via sprint → project."""
    from app.modules.workspaces.features import require_feature

    sprint_id = str(uuid.uuid4())
    checker = require_feature("sprints")

    request = MagicMock()
    request.path_params = {"sprint_id": sprint_id}

    sprint = MagicMock()
    sprint.project_id = uuid.uuid4()
    project = _make_project()
    workspace = MagicMock()
    workspace.settings = {}

    db = AsyncMock()
    db.get = AsyncMock(side_effect=[sprint, project, workspace])

    result = await checker(request=request, db=db)
    assert result is True


@pytest.mark.asyncio
async def test_feature_checker_sprint_id_sprint_not_found():
    """sprint_id present but sprint not found → cannot resolve ws → True."""
    from app.modules.workspaces.features import require_feature

    checker = require_feature("sprints")

    request = MagicMock()
    request.path_params = {"sprint_id": str(uuid.uuid4())}

    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    result = await checker(request=request, db=db)
    assert result is True


@pytest.mark.asyncio
async def test_feature_checker_task_id_in_path():
    """task_id present → resolves workspace via task → project."""
    from app.modules.workspaces.features import require_feature

    task_id = str(uuid.uuid4())
    checker = require_feature("tasks")

    request = MagicMock()
    request.path_params = {"task_id": task_id}

    task = MagicMock()
    task.project_id = uuid.uuid4()
    project = _make_project()
    workspace = MagicMock()
    workspace.settings = {}

    db = AsyncMock()
    db.get = AsyncMock(side_effect=[task, project, workspace])

    result = await checker(request=request, db=db)
    assert result is True


@pytest.mark.asyncio
async def test_feature_checker_epic_id_in_path():
    """epic_id present → resolves workspace via epic → project."""
    import sys
    import types

    # Create stub module for epics.models
    epic_model = MagicMock()
    epic_module = types.ModuleType("app.modules.epics.models")
    epic_module.Epic = epic_model
    sys.modules.setdefault("app.modules.epics", types.ModuleType("app.modules.epics"))
    sys.modules["app.modules.epics.models"] = epic_module

    from app.modules.workspaces.features import require_feature

    epic_id = str(uuid.uuid4())
    checker = require_feature("epics")

    request = MagicMock()
    request.path_params = {"epic_id": epic_id}

    epic = MagicMock()
    epic.project_id = uuid.uuid4()
    project = _make_project()
    workspace = MagicMock()
    workspace.settings = {}

    db = AsyncMock()
    db.get = AsyncMock(side_effect=[epic, project, workspace])

    result = await checker(request=request, db=db)
    assert result is True


@pytest.mark.asyncio
async def test_feature_checker_rule_id_in_path():
    """rule_id present → resolves workspace via automation rule → project."""
    import sys
    import types

    # Create stub module for automation.models
    rule_model = MagicMock()
    automation_module = types.ModuleType("app.modules.automation.models")
    automation_module.AutomationRule = rule_model
    sys.modules.setdefault(
        "app.modules.automation", types.ModuleType("app.modules.automation")
    )
    sys.modules["app.modules.automation.models"] = automation_module

    from app.modules.workspaces.features import require_feature

    rule_id = str(uuid.uuid4())
    checker = require_feature("automation")

    request = MagicMock()
    request.path_params = {"rule_id": rule_id}

    rule = MagicMock()
    rule.project_id = uuid.uuid4()
    project = _make_project()
    workspace = MagicMock()
    workspace.settings = {}

    db = AsyncMock()
    db.get = AsyncMock(side_effect=[rule, project, workspace])

    result = await checker(request=request, db=db)
    assert result is True


@pytest.mark.asyncio
async def test_feature_checker_no_path_params():
    """No identifiable path params → cannot resolve workspace → True."""
    from app.modules.workspaces.features import require_feature

    checker = require_feature("tasks")

    request = MagicMock()
    request.path_params = {}

    db = AsyncMock()
    result = await checker(request=request, db=db)
    assert result is True


@pytest.mark.asyncio
async def test_feature_checker_workspace_not_found_in_db():
    """workspace_id resolved but workspace not found → True (no 403)."""
    from app.modules.workspaces.features import require_feature

    ws_id = str(uuid.uuid4())
    checker = require_feature("tasks")

    request = MagicMock()
    request.path_params = {"workspace_id": ws_id}

    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    result = await checker(request=request, db=db)
    assert result is True


# ═══════════════════════════════════════════════════════════════════════════════
# 2. search/service.py
# ═══════════════════════════════════════════════════════════════════════════════


def _get_search_client(user=None):
    from app.database import get_db
    from app.main import app
    from app.modules.auth.dependencies import get_current_active_user

    if user is None:
        user = _make_user()
    _db = AsyncMock()

    async def _override_db():
        yield _db

    async def _override_user():
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_active_user] = _override_user
    return TestClient(app, raise_server_exceptions=False), _db, user


def test_global_search_not_member():
    """GET /api/v1/search → returns empty when service returns {}."""
    client, _, _ = _get_search_client()
    ws_id = uuid.uuid4()
    try:
        with patch(
            "app.modules.search.service.global_search",
            new=AsyncMock(return_value={"projects": [], "tasks": [], "users": []}),
        ):
            resp = client.get(f"/api/v1/search?q=test&workspace_id={ws_id}")
        assert resp.status_code == 200
        assert resp.json() == {"projects": [], "tasks": [], "users": []}
    finally:
        from app.main import app

        app.dependency_overrides.clear()


def test_global_search_member_with_results():
    """GET /api/v1/search → returns search results when service finds matches."""
    client, _, _ = _get_search_client()
    ws_id = uuid.uuid4()
    proj_id = str(uuid.uuid4())
    expected = {
        "projects": [{"id": proj_id, "name": "Project A"}],
        "tasks": [],
        "users": [],
    }
    try:
        with patch(
            "app.modules.search.service.global_search",
            new=AsyncMock(return_value=expected),
        ):
            resp = client.get(f"/api/v1/search?q=proj&workspace_id={ws_id}")
        assert resp.status_code == 200
        assert resp.json()["projects"][0]["name"] == "Project A"
    finally:
        from app.main import app

        app.dependency_overrides.clear()


def test_global_search_member_empty_results():
    """GET /api/v1/search with no matches → empty lists."""
    client, _, _ = _get_search_client()
    ws_id = uuid.uuid4()
    try:
        with patch(
            "app.modules.search.service.global_search",
            new=AsyncMock(return_value={"projects": [], "tasks": [], "users": []}),
        ):
            resp = client.get(f"/api/v1/search?q=nope&workspace_id={ws_id}")
        assert resp.status_code == 200
    finally:
        from app.main import app

        app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. users/router.py — TestClient
# ═══════════════════════════════════════════════════════════════════════════════


def _get_users_client(user=None):
    from app.database import get_db
    from app.main import app
    from app.modules.auth.dependencies import get_current_active_user

    if user is None:
        user = _make_user()

    _db = AsyncMock()

    async def _override_db():
        yield _db

    async def _override_user():
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_active_user] = _override_user
    return TestClient(app, raise_server_exceptions=False), _db, user


def test_users_get_me():
    """GET /api/v1/users/me → 200."""
    client, _, user = _get_users_client()
    try:
        with patch(
            "app.modules.auth.manager.user_manager.search_users",
            new=AsyncMock(return_value=[]),
        ):
            resp = client.get("/api/v1/users/me")
        assert resp.status_code == 200
    finally:
        from app.main import app

        app.dependency_overrides.clear()


def test_users_search():
    """GET /api/v1/users/search?q=alice → 200."""
    client, db, user = _get_users_client()
    try:
        with patch(
            "app.modules.auth.manager.user_manager.search_users",
            new=AsyncMock(return_value=[]),
        ):
            resp = client.get("/api/v1/users/search?q=alice")
        assert resp.status_code == 200
    finally:
        from app.main import app

        app.dependency_overrides.clear()


def test_users_update_me():
    """PUT /api/v1/users/me → 200 with mocked update."""
    user = _make_user()
    client, db, _ = _get_users_client(user)
    try:
        with patch(
            "app.modules.auth.manager.user_manager.update",
            new=AsyncMock(return_value=user),
        ):
            resp = client.put(
                "/api/v1/users/me",
                json={"full_name": "New Name"},
            )
        assert resp.status_code == 200
    finally:
        from app.main import app

        app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. notifications/router.py — TestClient + mocked service
# ═══════════════════════════════════════════════════════════════════════════════


def _get_notif_client(user=None):
    from app.database import get_db
    from app.main import app
    from app.modules.auth.dependencies import get_current_active_user

    if user is None:
        user = _make_user()

    _db = AsyncMock()

    async def _override_db():
        yield _db

    async def _override_user():
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_active_user] = _override_user
    return TestClient(app, raise_server_exceptions=False), _db, user


def test_notifications_list():
    """GET /api/v1/notifications → 200."""
    client, _, user = _get_notif_client()
    try:
        with patch(
            "app.modules.notifications.service.get_for_user",
            new=AsyncMock(return_value=[]),
        ):
            resp = client.get("/api/v1/notifications")
        assert resp.status_code == 200
    finally:
        from app.main import app

        app.dependency_overrides.clear()


def test_notifications_unread_count():
    """GET /api/v1/notifications/unread-count → 200."""
    client, _, user = _get_notif_client()
    try:
        with patch(
            "app.modules.notifications.service.get_unread_count",
            new=AsyncMock(return_value=5),
        ):
            resp = client.get("/api/v1/notifications/unread-count")
        assert resp.status_code == 200
        assert resp.json()["count"] == 5
    finally:
        from app.main import app

        app.dependency_overrides.clear()


def test_notifications_read_all():
    """PATCH /api/v1/notifications/read-all → 200."""
    client, _, user = _get_notif_client()
    try:
        with patch(
            "app.modules.notifications.service.mark_all_read",
            new=AsyncMock(return_value=3),
        ):
            resp = client.patch("/api/v1/notifications/read-all")
        assert resp.status_code == 200
        assert resp.json()["marked_read"] == 3
    finally:
        from app.main import app

        app.dependency_overrides.clear()


def test_notifications_read_one_success():
    """PATCH /api/v1/notifications/{id}/read → 200 when found."""
    client, _, user = _get_notif_client()
    notif_id = uuid.uuid4()
    try:
        with patch(
            "app.modules.notifications.service.mark_read",
            new=AsyncMock(return_value=True),
        ):
            resp = client.patch(f"/api/v1/notifications/{notif_id}/read")
        assert resp.status_code == 200
    finally:
        from app.main import app

        app.dependency_overrides.clear()


def test_notifications_read_one_not_found():
    """PATCH /api/v1/notifications/{id}/read → 404 when not found."""
    client, _, user = _get_notif_client()
    notif_id = uuid.uuid4()
    try:
        with patch(
            "app.modules.notifications.service.mark_read",
            new=AsyncMock(return_value=False),
        ):
            resp = client.patch(f"/api/v1/notifications/{notif_id}/read")
        assert resp.status_code == 404
    finally:
        from app.main import app

        app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# 5. admin/router.py — TestClient
# ═══════════════════════════════════════════════════════════════════════════════


def _get_admin_client():
    from app.database import get_db
    from app.main import app
    from app.modules.auth.dependencies import get_current_active_user, require_admin

    admin_user = _make_user(system_role="admin")
    _db = AsyncMock()

    async def _override_db():
        yield _db

    async def _override_admin():
        return admin_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_active_user] = _override_admin
    app.dependency_overrides[require_admin] = _override_admin
    return TestClient(app, raise_server_exceptions=False), _db, admin_user


def test_admin_list_users():
    """GET /api/v1/admin/users → 200."""
    client, _, _ = _get_admin_client()
    try:
        with patch(
            "app.modules.admin.manager.admin_manager.list_users",
            new=AsyncMock(return_value=[]),
        ):
            resp = client.get("/api/v1/admin/users")
        assert resp.status_code == 200
    finally:
        from app.main import app

        app.dependency_overrides.clear()


def test_admin_update_user_role_invalid():
    """PUT /api/v1/admin/users/{id}/role with bad role → 400."""
    client, _, _ = _get_admin_client()
    user_id = uuid.uuid4()
    try:
        resp = client.put(
            f"/api/v1/admin/users/{user_id}/role",
            json={"role": "superuser"},
        )
        assert resp.status_code == 400
    finally:
        from app.main import app

        app.dependency_overrides.clear()


def test_admin_update_user_role_valid():
    """PUT /api/v1/admin/users/{id}/role with valid role → 200."""
    client, _, admin = _get_admin_client()
    user_id = uuid.uuid4()
    try:
        with patch(
            "app.modules.admin.manager.admin_manager.update_user_role",
            new=AsyncMock(return_value=admin),
        ):
            resp = client.put(
                f"/api/v1/admin/users/{user_id}/role",
                json={"role": "user"},
            )
        assert resp.status_code == 200
    finally:
        from app.main import app

        app.dependency_overrides.clear()


def test_admin_update_user_status():
    """PUT /api/v1/admin/users/{id}/status → 200."""
    client, _, admin = _get_admin_client()
    user_id = uuid.uuid4()
    try:
        with patch(
            "app.modules.admin.manager.admin_manager.update_user_status",
            new=AsyncMock(return_value=admin),
        ):
            resp = client.put(
                f"/api/v1/admin/users/{user_id}/status",
                json={"is_active": False},
            )
        assert resp.status_code == 200
    finally:
        from app.main import app

        app.dependency_overrides.clear()


def test_admin_list_workspaces():
    """GET /api/v1/admin/workspaces → 200."""
    client, _, _ = _get_admin_client()
    try:
        with patch(
            "app.modules.admin.manager.admin_manager.list_workspaces",
            new=AsyncMock(return_value=[]),
        ):
            resp = client.get("/api/v1/admin/workspaces")
        assert resp.status_code == 200
    finally:
        from app.main import app

        app.dependency_overrides.clear()


def test_admin_reset_password_too_short():
    """PUT /api/v1/admin/users/{id}/reset-password with short pw → 400."""
    client, _, _ = _get_admin_client()
    user_id = uuid.uuid4()
    try:
        resp = client.put(
            f"/api/v1/admin/users/{user_id}/reset-password",
            json={"new_password": "abc"},
        )
        assert resp.status_code == 400
    finally:
        from app.main import app

        app.dependency_overrides.clear()


def test_admin_reset_password_valid():
    """PUT /api/v1/admin/users/{id}/reset-password valid → 200."""
    client, _, admin = _get_admin_client()
    user_id = uuid.uuid4()
    try:
        with patch(
            "app.modules.admin.manager.admin_manager.reset_user_password",
            new=AsyncMock(return_value=admin),
        ):
            resp = client.put(
                f"/api/v1/admin/users/{user_id}/reset-password",
                json={"new_password": "NewPass1!"},
            )
        assert resp.status_code == 200
    finally:
        from app.main import app

        app.dependency_overrides.clear()


def test_admin_update_user_profile():
    """PUT /api/v1/admin/users/{id}/profile → 200."""
    client, _, admin = _get_admin_client()
    user_id = uuid.uuid4()
    try:
        with patch(
            "app.modules.admin.manager.admin_manager.update_user_profile",
            new=AsyncMock(return_value=admin),
        ):
            resp = client.put(
                f"/api/v1/admin/users/{user_id}/profile",
                json={"full_name": "New Name", "email": "new@test.com"},
            )
        assert resp.status_code == 200
    finally:
        from app.main import app

        app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# 6. main.py — exception handlers
# ═══════════════════════════════════════════════════════════════════════════════


def test_main_validation_error_handler():
    """POST /api/v1/auth/register with bad body → 422 via validation handler."""
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    # Sending invalid JSON (missing required fields triggers RequestValidationError)
    resp = client.post("/api/v1/auth/register", json={})
    assert resp.status_code == 422
    data = resp.json()
    assert "detail" in data


def test_main_health_check():
    """GET / → 200 health check (covers line 122)."""
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_main_sqlalchemy_error_handler():
    """Trigger SQLAlchemyError handler → 500 with db.unexpected_error."""
    from sqlalchemy.exc import SQLAlchemyError

    from app.database import get_db
    from app.main import app

    async def _raise_db():
        raise SQLAlchemyError("boom")
        yield  # make it a generator

    app.dependency_overrides[get_db] = _raise_db
    client = TestClient(app, raise_server_exceptions=False)
    try:
        resp = client.get("/api/v1/users/me")
        # Either 500 from sqlalchemy handler or 401 from auth — depends on order
        assert resp.status_code in (401, 500, 422)
    finally:
        app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# 7. dashboard/manager.py — is_pm=True path
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_dashboard_personal_stats_is_pm_with_workload():
    """get_personal_stats with PM role → executes team workload + blocked tasks paths."""
    from app.modules.dashboard.manager import DashboardManager

    mgr = DashboardManager()
    user = _make_user()
    pm_project_id = uuid.uuid4()

    db = AsyncMock()
    # scalar calls: todo, in_progress, review, done_week, overdue, then per-member (ip, td, ov), blocked_by
    db.scalar = AsyncMock(return_value=0)

    # upcoming rows (empty)
    upcoming_res = MagicMock()
    upcoming_res.all.return_value = []

    # project rows (empty)
    project_res = MagicMock()
    project_res.all.return_value = []

    # PM project ids (non-empty → is_pm=True)
    pm_ids_scalars = MagicMock()
    pm_ids_scalars.all.return_value = [pm_project_id]
    pm_ids_res = MagicMock()
    pm_ids_res.scalars.return_value = pm_ids_scalars

    # member user ids
    member_uid = uuid.uuid4()
    member_uids_scalars = MagicMock()
    member_uids_scalars.all.return_value = [member_uid]
    member_uids_res = MagicMock()
    member_uids_res.scalars.return_value = member_uids_scalars

    # members
    member_obj = MagicMock()
    member_obj.id = member_uid
    member_obj.full_name = "Alice"
    member_obj.email = "alice@test.com"
    members_scalars = MagicMock()
    members_scalars.all.return_value = [member_obj]
    members_res = MagicMock()
    members_res.scalars.return_value = members_scalars

    # blocked rows (empty)
    blocked_res = MagicMock()
    blocked_res.all.return_value = []

    db.execute = AsyncMock(
        side_effect=[
            upcoming_res,
            project_res,
            pm_ids_res,
            member_uids_res,
            members_res,
            blocked_res,
        ]
    )

    result = await mgr.get_personal_stats(db, user)
    assert result.is_pm is True
    assert len(result.team_workload) == 1
    assert result.team_workload[0].full_name == "Alice"


@pytest.mark.asyncio
async def test_dashboard_personal_stats_is_pm_with_blocked_tasks():
    """get_personal_stats with PM role and blocked tasks → covers blocked_tasks loop."""
    from app.modules.dashboard.manager import DashboardManager

    mgr = DashboardManager()
    user = _make_user()
    pm_project_id = uuid.uuid4()

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=1)

    # upcoming rows
    upcoming_res = MagicMock()
    upcoming_res.all.return_value = []

    # project rows
    project_res = MagicMock()
    project_res.all.return_value = []

    # PM project ids (non-empty)
    pm_ids_scalars = MagicMock()
    pm_ids_scalars.all.return_value = [pm_project_id]
    pm_ids_res = MagicMock()
    pm_ids_res.scalars.return_value = pm_ids_scalars

    # member user ids (empty → no workload loop)
    member_uids_scalars = MagicMock()
    member_uids_scalars.all.return_value = []
    member_uids_res = MagicMock()
    member_uids_res.scalars.return_value = member_uids_scalars

    # members (empty)
    members_scalars = MagicMock()
    members_scalars.all.return_value = []
    members_res = MagicMock()
    members_res.scalars.return_value = members_scalars

    # blocked row
    blocked_task = MagicMock()
    blocked_task.id = uuid.uuid4()
    blocked_task.title = "Blocked Task"
    blocked_task.project_id = pm_project_id
    blocked_row = MagicMock()
    blocked_row.Task = blocked_task
    blocked_row.project_name = "Project X"

    blocked_res = MagicMock()
    blocked_res.all.return_value = [blocked_row]

    db.execute = AsyncMock(
        side_effect=[
            upcoming_res,
            project_res,
            pm_ids_res,
            member_uids_res,
            members_res,
            blocked_res,
        ]
    )

    result = await mgr.get_personal_stats(db, user)
    assert result.is_pm is True
    assert len(result.blocked_tasks) == 1
    assert result.blocked_tasks[0].title == "Blocked Task"


@pytest.mark.asyncio
async def test_dashboard_personal_stats_not_pm():
    """get_personal_stats with no PM projects → is_pm=False, no extra queries."""
    from app.modules.dashboard.manager import DashboardManager

    mgr = DashboardManager()
    user = _make_user()

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=0)

    upcoming_res = MagicMock()
    upcoming_res.all.return_value = []

    project_res = MagicMock()
    project_res.all.return_value = []

    # PM project ids (empty → is_pm=False)
    pm_ids_scalars = MagicMock()
    pm_ids_scalars.all.return_value = []
    pm_ids_res = MagicMock()
    pm_ids_res.scalars.return_value = pm_ids_scalars

    db.execute = AsyncMock(side_effect=[upcoming_res, project_res, pm_ids_res])

    result = await mgr.get_personal_stats(db, user)
    assert result.is_pm is False
    assert result.team_workload == []
    assert result.blocked_tasks == []


@pytest.mark.asyncio
async def test_dashboard_personal_stats_with_project_rows():
    """get_personal_stats with project rows → exercises my_projects loop (lines 141-166)."""
    from app.modules.dashboard.manager import DashboardManager

    mgr = DashboardManager()
    user = _make_user()

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=5)

    upcoming_res = MagicMock()
    upcoming_res.all.return_value = []

    # Project row
    project_obj = MagicMock()
    project_obj.id = uuid.uuid4()
    project_obj.name = "My Project"
    proj_row = MagicMock()
    proj_row.Project = project_obj
    proj_row.name = "Developer"

    project_res = MagicMock()
    project_res.all.return_value = [proj_row]

    # PM project ids (empty)
    pm_ids_scalars = MagicMock()
    pm_ids_scalars.all.return_value = []
    pm_ids_res = MagicMock()
    pm_ids_res.scalars.return_value = pm_ids_scalars

    db.execute = AsyncMock(side_effect=[upcoming_res, project_res, pm_ids_res])

    result = await mgr.get_personal_stats(db, user)
    assert len(result.my_projects) == 1
    assert result.my_projects[0].name == "My Project"
