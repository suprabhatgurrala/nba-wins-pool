from datetime import date

FANDUEL_FULL_WEIGHT_DAYS = 1
FANDUEL_ZERO_WEIGHT_DAYS = 5


def fanduel_blend_weight(projection_date: date, today: date) -> float:
    """Weight of a FanDuel win total in a FanDuel/ESPN BPI blend, by its age.

    1.0 up to :data:`FANDUEL_FULL_WEIGHT_DAYS` old, falling linearly to 0.0 at
    :data:`FANDUEL_ZERO_WEIGHT_DAYS`. A pulled market keeps its last row, so an old
    projection date means FanDuel no longer lists the line.
    """
    age_days = (today - projection_date).days
    if age_days <= FANDUEL_FULL_WEIGHT_DAYS:
        return 1.0
    if age_days >= FANDUEL_ZERO_WEIGHT_DAYS:
        return 0.0
    return (FANDUEL_ZERO_WEIGHT_DAYS - age_days) / (FANDUEL_ZERO_WEIGHT_DAYS - FANDUEL_FULL_WEIGHT_DAYS)
