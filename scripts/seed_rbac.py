import asyncio
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select, text
from app.config import get_settings
from app.models.rbac import Role, Permission, RolePermission
from app.models.project import ProjectMember

settings = get_settings()
engine = create_async_engine(settings.DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

DEFAULT_PERMISSIONS = [
    {
        "code": "project.settings",
        "module": "Projects",
        "description": "Manage project settings",
    },
    {"code": "task.create", "module": "Tasks", "description": "Create new tasks"},
    {"code": "task.update", "module": "Tasks", "description": "Update existing tasks"},
    {"code": "task.delete", "module": "Tasks", "description": "Delete tasks"},
    {"code": "sprint.manage", "module": "Sprints", "description": "Manage sprints"},
    {
        "code": "workspace.admin",
        "module": "Workspaces",
        "description": "Full workspace administration",
    },
    {
        "code": "workspace.member_manage",
        "module": "Workspaces",
        "description": "Manage workspace members",
    },
]

DEFAULT_ROLES = [
    {
        "name": "Project Manager",
        "description": "Full access to the project",
        "scope": "project",
        "is_system_default": True,
        "permissions": [
            "project.settings",
            "task.create",
            "task.update",
            "task.delete",
            "sprint.manage",
        ],
    },
    {
        "name": "Member",
        "description": "Can create and edit tasks",
        "scope": "project",
        "is_system_default": True,
        "permissions": ["task.create", "task.update"],
    },
    {
        "name": "Viewer",
        "description": "Read-only access",
        "scope": "project",
        "is_system_default": True,
        "permissions": [],
    },
    {
        "name": "Workspace Admin",
        "description": "Full access to workspace settings and members",
        "scope": "workspace",
        "is_system_default": True,
        "permissions": ["workspace.admin", "workspace.member_manage"],
    },
    {
        "name": "Workspace Member",
        "description": "Can view workspace and access assigned projects",
        "scope": "workspace",
        "is_system_default": True,
        "permissions": [],
    },
]


async def seed_rbac():
    async with AsyncSessionLocal() as db:
        # Seed Permissions
        perm_map = {}
        for p_data in DEFAULT_PERMISSIONS:
            result = await db.execute(
                select(Permission).where(Permission.code == p_data["code"])
            )
            perm = result.scalars().first()
            if not perm:
                perm = Permission(
                    id=uuid.uuid4(),
                    code=p_data["code"],
                    module=p_data["module"],
                    description=p_data["description"],
                )
                db.add(perm)
            perm_map[p_data["code"]] = perm

        await db.commit()

        # Seed Roles
        role_map = {}
        for r_data in DEFAULT_ROLES:
            result = await db.execute(
                select(Role).where(
                    Role.name == r_data["name"], Role.is_system_default == True
                )
            )
            role = result.scalars().first()
            if not role:
                role = Role(
                    id=uuid.uuid4(),
                    name=r_data["name"],
                    description=r_data["description"],
                    scope=r_data["scope"],
                    is_system_default=True,
                )
                db.add(role)
                await db.flush()

                # Add permissions
                for p_code in r_data["permissions"]:
                    rp = RolePermission(
                        role_id=role.id, permission_id=perm_map[p_code].id
                    )
                    db.add(rp)
            role_map[r_data["name"]] = role

        await db.commit()

        # Migrate ProjectMembers
        print("Migrating ProjectMembers to use role_id...")
        members = await db.execute(
            select(ProjectMember).where(ProjectMember.role_id.is_(None))
        )
        members = members.scalars().all()
        for member in members:
            old_role = member.project_role
            if old_role == "project_manager":
                member.role_id = role_map["Project Manager"].id
            elif old_role == "member":
                member.role_id = role_map["Member"].id
            else:
                member.role_id = role_map["Viewer"].id

        await db.commit()
        print("RBAC Seeding and Data Migration Complete.")


if __name__ == "__main__":
    asyncio.run(seed_rbac())
