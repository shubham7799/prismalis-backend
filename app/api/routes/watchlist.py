import asyncio

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.routes.auth import get_current_user
from app.api.routes.us import get_stock_data_service
from app.services.fmp_service import FMPServiceError
from app.services.market_data_service import StockDataService
from app.services.watchlist_service import WatchlistService

router = APIRouter(prefix="/watchlist", tags=["watchlist"], dependencies=[Depends(get_current_user)])


def get_watchlist_service() -> WatchlistService:
    return WatchlistService()


@router.get("")
async def get_watchlist(
    current_user: dict = Depends(get_current_user),
    watchlist_service: WatchlistService = Depends(get_watchlist_service),
    stock_data_service: StockDataService = Depends(get_stock_data_service),
):
    symbols = await watchlist_service.list_symbols(current_user["id"])
    try:
        return await asyncio.gather(
            *(stock_data_service.get_profile_with_quote(symbol) for symbol in symbols)
        )
    except FMPServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{symbol}", status_code=status.HTTP_201_CREATED)
async def add_to_watchlist(
    symbol: str,
    current_user: dict = Depends(get_current_user),
    watchlist_service: WatchlistService = Depends(get_watchlist_service),
):
    await watchlist_service.add_symbol(current_user["id"], symbol)
    return {"symbol": symbol.upper(), "status": "added"}


@router.delete("/{symbol}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_watchlist(
    symbol: str,
    current_user: dict = Depends(get_current_user),
    watchlist_service: WatchlistService = Depends(get_watchlist_service),
):
    await watchlist_service.remove_symbol(current_user["id"], symbol)
