from fastapi import APIRouter, Depends, status
from sse_starlette.sse import EventSourceResponse

from nba_wins_pool.event.broker import Broker, get_broker
from nba_wins_pool.event.core import Event, EventType, Topic
from nba_wins_pool.utils.server_sent_events import sse_event_generator

router = APIRouter()


class InternalTestTopic(Topic):
    def __str__(self) -> str:
        return "internal_test"


class InternalTestEvent(Event):
    type: EventType = "internal_test"
    message: str


@router.get("/sse/subscribe")
async def sse(broker: Broker = Depends(get_broker)):
    """Subscribe to internal test events"""
    return EventSourceResponse(sse_event_generator(InternalTestTopic(), broker))


# 204 created response
@router.post("/sse/publish", status_code=status.HTTP_204_NO_CONTENT)
async def publish(message: str, broker: Broker = Depends(get_broker)):
    """Publish an internal test event"""
    await broker.publish(InternalTestTopic(), InternalTestEvent(message=message))
