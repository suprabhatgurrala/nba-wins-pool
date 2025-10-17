import logging
from typing import List
from uuid import UUID

from fastapi import Depends

from nba_wins_pool.event.broker import Broker, get_broker
from nba_wins_pool.models.auction import AuctionEvent, AuctionTopic
from nba_wins_pool.models.auction_event_log import AuctionEventLog
from nba_wins_pool.repositories.auction_event_log_repository import (
    AuctionEventLogRepository,
    get_auction_event_log_repository,
)

logger = logging.getLogger(__name__)


class AuctionEventService:
    """
    Centralized service for handling auction events.
    Ensures events are persisted to database first, then published to SSE.
    """

    def __init__(
        self,
        event_log_repository: AuctionEventLogRepository,
        event_broker: Broker,
    ):
        self.event_log_repository = event_log_repository
        self.event_broker = event_broker

    async def publish_and_persist(self, event: AuctionEvent) -> None:
        """
        Persist event to database first, then publish to SSE broker.

        Order matters:
        1. Persist to DB (source of truth, will raise on failure)
        2. Publish to SSE (best effort, logs on failure)

        This ensures the historical record is always consistent.
        """
        # Step 1: Persist to database (critical - will raise on failure)
        try:
            event_log = AuctionEventLog(
                auction_id=event.auction_id,
                event_type=event.type.value,
                payload=event.model_dump(mode="json"),
                created_at=event.created_at,
            )
            await self.event_log_repository.save(event_log)
        except Exception as e:
            logger.error(
                f"Failed to persist {event.type} event for auction {event.auction_id}: {e}",
                exc_info=True,
            )
            raise  # Re-raise to fail the operation

        # Step 2: Publish to SSE (best effort - don't fail operation if this fails)
        try:
            topic = AuctionTopic(auction_id=event.auction_id)
            await self.event_broker.publish(topic=topic, event=event)
        except Exception as e:
            logger.error(
                f"Failed to publish {event.type} event for auction {event.auction_id}: {e}",
                exc_info=True,
            )
            # Don't raise - event is already persisted, SSE failure shouldn't block

    async def get_history(self, auction_id: UUID) -> List[dict]:
        """Get all historical events for an auction"""
        event_logs = await self.event_log_repository.get_by_auction_id(auction_id)
        return [log.payload for log in event_logs]


def get_auction_event_service(
    event_log_repository: AuctionEventLogRepository = Depends(get_auction_event_log_repository),
    event_broker: Broker = Depends(get_broker),
) -> AuctionEventService:
    return AuctionEventService(
        event_log_repository=event_log_repository,
        event_broker=event_broker,
    )
