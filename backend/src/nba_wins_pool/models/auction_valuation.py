"""Models for auction valuation data."""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TeamValuation(BaseModel):
    """Valuation data for a single NBA team.

    Contains odds-based probabilities and calculated auction value.
    """

    team_name: str = Field(None, description="Team name")
    conference: str = Field(None, description="Conference (East or West)")
    team_id: Optional[UUID] = Field(None, description="UUID of the team in the database")
    logo_url: Optional[str] = Field(None, description="URL to team logo")

    reg_season_wins: Optional[float] = Field(None, description="Over/under line for regular season wins")
    over_wins_prob: Optional[float] = Field(None, description="Probability of going over")
    make_playoffs_prob: Optional[float] = Field(None, description="Probability of making playoffs")
    win_conference_prob: Optional[float] = Field(None, description="Probability of winning conference")
    win_finals_prob: Optional[float] = Field(None, description="Probability of winning championship")

    expected_wins: Optional[float] = Field(None, description="Expected total wins (regular + playoff)")
    auction_value: Optional[float] = Field(None, description="Calculated auction value in dollars")


class AuctionValuationData(BaseModel):
    """Response model for auction valuation data.

    Contains valuation data for all teams based on current odds.
    """

    data: list[TeamValuation] = Field(description="List of team valuations")
    num_participants: int = Field(description="Number of auction participants used in calculation")
    budget_per_participant: int = Field(description="Budget per participant used in calculation")
    teams_per_participant: int = Field(description="Teams per participant used in calculation")
    cached_at: str = Field(description="ISO timestamp when odds data was cached")
