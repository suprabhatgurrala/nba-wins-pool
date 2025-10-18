from enum import IntEnum


class NBAGameStatus(IntEnum):
    """Enum representing the lifecycle status of an NBA game."""

    PREGAME = 1
    INGAME = 2
    FINAL = 3

    def is_final(self) -> bool:
        return self is NBAGameStatus.FINAL

    def __str__(self) -> str:  # pragma: no cover - convenience helper
        return self.name.lower()
