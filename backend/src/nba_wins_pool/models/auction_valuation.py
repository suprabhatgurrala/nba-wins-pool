"""Models for auction valuation data."""

from typing import Optional

from pydantic import BaseModel, Field


class TeamValuation(BaseModel):
    """Valuation data for a single NBA team.
    
    Contains odds-based probabilities and calculated auction value.
    """
    
    team: str = Field(description="Team name from FanDuel")
    team_id: Optional[str] = Field(None, description="UUID of the team in the database")
    logo_url: str = Field(description="URL to team logo")
    
    # Regular season data
    reg_season_wins: float = Field(description="Over/under line for regular season wins")
    over_reg_season_wins: Optional[float] = Field(None, description="Decimal odds for over")
    under_reg_season_wins: Optional[float] = Field(None, description="Decimal odds for under")
    over_reg_season_wins_prob: float = Field(description="Probability of going over")
    
    # Playoff data
    make_playoffs: Optional[float] = Field(None, description="Decimal odds to make playoffs")
    miss_playoffs: Optional[float] = Field(None, description="Decimal odds to miss playoffs")
    make_playoffs_prob: float = Field(description="Probability of making playoffs")
    
    # Conference and title odds
    conf: str = Field(description="Conference (East or West)")
    conf_odds: float = Field(description="Decimal odds to win conference")
    conf_prob: float = Field(description="Probability of winning conference")
    title_odds: float = Field(description="Decimal odds to win championship")
    title_prob: float = Field(description="Probability of winning championship")
    
    # Calculated values
    total_expected_wins: float = Field(description="Expected total wins (regular + playoff)")
    auction_value: float = Field(description="Calculated auction value in dollars")


class AuctionValuationData(BaseModel):
    """Response model for auction valuation data.
    
    Contains valuation data for all teams based on current odds.
    """
    
    data: list[TeamValuation] = Field(description="List of team valuations")
    num_participants: int = Field(description="Number of auction participants used in calculation")
    budget_per_participant: int = Field(description="Budget per participant used in calculation")
    teams_per_participant: int = Field(description="Teams per participant used in calculation")
    cached_at: str = Field(description="ISO timestamp when odds data was cached")
