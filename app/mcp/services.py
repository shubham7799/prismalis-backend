"""Shared lazy service factories for MCP tools."""

from typing import Optional

from app.core.config import get_settings
from app.services.fmp_service import FMPService
from app.services.market_data_service import MarketDataService, StockDataService
from app.services.watchlist_service import WatchlistService

_stock_service: Optional[StockDataService] = None
_watchlist_service: Optional[WatchlistService] = None


def fmp() -> FMPService:
    s = get_settings()
    return FMPService(
        api_key=s.fmp_api_key,
        base_url=s.fmp_base_url,
        api_version=s.fmp_api_version,
        timeout_seconds=s.fmp_timeout_seconds,
        max_retries=s.fmp_max_retries,
    )


def stock_service() -> StockDataService:
    global _stock_service
    if _stock_service is None:
        _stock_service = StockDataService(fmp_service=fmp())
    return _stock_service


def watchlist_service() -> WatchlistService:
    global _watchlist_service
    if _watchlist_service is None:
        _watchlist_service = WatchlistService()
    return _watchlist_service
