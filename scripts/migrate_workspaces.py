import asyncio
import sys
import os

# Add the current folder to PYTHONPATH so that app can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, update
from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.workspace import Workspace
from app.models.project import Project
from app.models.task import Task


async def migrate():
    print("Starting Workspace Data Migration...")
    async with AsyncSessionLocal() as session:
        # 1. Create personal Workspace for all existing Users if missing
        result = await session.execute(select(User))
        users = result.scalars().all()

        user_workspaces = {}  # user_id -> workspace_id

        for user in users:
            # Check if user already has a personal workspace
            ws_result = await session.execute(
                select(Workspace).where(
                    Workspace.owner_id == user.id, Workspace.type == "personal"
                )
            )
            ws = ws_result.scalar_one_or_none()

            if not ws:
                # Create new
                ws = Workspace(
                    name="Personal Workspace",
                    type="personal",
                    owner_id=user.id,
                    settings={
                        "enable_members": False,
                        "enable_sprint": False,
                        "enable_epics": False,
                        "enable_story_points": False,
                        "enable_workload": False,
                        "enable_automation": False,
                        "enable_ai": True,
                        "enable_time_tracking": False,
                        "enable_calendar": True,
                        "theme": "minimal",
                    },
                )
                session.add(ws)
                await session.flush()  # Get ws.id
                print(f"-> Created personal Workspace for user: {user.email}")

            user_workspaces[user.id] = ws.id

        await session.commit()

        # 2. Update projects and tasks where workspace_id = NULL
        result_proj = await session.execute(
            select(Project).where(Project.workspace_id is None)
        )
        projects = result_proj.scalars().all()

        for proj in projects:
            owner_id = proj.owner_id
            if not owner_id:
                # Use admin user as fallback owner
                admin_result = await session.execute(
                    select(User).where(User.system_role == "admin").limit(1)
                )
                admin = admin_result.scalar_one_or_none()
                if admin:
                    owner_id = admin.id
                else:
                    owner_id = users[0].id if users else None

            if owner_id and owner_id in user_workspaces:
                ws_id = user_workspaces[owner_id]
                proj.workspace_id = ws_id
                print(
                    f"-> Assigned Project '{proj.name}' to Workspace of Owner ({owner_id})"
                )

                # Update all tasks in this project to the same workspace
                await session.execute(
                    update(Task)
                    .where(Task.project_id == proj.id, Task.workspace_id is None)
                    .values(workspace_id=ws_id)
                )
            else:
                print(
                    f"Warning: No valid Owner found for Project '{proj.name}' (ID: {proj.id})"
                )

        await session.commit()
        print("Data migration completed successfully!")


if __name__ == "__main__":
    asyncio.run(migrate())
