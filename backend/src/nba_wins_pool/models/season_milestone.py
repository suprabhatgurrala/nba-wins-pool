from datetime import datetime, date, timezone
from sqlmodel import SQLModel, Field, Relationship
import uuid


class SeasonMilestone(SQLModel, table=True):
    """Season milestones like All-Star break, playoffs, etc."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pool_id: uuid.UUID = Field(foreign_key="pool.id", index=True)
    season: str = Field(index=True)
    slug: str = Field(index=True)
    date: date
    description: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # Relationships
    pool: "Pool" = Relationship(back_populates="milestones")
