"""Utilities for NBA season handling."""

from datetime import date

from nba_wins_pool.types.season_str import SeasonStr


def get_current_season(reference_date: date | None = None) -> SeasonStr:
    """Determine the current NBA season based on a reference date.
    
    NBA season runs from October to June. For example:
    - October 2024 - June 2025 = "2024-25" season
    - July 2025 - September 2025 = "2024-25" season (offseason)
    - October 2025 - June 2026 = "2025-26" season
    
    Args:
        reference_date: Date to determine the season for. If None, uses today's date.
        
    Returns:
        Season string in format YYYY-YY (e.g., "2024-25")
        
    Examples:
        >>> from datetime import date
        >>> get_current_season(date(2024, 10, 1))  # October 2024
        '2024-25'
        >>> get_current_season(date(2025, 6, 15))  # June 2025
        '2024-25'
        >>> get_current_season(date(2025, 9, 1))   # September 2025 (offseason)
        '2024-25'
        >>> get_current_season(date(2025, 10, 1))  # October 2025
        '2025-26'
    """
    if reference_date is None:
        reference_date = date.today()
    
    year = reference_date.year
    month = reference_date.month
    
    # If before October, we're in the previous season
    if month < 10:
        start_year = year - 1
    else:
        start_year = year
    
    end_year = start_year + 1
    return f"{start_year}-{str(end_year)[2:]}"
