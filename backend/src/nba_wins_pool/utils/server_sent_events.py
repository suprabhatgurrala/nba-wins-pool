import asyncio
from typing import AsyncGenerator, Dict, Optional

from nba_wins_pool.event.broker import Broker
from nba_wins_pool.event.core import Event, Topic

"""
This creates an event generator that can be used to stream server-sent events (SSE)
from our broker implementation to the client.
"""


async def sse_event_generator(
    topic: Topic, broker: Broker, initial_event: Optional[Dict] = None
) -> AsyncGenerator[Dict, None]:
    queue: asyncio.Queue[Event] = asyncio.Queue()

    async def subscriber(event: Event):
        await queue.put(event)

    broker.subscribe(topic, subscriber)

    try:
        # Response headers aren't flushed until the first message, so send one right away to let the
        # client's EventSource open immediately instead of waiting for the first event or ping.
        if initial_event is not None:
            yield initial_event
        while True:
            event = await queue.get()
            yield {"event": event.type, "data": event.model_dump_json(exclude={"type"})}
    except asyncio.CancelledError:
        pass
    finally:
        broker.unsubscribe(topic, subscriber)
