import re
from typing import Annotated

from pydantic import AfterValidator, StringConstraints


def validate_season(v: str) -> str:
    if not re.match(r"^\d{4}-\d{2}$", v):
        raise ValueError("season must be in format YYYY-YY, e.g., 2024-25")
    return v


SeasonStr = Annotated[
    str,
    StringConstraints(min_length=7, max_length=7),
    AfterValidator(validate_season),
]
