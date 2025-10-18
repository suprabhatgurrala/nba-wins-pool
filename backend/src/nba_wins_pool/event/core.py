from enum import Enum

from pydantic import BaseModel


class EventType(str, Enum):
    pass


class Event(BaseModel):
    type: EventType


class Topic(BaseModel):
    def __str__(self) -> str:
        raise NotImplementedError
