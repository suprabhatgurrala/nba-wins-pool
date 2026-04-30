from enum import Enum


class NBAGameType(str, Enum):
    """Enum representing the phase of the NBA season a game belongs to."""

    PRESEASON = "Preseason"
    REGULAR_SEASON = "Regular Season"
    PLAY_IN = "Play-In"
    PLAYOFFS = "Playoffs"

    def __str__(self) -> str:
        return self.value
