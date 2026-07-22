from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.routes.auth import get_current_user
from app.mcp.services import fmp
from app.services.fmp_service import FMPServiceError

router = APIRouter(prefix="/screener", tags=["screener"])


class ScreenerRequest(BaseModel):
    sector: Optional[str] = Field(None, description="e.g. Technology, Healthcare, Energy, Financials")
    industry: Optional[str] = Field(None, description="e.g. Semiconductors, Software, Banks")
    market_cap_min: Optional[float] = Field(None, alias="marketCapMin", description="Min market cap in USD")
    market_cap_max: Optional[float] = Field(None, alias="marketCapMax", description="Max market cap in USD")
    pe_min: Optional[float] = Field(None, alias="peMin", description="Min P/E ratio")
    pe_max: Optional[float] = Field(None, alias="peMax", description="Max P/E ratio")
    price_min: Optional[float] = Field(None, alias="priceMin", description="Min stock price in USD")
    price_max: Optional[float] = Field(None, alias="priceMax", description="Max stock price in USD")
    beta_max: Optional[float] = Field(None, alias="betaMax", description="Max beta (volatility)")
    dividend_min: Optional[float] = Field(None, alias="dividendMin", description="Min dividend yield %")
    revenue_growth_min: Optional[float] = Field(None, alias="revenueGrowthMin", description="Min revenue growth as decimal, e.g. 0.15 for 15%")
    exchange: Optional[str] = Field(None, description="e.g. NASDAQ, NYSE")
    country: Optional[str] = Field(None, description="e.g. US, GB, IN")
    limit: int = Field(20, ge=1, le=100, description="Max number of results")

    model_config = {"populate_by_name": True}


@router.post("")
async def screen_stocks(
    body: ScreenerRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Screen stocks by fundamental and market criteria.

    All filters are optional — combine any number of them.
    Results are sorted by market cap descending.
    """
    fetch_limit = min(body.limit * 5, 250) if body.revenue_growth_min is not None else body.limit

    try:
        results = await fmp().screen_stocks(
            market_cap_min=body.market_cap_min,
            market_cap_max=body.market_cap_max,
            pe_min=body.pe_min,
            pe_max=body.pe_max,
            price_min=body.price_min,
            price_max=body.price_max,
            beta_max=body.beta_max,
            dividend_min=body.dividend_min,
            sector=body.sector,
            industry=body.industry,
            exchange=body.exchange,
            country=body.country,
            limit=fetch_limit,
        )
    except FMPServiceError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    if body.revenue_growth_min is not None:
        results = [
            s for s in results
            if (s.get("revenueGrowth") or 0) >= body.revenue_growth_min
        ]

    results = results[:body.limit]

    return {
        "count": len(results),
        "filters": body.model_dump(by_alias=True, exclude_none=True, exclude={"limit"}),
        "results": [
            {
                "symbol": s.get("symbol"),
                "name": s.get("companyName"),
                "sector": s.get("sector"),
                "industry": s.get("industry"),
                "exchange": s.get("exchangeShortName"),
                "country": s.get("country"),
                "price": s.get("price"),
                "marketCap": s.get("marketCap"),
                "pe": s.get("pe"),
                "beta": s.get("beta"),
                "dividendYield": s.get("lastAnnualDividend"),
                "revenueGrowth": s.get("revenueGrowth"),
                "volume": s.get("volume"),
            }
            for s in results
        ],
    }
