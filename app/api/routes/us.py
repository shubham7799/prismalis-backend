from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.routes.auth import get_current_user
from app.core.config import get_settings
from app.services.fmp_service import (
    FMPConfigurationError,
    FMPRequestError,
    FMPService,
    FMPServiceError,
)

router = APIRouter(prefix="/us", tags=["fmp"], dependencies=[Depends(get_current_user)])


def get_fmp_service() -> FMPService:
    settings = get_settings()
    return FMPService(
        api_key=settings.fmp_api_key,
        base_url=settings.fmp_base_url,
        api_version=settings.fmp_api_version,
        timeout_seconds=settings.fmp_timeout_seconds,
        max_retries=settings.fmp_max_retries,
    )


def to_http_error(exc: FMPServiceError) -> HTTPException:
    if isinstance(exc, FMPConfigurationError):
        return HTTPException(status_code=500, detail=str(exc))

    if isinstance(exc, FMPRequestError) and exc.status_code:
        return HTTPException(status_code=exc.status_code, detail=str(exc))

    return HTTPException(status_code=502, detail=str(exc))


@router.get("/search")
async def search_symbols(
    query: str = Query(..., min_length=1),
    limit: int = Query(default=10, ge=1, le=100),
    exchange: Optional[str] = None,
    fmp_service: FMPService = Depends(get_fmp_service),
):
    try:
        return await fmp_service.search_symbols(query=query, limit=limit, exchange=exchange)
    except FMPServiceError as exc:
        raise to_http_error(exc) from exc


@router.get("/stocks")
async def get_stock_list(
    fmp_service: FMPService = Depends(get_fmp_service),
):
    try:
        return await fmp_service.get_stock_list()
    except FMPServiceError as exc:
        raise to_http_error(exc) from exc


@router.get("/stocks/{symbol}/profile")
async def get_company_profile(
    symbol: str,
    fmp_service: FMPService = Depends(get_fmp_service),
):
    try:
        return await fmp_service.get_company_profile(symbol)
    except FMPServiceError as exc:
        raise to_http_error(exc) from exc


@router.get("/stocks/{symbol}/quote")
async def get_quote(
    symbol: str,
    fmp_service: FMPService = Depends(get_fmp_service),
):
    try:
        return await fmp_service.get_quote(symbol)
    except FMPServiceError as exc:
        raise to_http_error(exc) from exc


@router.get("/stocks/{symbol}/dataset")
async def get_company_dataset(
    symbol: str,
    period: str = Query(default="annual", pattern="^(annual|quarter)$"),
    limit: int = Query(default=5, ge=1, le=120),
    fmp_service: FMPService = Depends(get_fmp_service),
):
    try:
        return await fmp_service.get_company_dataset(
            symbol=symbol,
            period=period,
            limit=limit,
        )
    except FMPServiceError as exc:
        raise to_http_error(exc) from exc


@router.get("/stocks/{symbol}/historical-prices")
async def get_historical_prices(
    symbol: str,
    from_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    to_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    timeseries: Optional[int] = Query(default=None, ge=1),
    fmp_service: FMPService = Depends(get_fmp_service),
):
    try:
        return await fmp_service.get_historical_prices(
            symbol=symbol,
            from_date=from_date,
            to_date=to_date,
            timeseries=timeseries,
        )
    except FMPServiceError as exc:
        raise to_http_error(exc) from exc
