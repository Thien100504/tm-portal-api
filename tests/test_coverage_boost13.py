"""
Coverage boost 13 — final push to 80%:
  - workspaces/router.py    (11 missing lines — all endpoint bodies)
  - rbac/router.py          (16 missing lines)
  - epics/router.py         (9 remaining error paths)
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_user(**kw):
    u = MagicMock()
    u.id = kw.get("id", uuid.uuid4())
    u.email = kw.get("email", "u@test.com")
    u.full_name = kw.get("full_name", "Test User")
    u.is_active = True
    u.system_role = "user"
    u.password_hash = "hashed"
    u.telegram_chat_id = None
    u.avatar_url = None
    return u


def _make_workspace(**kw):
    ws = MagicMock()
    ws.id = kw.get("id", uuid.uuid4())
    ws.name = kw.get("name", "My Workspace")
    ws.type = kw.get("type", "personal")
    ws.owner_id = kw.get("owner_id", uuid.uuid4())
    ws.settings = kw.get("settings", {})
    ws.created_at = kw.get("created_at", datetime(2026, 1, 1))
    return ws


def _make_role(**kw):
    r = MagicMock()
    r.id = kw.get("id", uuid.uuid4())
    r.name = kw.get("name", "Developer")
    r.description = kw.get("description", None)
    r.scope = kw.get("scope", "project")
    r.workspace_id = kw.get("workspace_id", None)
    r.is_system_default = kw.get("is_system_default", False)
    r.permissions = kw.get("permissions", [])
    return r


def _make_epic(**kw):
    e = MagicMock()
    e.id = kw.get("id", uuid.uuid4())
    e.workspace_id = kw.get("workspace_id", uuid.uuid4())
    e.project_id = kw.get("project_id", None)
    e.name = kw.get("name", "Test Epic")
    e.description = None
    e.color = None
    e.status = kw.get("status", "open")
    e.due_date = None
    e.created_at = kw.get("created_at", datetime(2026, 1, 1))
    e.updated_at = None
    e.is_deleted = False
    return e


def _make_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.scalar = AsyncMock(return_value=None)
    db.get = AsyncMock(return_value=None)
    return db


def _get_client(user=None, db=None):
    from app.database import get_db
    from app.main import app
    from app.modules.auth.dependencies import get_current_active_user

    if user is None:
        user = _make_user()
    if db is None:
        db = _make_db()

    async def _override_db():
        yield db

    async def _override_user():
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_active_user] = _override_user
    return TestClient(app, raise_server_exceptions=False), db, user


def _clear(app):
    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. workspaces/router.py — lines 29, 39, 49, 60, 72, 82, 94, 107, 121, 136, 151
# ═══════════════════════════════════════════════════════════════════════════════


def test_workspaces_list():
    """GET /api/v1/workspaces → 200."""
    client, db, user = _get_client()
    try:
        with patch(
            "app.modules.workspaces.manager.workspace_manager.list_workspaces",
            new=AsyncMock(return_value=[]),
        ):
            resp = client.get("/api/v1/workspaces")
        assert resp.status_code == 200
    finally:
        from app.main import app as _app

        _clear(_app)


def test_workspaces_create():
    """POST /api/v1/workspaces → 201."""
    client, db, user = _get_client()
    ws = _make_workspace(owner_id=user.id)
    try:
        with patch(
            "app.modules.workspaces.manager.workspace_manager.create_workspace",
            new=AsyncMock(return_value=ws),
        ):
            resp = client.post(
                "/api/v1/workspaces",
                json={"name": "My Workspace", "type": "personal"},
            )
        assert resp.status_code == 201
    finally:
        from app.main import app as _app

        _clear(_app)


def test_workspaces_get_one():
    """GET /api/v1/workspaces/{id} → 200."""
    client, db, user = _get_client()
    ws = _make_workspace(owner_id=user.id)
    try:
        with patch(
            "app.modules.workspaces.manager.workspace_manager.get_workspace",
            new=AsyncMock(return_value=ws),
        ):
            resp = client.get(f"/api/v1/workspaces/{ws.id}")
        assert resp.status_code == 200
    finally:
        from app.main import app as _app

        _clear(_app)


def test_workspaces_update():
    """PUT /api/v1/workspaces/{id} → 200."""
    client, db, user = _get_client()
    ws = _make_workspace(owner_id=user.id)
    try:
        with patch(
            "app.modules.workspaces.manager.workspace_manager.update_workspace",
            new=AsyncMock(return_value=ws),
        ):
            resp = client.put(
                f"/api/v1/workspaces/{ws.id}",
                json={"name": "Updated"},
            )
        assert resp.status_code == 200
    finally:
        from app.main import app as _app

        _clear(_app)


def test_workspaces_delete():
    """DELETE /api/v1/workspaces/{id} → 204."""
    client, db, user = _get_client()
    ws_id = uuid.uuid4()
    try:
        with patch(
            "app.modules.workspaces.manager.workspace_manager.delete_workspace",
            new=AsyncMock(return_value=None),
        ):
            resp = client.delete(f"/api/v1/workspaces/{ws_id}")
        assert resp.status_code == 204
    finally:
        from app.main import app as _app

        _clear(_app)


def test_workspaces_get_members():
    """GET /api/v1/workspaces/{id}/members → 200."""
    client, db, user = _get_client()
    ws_id = uuid.uuid4()
    try:
        with patch(
            "app.modules.workspaces.manager.workspace_manager.get_workspace_members",
            new=AsyncMock(return_value=[]),
        ):
            resp = client.get(f"/api/v1/workspaces/{ws_id}/members")
        assert resp.status_code == 200
    finally:
        from app.main import app as _app

        _clear(_app)


def test_workspaces_get_invitations():
    """GET /api/v1/workspaces/{id}/invitations → 200."""
    client, db, user = _get_client()
    ws_id = uuid.uuid4()
    try:
        with patch(
            "app.modules.workspaces.manager.workspace_manager.get_workspace_invitations",
            new=AsyncMock(return_value=[]),
        ):
            resp = client.get(f"/api/v1/workspaces/{ws_id}/invitations")
        assert resp.status_code == 200
    finally:
        from app.main import app as _app

        _clear(_app)


def test_workspaces_invite_member():
    """POST /api/v1/workspaces/{id}/members/invite → 200."""
    client, db, user = _get_client()
    ws_id = uuid.uuid4()
    try:
        with patch(
            "app.modules.workspaces.manager.workspace_manager.invite_workspace_member",
            new=AsyncMock(return_value={"status": "invited"}),
        ):
            resp = client.post(
                f"/api/v1/workspaces/{ws_id}/members/invite",
                json={"email": "new@test.com"},
            )
        assert resp.status_code == 200
    finally:
        from app.main import app as _app

        _clear(_app)


def test_workspaces_update_member():
    """PUT /api/v1/workspaces/{id}/members/{user_id} → 200."""
    client, db, user = _get_client()
    ws_id = uuid.uuid4()
    target_id = uuid.uuid4()

    mem = MagicMock()
    mem.workspace_id = ws_id
    mem.user_id = target_id
    mem.role_id = None
    mem.role = None
    mem.user = _make_user(id=target_id)
    mem.joined_at = datetime(2026, 1, 1)

    try:
        with patch(
            "app.modules.workspaces.manager.workspace_manager.update_workspace_member",
            new=AsyncMock(return_value=mem),
        ):
            resp = client.put(
                f"/api/v1/workspaces/{ws_id}/members/{target_id}",
                json={"role_id": None},
            )
        assert resp.status_code == 200
    finally:
        from app.main import app as _app

        _clear(_app)


def test_workspaces_remove_member():
    """DELETE /api/v1/workspaces/{id}/members/{user_id} → 204."""
    client, db, user = _get_client()
    ws_id = uuid.uuid4()
    target_id = uuid.uuid4()
    try:
        with patch(
            "app.modules.workspaces.manager.workspace_manager.remove_workspace_member",
            new=AsyncMock(return_value=None),
        ):
            resp = client.delete(f"/api/v1/workspaces/{ws_id}/members/{target_id}")
        assert resp.status_code == 204
    finally:
        from app.main import app as _app

        _clear(_app)


def test_workspaces_cancel_invitation():
    """DELETE /api/v1/workspaces/{id}/invitations/{invite_id} → 204."""
    client, db, user = _get_client()
    ws_id = uuid.uuid4()
    invite_id = uuid.uuid4()
    try:
        with patch(
            "app.modules.workspaces.manager.workspace_manager.cancel_workspace_invitation",
            new=AsyncMock(return_value=None),
        ):
            resp = client.delete(f"/api/v1/workspaces/{ws_id}/invitations/{invite_id}")
        assert resp.status_code == 204
    finally:
        from app.main import app as _app

        _clear(_app)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. rbac/router.py — lines 29-31, 42, 52, 63, 74-76, 86, 97-111
# ═══════════════════════════════════════════════════════════════════════════════


def test_rbac_get_permissions():
    """GET /api/v1/roles/permissions → 200."""
    client, db, user = _get_client()
    empty_scalars = MagicMock()
    empty_scalars.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=empty_scalars)
    try:
        resp = client.get("/api/v1/roles/permissions")
        assert resp.status_code == 200
    finally:
        from app.main import app as _app

        _clear(_app)


def test_rbac_get_roles():
    """GET /api/v1/roles → 200."""
    client, db, user = _get_client()
    try:
        with patch(
            "app.modules.rbac.manager.rbac_manager.get_roles",
            new=AsyncMock(return_value=[]),
        ):
            resp = client.get("/api/v1/roles")
        assert resp.status_code == 200
    finally:
        from app.main import app as _app

        _clear(_app)


def test_rbac_create_role():
    """POST /api/v1/roles → 201."""
    client, db, user = _get_client()
    role = _make_role()
    try:
        with patch(
            "app.modules.rbac.manager.rbac_manager.create_role",
            new=AsyncMock(return_value=role),
        ):
            resp = client.post(
                "/api/v1/roles",
                json={"name": "Developer", "scope": "project"},
            )
        assert resp.status_code == 201
    finally:
        from app.main import app as _app

        _clear(_app)


def test_rbac_update_role():
    """PUT /api/v1/roles/{id} → 200."""
    client, db, user = _get_client()
    role = _make_role()
    try:
        with patch(
            "app.modules.rbac.manager.rbac_manager.update_role",
            new=AsyncMock(return_value=role),
        ):
            resp = client.put(
                f"/api/v1/roles/{role.id}",
                json={"name": "Updated Role"},
            )
        assert resp.status_code == 200
    finally:
        from app.main import app as _app

        _clear(_app)


def test_rbac_update_role_permissions():
    """PUT /api/v1/roles/{id}/permissions → 200."""
    client, db, user = _get_client()
    role = _make_role()
    try:
        with patch(
            "app.modules.rbac.manager.rbac_manager.update_role_permissions",
            new=AsyncMock(return_value=role),
        ):
            resp = client.put(
                f"/api/v1/roles/{role.id}/permissions",
                json={"permission_ids": []},
            )
        assert resp.status_code == 200
    finally:
        from app.main import app as _app

        _clear(_app)


def test_rbac_delete_role():
    """DELETE /api/v1/roles/{id} → 204."""
    client, db, user = _get_client()
    role_id = uuid.uuid4()
    try:
        with patch(
            "app.modules.rbac.manager.rbac_manager.delete_role",
            new=AsyncMock(return_value=None),
        ):
            resp = client.delete(f"/api/v1/roles/{role_id}")
        assert resp.status_code == 204
    finally:
        from app.main import app as _app

        _clear(_app)


def test_rbac_my_permissions_no_workspace():
    """GET /api/v1/roles/my-permissions (no scope) → 200 returns []."""
    client, db, user = _get_client()
    try:
        resp = client.get("/api/v1/roles/my-permissions")
        assert resp.status_code == 200
        assert resp.json() == []
    finally:
        from app.main import app as _app

        _clear(_app)


def test_rbac_my_permissions_with_workspace():
    """GET /api/v1/roles/my-permissions?workspace_id=... → 200."""
    client, db, user = _get_client()
    ws_id = uuid.uuid4()
    try:
        with patch(
            "app.modules.rbac.manager.rbac_manager.get_user_permissions",
            new=AsyncMock(return_value={"project.create", "task.read"}),
        ):
            resp = client.get(f"/api/v1/roles/my-permissions?workspace_id={ws_id}")
        assert resp.status_code == 200
        assert len(resp.json()) == 2
    finally:
        from app.main import app as _app

        _clear(_app)


def test_rbac_my_permissions_with_project_id():
    """GET /api/v1/roles/my-permissions?project_id=... → 200 (resolves ws_id from DB)."""
    client, db, user = _get_client()
    proj_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    db.scalar = AsyncMock(return_value=ws_id)  # returns workspace_id
    try:
        with patch(
            "app.modules.rbac.manager.rbac_manager.get_user_permissions",
            new=AsyncMock(return_value={"task.read"}),
        ):
            resp = client.get(f"/api/v1/roles/my-permissions?project_id={proj_id}")
        assert resp.status_code == 200
    finally:
        from app.main import app as _app

        _clear(_app)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. epics/router.py — remaining error paths (lines 111, 113-120, 137, 141-150)
# ═══════════════════════════════════════════════════════════════════════════════


def _epic_client():
    from app.database import get_db
    from app.main import app
    from app.modules.auth.dependencies import get_current_active_user
    from app.modules.epics import router as epics_router_module

    user = _make_user()
    db = _make_db()

    async def _override_db():
        yield db

    async def _override_user():
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_active_user] = _override_user

    epic_feature_dep = epics_router_module.router.dependencies[0].dependency
    app.dependency_overrides[epic_feature_dep] = lambda: True

    return TestClient(app, raise_server_exceptions=False), db, user


def test_epics_update_not_member_403():
    """PUT /api/v1/epics/{id} → 403 when user not ws owner or member (lines 113-120)."""
    client, db, user = _epic_client()
    epic = _make_epic()  # project_id = None
    ws = MagicMock()
    ws.owner_id = uuid.uuid4()  # different owner
    db.get = AsyncMock(return_value=ws)
    db.scalar = AsyncMock(return_value=None)  # not a member
    try:
        with patch(
            "app.modules.epics.manager.epic_manager.get",
            new=AsyncMock(return_value=epic),
        ):
            resp = client.put(f"/api/v1/epics/{epic.id}", json={"name": "X"})
        assert resp.status_code == 403
    finally:
        from app.main import app as _app

        _clear(_app)


def test_epics_delete_project_scoped():
    """DELETE /api/v1/epics/{id} → 204 for project-scoped epic (line 137)."""
    client, db, user = _epic_client()
    proj_id = uuid.uuid4()
    epic = _make_epic(project_id=proj_id)
    try:
        with (
            patch(
                "app.modules.epics.manager.epic_manager.get",
                new=AsyncMock(return_value=epic),
            ),
            patch(
                "app.modules.epics.router.get_project_pm_access",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.modules.epics.manager.epic_manager.remove",
                new=AsyncMock(return_value=None),
            ),
        ):
            resp = client.delete(f"/api/v1/epics/{epic.id}")
        assert resp.status_code == 204
    finally:
        from app.main import app as _app

        _clear(_app)


def test_epics_delete_not_member_403():
    """DELETE /api/v1/epics/{id} → 403 when not ws owner or member (lines 143-150)."""
    client, db, user = _epic_client()
    epic = _make_epic()  # project_id = None
    ws = MagicMock()
    ws.owner_id = uuid.uuid4()  # different owner
    db.get = AsyncMock(return_value=ws)
    db.scalar = AsyncMock(return_value=None)  # not a member
    try:
        with patch(
            "app.modules.epics.manager.epic_manager.get",
            new=AsyncMock(return_value=epic),
        ):
            resp = client.delete(f"/api/v1/epics/{epic.id}")
        assert resp.status_code == 403
    finally:
        from app.main import app as _app

        _clear(_app)


@pytest.fixture(autouse=True)
def _workspace_member_access(request, monkeypatch):
    """Happy-path tests run as a workspace member/admin (access rules are tested elsewhere)."""
    name = request.node.name
    if any(
        word in name
        for word in ("not_member", "forbidden", "403", "not_owner", "non_owner")
    ):
        return
    from unittest.mock import AsyncMock as _AsyncMock

    from app.modules.projects.manager import project_manager as _pm
    from app.modules.rbac.manager import rbac_manager as _rbac

    monkeypatch.setattr(_pm, "is_workspace_member", _AsyncMock(return_value=True))
    monkeypatch.setattr(_pm, "validate_role", _AsyncMock(return_value=None))
    monkeypatch.setattr(
        _rbac, "_check_workspace_admin_access", _AsyncMock(return_value=True)
    )
