from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_manager import BaseManager
from app.models.user import User
from app.modules.auth.schemas import UserCreate, UserUpdate
from app.modules.auth.security import get_password_hash


class UserManager(BaseManager[User, UserCreate, UserUpdate]):
    async def get_by_email(self, db: AsyncSession, email: str) -> Optional[User]:
        """Get a User by email"""
        stmt = select(self.model).where(self.model.email == email)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, db: AsyncSession, *, obj_in: UserCreate, **kwargs) -> User:
        """Override create to hash the password before saving"""
        hashed_password = get_password_hash(obj_in.password)
        db_user = User(
            email=obj_in.email,
            password_hash=hashed_password,
            full_name=obj_in.full_name,
        )
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)

        return db_user

    async def search_users(self, db: AsyncSession, query: str) -> List[User]:
        """Search users by email or full_name"""
        stmt = (
            select(self.model)
            .where(
                (self.model.email.ilike(f"%{query}%"))
                | (self.model.full_name.ilike(f"%{query}%"))
            )
            .limit(20)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self, db: AsyncSession, *, db_obj: User, obj_in: UserUpdate | dict
    ) -> User:
        """Override update to hash the password if it changed"""
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True)

        if "password" in update_data:
            hashed_password = get_password_hash(update_data["password"])
            del update_data["password"]
            update_data["password_hash"] = hashed_password

        return await super().update(db, db_obj=db_obj, obj_in=update_data)


user_manager = UserManager(User)
