"""seed default permissions and system roles

A fresh database had no roles, so nobody (not even project owners) got any
project permission. This seeds the same defaults as scripts/seed_rbac.py and
is safe to run on databases that were already seeded.

Revision ID: c7d1e2f3a4b5
Revises: eab3482e0963
Create Date: 2026-11-26 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7d1e2f3a4b5"
down_revision: str | None = "eab3482e0963"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSIONS = [
    ("project.settings", "Projects", "Manage project settings"),
    ("task.create", "Tasks", "Create new tasks"),
    ("task.update", "Tasks", "Update existing tasks"),
    ("task.delete", "Tasks", "Delete tasks"),
    ("sprint.manage", "Sprints", "Manage sprints"),
    ("workspace.admin", "Workspaces", "Full workspace administration"),
    ("workspace.member_manage", "Workspaces", "Manage workspace members"),
]

ROLES = [
    (
        "Project Manager",
        "Full access to the project",
        "project",
        [
            "project.settings",
            "task.create",
            "task.update",
            "task.delete",
            "sprint.manage",
        ],
    ),
    ("Member", "Can create and edit tasks", "project", ["task.create", "task.update"]),
    ("Viewer", "Read-only access", "project", []),
    (
        "Workspace Admin",
        "Full access to workspace settings and members",
        "workspace",
        ["workspace.admin", "workspace.member_manage"],
    ),
    (
        "Workspace Member",
        "Can view workspace and access assigned projects",
        "workspace",
        [],
    ),
]

# project_members.project_role -> system role, for rows created without role_id
MEMBER_ROLE = {
    "project_manager": "Project Manager",
    "member": "Member",
    "viewer": "Viewer",
}


def upgrade() -> None:
    conn = op.get_bind()
    for code, module, description in PERMISSIONS:
        conn.execute(
            sa.text(
                "INSERT INTO permissions (id, code, module, description, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :code, :module, :description, now(), now()) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "module": module, "description": description},
        )

    for name, description, scope, codes in ROLES:
        role_id = conn.scalar(
            sa.text(
                "SELECT id FROM roles WHERE name = :name AND scope = :scope "
                "AND is_system_default AND workspace_id IS NULL AND NOT is_deleted LIMIT 1"
            ),
            {"name": name, "scope": scope},
        )
        if role_id is None:
            role_id = conn.scalar(
                sa.text(
                    "INSERT INTO roles (id, name, description, scope, workspace_id, "
                    "is_system_default, is_deleted, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), :name, :description, :scope, NULL, "
                    "true, false, now(), now()) RETURNING id"
                ),
                {"name": name, "description": description, "scope": scope},
            )
        for code in codes:
            conn.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "SELECT :role_id, p.id FROM permissions p WHERE p.code = :code "
                    "AND NOT EXISTS (SELECT 1 FROM role_permissions rp "
                    "WHERE rp.role_id = :role_id AND rp.permission_id = p.id)"
                ),
                {"role_id": role_id, "code": code},
            )

    for project_role, role_name in MEMBER_ROLE.items():
        conn.execute(
            sa.text(
                "UPDATE project_members SET role_id = r.id FROM roles r "
                "WHERE project_members.role_id IS NULL "
                "AND project_members.project_role = :project_role "
                "AND r.name = :role_name AND r.scope = 'project' "
                "AND r.is_system_default AND r.workspace_id IS NULL AND NOT r.is_deleted"
            ),
            {"project_role": project_role, "role_name": role_name},
        )


def downgrade() -> None:
    # Seed data may already be referenced by members and custom setups; keep it.
    pass
