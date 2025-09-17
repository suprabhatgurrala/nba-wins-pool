import asyncio
import logging
from typing import Awaitable, Callable, Dict, List

from .core import Event, Topic

Subscriber = Callable[[Event], Awaitable[None]]

logger = logging.getLogger(__name__)


class Broker:
    """
    Common interface for event brokers.
    """

    async def publish(self, topic: Topic, event: Event):
        raise NotImplementedError

    def subscribe(self, topic: Topic, callback: Subscriber):
        raise NotImplementedError

    def unsubscribe(self, topic: Topic, callback: Subscriber):
        raise NotImplementedError


class LocalBroker(Broker):
    """
    Simple in-memory broker that can be used when running a single server instance.
    This should be replaced by a distributed broker when running multiple server instances.
    """

    def __init__(self):
        self.subscribers: Dict[str, List[Subscriber]] = {}

    def _total_subscribers(self, topic: Topic) -> int:
        return len(self.subscribers.get(str(topic), []))

    async def publish(self, topic: Topic, event: Event):
        for subscriber in self.subscribers.get(str(topic), []):
            try:
                asyncio.create_task(subscriber(event))
            except Exception as e:
                logger.error(f"Error publishing event {event}: {e}", exc_info=True)
        logger.info(
            f"Published event '{event.type}' to topic '{topic}', total subscribers: {self._total_subscribers(topic)}"
        )

    def subscribe(self, topic: Topic, callback: Subscriber):
        self.subscribers.setdefault(str(topic), []).append(callback)
        logger.info(f"Subscribed to topic '{topic}', total subscribers: {self._total_subscribers(topic)}")

    def unsubscribe(self, topic: Topic, callback: Subscriber):
        subs = self.subscribers.get(str(topic), [])
        if callback in subs:
            subs.remove(callback)
        if not subs:
            self.subscribers.pop(str(topic), None)
        logger.info(f"Unsubscribed from topic '{topic}', total subscribers: {self._total_subscribers(topic)}")


local_broker = LocalBroker()


def get_broker() -> Broker:
    return local_broker
