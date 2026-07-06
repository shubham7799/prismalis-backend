from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.core.orm import get_session
from app.models.watchlist import WatchlistItem
from app.services.market_data_service import MarketDataService


class WatchlistService:
    def __init__(self, market_data_service: Optional[MarketDataService] = None):
        self.market_data_service = market_data_service or MarketDataService()

    async def add_symbol(self, user_id: str, symbol: str) -> None:
        symbol = symbol.upper()
        await self.market_data_service.ensure_profile_stub(symbol)

        stmt = insert(WatchlistItem).values(user_id=user_id, symbol=symbol)
        stmt = stmt.on_conflict_do_nothing(index_elements=["user_id", "symbol"])

        async with get_session() as session:
            await session.execute(stmt)
            await session.commit()

    async def remove_symbol(self, user_id: str, symbol: str) -> None:
        async with get_session() as session:
            await session.execute(
                delete(WatchlistItem).where(
                    WatchlistItem.user_id == user_id, WatchlistItem.symbol == symbol.upper()
                )
            )
            await session.commit()

    async def list_symbols(self, user_id: str) -> list:
        async with get_session() as session:
            result = await session.execute(
                select(WatchlistItem.symbol)
                .where(WatchlistItem.user_id == user_id)
                .order_by(WatchlistItem.added_at.desc())
            )
            return [row[0] for row in result.all()]
