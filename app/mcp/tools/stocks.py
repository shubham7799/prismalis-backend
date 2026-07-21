import json

from app.mcp.server import mcp
from app.mcp.services import fmp, stock_service
from app.services.fmp_service import FMPServiceError


@mcp.tool()
async def get_quote(symbol: str) -> str:
    """
    Get the live quote for a US stock ticker.

    Returns current price, change, change percentage, volume, market cap,
    day range, 52-week range, and 50/200-day moving averages.

    Args:
        symbol: Ticker symbol, e.g. AAPL, NVDA, TSLA
    """
    try:
        data = await stock_service().get_quote_only(symbol.upper())
        return json.dumps(data, default=str, indent=2)
    except FMPServiceError as e:
        return f"Error: {e}"


@mcp.tool()
async def get_profile(symbol: str) -> str:
    """
    Get the company profile and live quote for a US stock ticker.

    Returns company name, sector, industry, description, CEO, employee count,
    website, country, IPO date, exchange, beta, ETF/ADR flags, and current price.

    Args:
        symbol: Ticker symbol, e.g. AAPL, NVDA, TSLA
    """
    try:
        data = await stock_service().get_profile_with_quote(symbol.upper())
        return json.dumps(data, default=str, indent=2)
    except FMPServiceError as e:
        return f"Error: {e}"


@mcp.tool()
async def get_financials(
    symbol: str,
    period: str = "annual",
    limit: int = 5,
) -> str:
    """
    Get the full financial dataset for a US stock ticker.

    Bundles profile, live quote, income statements, balance sheets,
    cash flow statements, key metrics, financial ratios, growth rates,
    and enterprise values — all in one call with DB caching.

    Args:
        symbol: Ticker symbol, e.g. AAPL, NVDA, TSLA
        period: "annual" or "quarter" (default: annual)
        limit:  Number of periods to return, 1–12 (default: 5)
    """
    if period not in ("annual", "quarter"):
        return "Invalid period. Use 'annual' or 'quarter'."
    limit = max(1, min(12, limit))
    try:
        data = await stock_service().get_company_dataset(symbol.upper(), period=period, limit=limit)
        return json.dumps(data, default=str, indent=2)
    except FMPServiceError as e:
        return f"Error: {e}"


@mcp.tool()
async def get_price_history(
    symbol: str,
    timeseries: int = 365,
) -> str:
    """
    Get historical daily OHLCV (open, high, low, close, volume) price data
    for a US stock ticker.

    Args:
        symbol:     Ticker symbol, e.g. AAPL, NVDA, TSLA
        timeseries: Number of trading days to return, 1–1825 (default: 365)
    """
    timeseries = max(1, min(1825, timeseries))
    try:
        data = await fmp().get_historical_prices(symbol.upper(), timeseries=timeseries)
        return json.dumps(data, default=str, indent=2)
    except FMPServiceError as e:
        return f"Error: {e}"
