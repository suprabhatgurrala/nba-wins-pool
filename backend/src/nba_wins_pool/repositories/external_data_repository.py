"""Repository for external data storage operations."""

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.external_data import DataFormat, ExternalData
from nba_wins_pool.utils.time import utc_now


class ExternalDataRepository:
    """Repository for managing external API data storage."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, external_data: ExternalData) -> ExternalData:
        """Save a new external data record.

        Args:
            external_data: ExternalData instance to save

        Returns:
            Saved ExternalData instance with generated ID
        """
        self.session.add(external_data)
        await self.session.commit()
        await self.session.refresh(external_data)
        return external_data

    async def get_by_id(self, data_id: uuid.UUID) -> Optional[ExternalData]:
        """Get external data by ID.

        Args:
            data_id: UUID of the data record

        Returns:
            ExternalData instance or None if not found
        """
        statement = select(ExternalData).where(ExternalData.id == data_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_key(self, key: str) -> Optional[ExternalData]:
        """Get external data by key.

        Args:
            key: Unique key for the data record

        Returns:
            ExternalData instance or None if not found
        """
        statement = select(ExternalData).where(ExternalData.key == key)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_key_prefix(
        self, key_prefix: str, limit: int = 100
    ) -> List[ExternalData]:
        """Get external data by key prefix.

        Args:
            key_prefix: Prefix to match keys against
            limit: Maximum number of records to return

        Returns:
            List of ExternalData instances ordered by created_at desc
        """
        statement = (
            select(ExternalData)
            .where(ExternalData.key.like(f"{key_prefix}%"))
            .order_by(ExternalData.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def update(self, external_data: ExternalData) -> ExternalData:
        """Update an existing external data record.

        Args:
            external_data: ExternalData instance with updated values

        Returns:
            Updated ExternalData instance
        """
        external_data.updated_at = utc_now()
        self.session.add(external_data)
        await self.session.commit()
        await self.session.refresh(external_data)
        return external_data

    async def delete(self, external_data: ExternalData) -> bool:
        """Delete an external data record.

        Args:
            external_data: ExternalData instance to delete

        Returns:
            True if deleted successfully
        """
        await self.session.delete(external_data)
        await self.session.commit()
        return True

    async def delete_by_key(self, key: str) -> bool:
        """Delete an external data record by key.

        Args:
            key: Key of the record to delete

        Returns:
            True if deleted successfully, False if not found
        """
        statement = select(ExternalData).where(ExternalData.key == key)
        result = await self.session.execute(statement)
        record = result.scalar_one_or_none()

        if record:
            await self.session.delete(record)
            await self.session.commit()
            return True
        return False

    async def delete_older_than(self, cutoff_date: datetime) -> int:
        """Delete external data records older than a cutoff date.

        Useful for cleanup/archival operations.

        Args:
            cutoff_date: Delete records created before this date

        Returns:
            Number of records deleted
        """
        statement = select(ExternalData).where(ExternalData.created_at < cutoff_date)
        result = await self.session.execute(statement)
        records = result.scalars().all()

        count = len(records)
        for record in records:
            await self.session.delete(record)

        await self.session.commit()
        return count

    async def get_all(
        self,
        offset: int = 0,
        limit: int = 100,
        data_format: Optional[DataFormat] = None,
    ) -> List[ExternalData]:
        """Get all external data records with optional filters.

        Args:
            offset: Number of records to skip
            limit: Maximum number of records to return
            data_format: Optional filter by data format

        Returns:
            List of ExternalData instances ordered by created_at desc
        """
        statement = select(ExternalData)

        if data_format:
            statement = statement.where(ExternalData.data_format == data_format)

        statement = (
            statement.order_by(ExternalData.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        result = await self.session.execute(statement)
        return list(result.scalars().all())


def get_external_data_repository(
    db: AsyncSession = Depends(get_db_session),
) -> ExternalDataRepository:
    """Dependency injection for ExternalDataRepository.

    Args:
        db: Database session from FastAPI dependency

    Returns:
        ExternalDataRepository instance
    """
    return ExternalDataRepository(db)
