import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import LargeBinary, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel

from nba_wins_pool.utils.time import utc_now


class DataFormat(str, Enum):
    """Format of stored external data."""

    JSON = "json"
    BINARY = "binary"
    TEXT = "text"


class ExternalData(SQLModel, table=True):
    """Generic storage for external API data.

    Stores raw data from external APIs (NBA API, FanDuel, etc.) for
    long-term persistence and caching.
    """

    __tablename__ = "external_data"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    key: str = Field(max_length=100, unique=True, index=True)

    data_format: DataFormat = Field(default=DataFormat.JSON)

    data_json: Optional[dict] = Field(sa_column=Column(JSONB), default=None)
    data_text: Optional[str] = Field(sa_column=Column(Text), default=None)
    data_blob: Optional[bytes] = Field(sa_column=Column(LargeBinary), default=None)

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

class ExternalDataCreate(SQLModel):
    """Schema for creating external data records."""

    key: str = Field(max_length=100)
    data_format: DataFormat = Field(default=DataFormat.JSON)
    data_json: Optional[dict] = None
    data_text: Optional[str] = None
    data_blob: Optional[bytes] = None


class ExternalDataUpdate(SQLModel):
    """Schema for updating external data records."""

    data_json: Optional[dict] = None
    data_text: Optional[str] = None
    data_blob: Optional[bytes] = None

