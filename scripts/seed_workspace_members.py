import asyncio
import os
import sys

# Add app to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.workspace import Workspace, WorkspaceMember


async def seed_workspace_members():
    async with AsyncSessionLocal() as session:
        # Get all workspaces
        stmt = select(Workspace)
        result = await session.execute(stmt)
        workspaces = result.scalars().all()

        count = 0
        for workspace in workspaces:
            # Check if membership already exists
            mem_stmt = select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == workspace.owner_id,
            )
            mem_res = await session.execute(mem_stmt)
            existing = mem_res.scalar_one_or_none()

            if not existing:
                new_member = WorkspaceMember(
                    workspace_id=workspace.id,
                    user_id=workspace.owner_id,
                    # role_id = None for now, or we can assign a "Workspace Owner" role if it exists
                    # We will leave role_id null and let the app logic treat owner implicitly or create a role later
                )
                session.add(new_member)
                count += 1

        await session.commit()
        print(f"Added {count} workspace owners to workspace_members.")


if __name__ == "__main__":
    asyncio.run(seed_workspace_members())
