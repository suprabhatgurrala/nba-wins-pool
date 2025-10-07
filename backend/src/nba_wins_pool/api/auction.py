from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from nba_wins_pool.auction_data import get_auction_data

router = APIRouter()


@router.get("/data", response_class=Response)
def auction_data(request: Request, num_owners: int = 6, budget_per_owner: int = 200, teams_per_owner: int = 4):
    df = get_auction_data(num_owners=num_owners, budget_per_owner=budget_per_owner, teams_per_owner=teams_per_owner)
    return JSONResponse(
        {
            "data": df.to_dict(orient="records"),
        }
    )
