import uuid
from typing import List, Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.pool import Pool


class PoolRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, pool: Pool) -> Optional[Pool]:
        self.session.add(pool)
        await self.session.commit()
        await self.session.refresh(pool)
        return pool

    async def get_by_id(self, pool_id: uuid.UUID) -> Optional[Pool]:
        statement = select(Pool).where(Pool.id == pool_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Pool:
        statement = select(Pool).where(Pool.slug == slug).order_by(Pool.created_at.desc())
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_all(self, offset: int = 0, limit: int = 100) -> List[Pool]:
        statement = select(Pool).offset(offset).limit(limit).order_by(Pool.created_at.desc())
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def delete(self, pool: Pool) -> bool:
        await self.session.delete(pool)
        await self.session.commit()
        return True


def get_pool_repository(db: AsyncSession = Depends(get_db_session)) -> PoolRepository:
    return PoolRepository(db)
