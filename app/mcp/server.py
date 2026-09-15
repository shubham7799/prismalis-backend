from contextlib import asynccontextmanager

from mcp.server.mcpserver import MCPServer

from app.core.orm import create_orm_tables, dispose_engine


@asynccontextmanager
async def lifespan(server: MCPServer):
    # Runs for the stdio entrypoint (mcp_server.py) and, when the HTTP app is
    # mounted, via StreamableHTTPSessionManager.run() from the FastAPI lifespan.
    await create_orm_tables()
    try:
        yield
    finally:
        await dispose_engine()


mcp = MCPServer(
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
