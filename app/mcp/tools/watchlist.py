import asyncio
import json
import os
from typing import Optional

from app.mcp.server import mcp
from app.mcp.services import stock_service, watchlist_service


@mcp.tool()
async def get_watchlist(user_id: Optional[str] = None) -> str:
    """
    Get the saved watchlist for a Prismalis user, enriched with live profile
    and quote data for each symbol.

    Args:
        user_id: Prismalis user UUID. Falls back to the PRISMALIS_USER_ID
                 environment variable when not provided.
    """
    uid = user_id or os.getenv("PRISMALIS_USER_ID")
    if not uid:
        return (
            "No user_id supplied. Pass it as an argument or set the "
            "PRISMALIS_USER_ID environment variable."
        )

    try:
        symbols = await watchlist_service().list_symbols(uid)
        if not symbols:
            return json.dumps({"user_id": uid, "watchlist": []})

        svc = stock_service()
        items = await asyncio.gather(
            *(svc.get_profile_with_quote(s) for s in symbols),
            return_exceptions=True,
        )

        result = [
            item if not isinstance(item, Exception) else {"symbol": sym, "error": str(item)}
            for sym, item in zip(symbols, items)
        ]
        return json.dumps({"user_id": uid, "watchlist": result}, default=str, indent=2)
    except Exception as e:
        return f"Error: {e}"
