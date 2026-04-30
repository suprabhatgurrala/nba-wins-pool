from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

router = APIRouter()

_SIMULATOR_README = Path(__file__).parent.parent / "services" / "nba_simulator" / "README.md"


@router.get("/docs/simulation", response_class=PlainTextResponse)
async def simulation_methodology() -> str:
    """Return the simulation methodology README as markdown."""
    try:
        return _SIMULATOR_README.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Documentation not found")
