from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from app.core.orm import create_orm_tables, dispose_engine


@asynccontextmanager
async def lifespan(server: FastMCP):
    await create_orm_tables()
    try:
        yield
    finally:
        await dispose_engine()


mcp = FastMCP(
    name="prismalis",
    instructions=(
        "Stock research tools powered by Prismalis. "
        "Use get_quote for live price, get_profile for company info, "
        "get_financials for full fundamental datasets (income / balance sheet / "
        "cash flow / ratios / growth), get_price_history for OHLCV data, "
        "and get_watchlist to retrieve a user's saved watchlist."
    ),
    lifespan=lifespan,
)
