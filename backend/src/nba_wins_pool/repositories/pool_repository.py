from typing import Optional, List
from sqlmodel import select, Session
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from nba_wins_pool.models.pool import Pool, PoolCreate, PoolUpdate


class PoolRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, pool_data: PoolCreate) -> Pool:
        """Create a new pool"""
        pool = Pool.model_validate(pool_data)
        self.session.add(pool)
        await self.session.commit()
        await self.session.refresh(pool)
        return pool

    async def get_by_id(self, pool_id: uuid.UUID) -> Optional[Pool]:
        """Get pool by ID"""
        statement = select(Pool).where(Pool.id == pool_id)
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_by_slug(self, slug: str) -> Optional[Pool]:
        """Get pool by slug"""
        statement = select(Pool).where(Pool.slug == slug)
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_all(self, offset: int = 0, limit: int = 100) -> List[Pool]:
        """Get all pools"""
        statement = select(Pool).offset(offset).limit(limit).order_by(Pool.name.asc())
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def update(self, pool_id: uuid.UUID, update_data: PoolUpdate) -> Optional[Pool]:
        """Update pool"""
        pool = await self.get_by_id(pool_id)
        if not pool:
            return None

        pool_data = update_data.model_dump(exclude_unset=True)
        pool.sqlmodel_update(pool_data)
        self.session.add(pool)
        await self.session.commit()
        await self.session.refresh(pool)
        return pool

    async def delete(self, pool_id: uuid.UUID) -> bool:
        """Delete pool"""
        pool = await self.get_by_id(pool_id)
        if not pool:
            return False

        await self.session.delete(pool)
        await self.session.commit()
        return True

    async def slug_exists(self, slug: str) -> bool:
        """Check if slug exists"""
        pool = await self.get_by_slug(slug)
        return pool is not None
