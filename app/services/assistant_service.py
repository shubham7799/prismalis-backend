import asyncio
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, AsyncIterator

from sqlalchemy import select

from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage
from langchain_core.tools import tool

from app.core.config import get_settings
from app.core.orm import get_session
from app.mcp.services import fmp, stock_service
from app.models.market_data import (
    BalanceSheet,
    CashFlowStatement,
    FinancialGrowth,
    IncomeStatement,
    KeyMetrics,
    Profile,
    Quote,
    Ratios,
)
from app.services.fmp_service import FMPRateLimitError, FMPServiceError
from app.services.market_data_service import _period_filter

SYSTEM_PROMPT = (
    "You are a financial research assistant for Prismalis, a stock analysis platform. "
    "You have access to real-time stock data tools. Use them to answer user questions about "
    "stocks, companies, financials, and market data. Be concise, accurate, and cite the data "
    "you retrieve. When discussing financials, highlight key metrics like revenue growth, "
    "margins, and valuation. When the user asks to compare two or more stocks, use the "
    "compare_stocks tool instead of calling individual quote/financials tools per symbol, "
    "and present the comparison as a clear table or side-by-side summary."
)

STOCK_SYSTEM_PROMPT_TEMPLATE = (
    "You are a financial research assistant embedded on the stock detail page for {symbol} "
    "on Prismalis, a stock analysis platform. Answer only using data returned by your tools — "
    "all of it comes directly from this project's database, never invent, estimate, or recall "
    "numbers from your own knowledge. If a tool reports that data is missing, say so plainly "
    "instead of guessing. When the user asks to see a specific section of the page (e.g. "
    "'show me past results', 'take me to the balance sheet', 'show ratios'), call "
    "navigate_to_tab with the matching tab in addition to answering their question."
)

RATE_LIMIT_MESSAGE = (
    "The stock data provider is currently rate-limited. Do not retry this tool again in this turn — "
    "tell the user the data is temporarily unavailable and to try again in a minute."
)


# ---------------------------------------------------------------------------
# General assistant tools (live FMP data, cached via StockDataService)
# ---------------------------------------------------------------------------

@tool
async def stock_quote(symbol: str) -> str:
    """Get the live price quote for a US stock ticker (price, change, volume, market cap, moving averages)."""
    try:
        data = await stock_service().get_quote_only(symbol.upper())
        return json.dumps(data, default=str, indent=2)
    except FMPRateLimitError:
        return RATE_LIMIT_MESSAGE
    except FMPServiceError as e:
        return f"Error fetching quote: {e}"


@tool
async def company_profile(symbol: str) -> str:
    """Get the company profile for a US stock ticker (name, sector, industry, description, CEO, exchange)."""
    try:
        data = await stock_service().get_profile_with_quote(symbol.upper())
        return json.dumps(data, default=str, indent=2)
    except FMPRateLimitError:
        return RATE_LIMIT_MESSAGE
    except FMPServiceError as e:
        return f"Error fetching profile: {e}"


@tool
async def company_financials(symbol: str, period: str = "annual", limit: int = 5) -> str:
    """Get full financial statements for a US stock ticker.

    Args:
        symbol: Ticker symbol, e.g. AAPL
        period: 'annual' or 'quarter'
        limit: Number of periods to return (1-12)
    """
    if period not in ("annual", "quarter"):
        return "Invalid period. Use 'annual' or 'quarter'."
    limit = max(1, min(12, limit))
    try:
        data = await stock_service().get_company_dataset(symbol.upper(), period=period, limit=limit)
        return json.dumps(data, default=str, indent=2)
    except FMPRateLimitError:
        return RATE_LIMIT_MESSAGE
    except FMPServiceError as e:
        return f"Error fetching financials: {e}"


@tool
async def price_history(symbol: str, days: int = 365) -> str:
    """Get historical daily OHLCV price data for a US stock ticker.

    Args:
        symbol: Ticker symbol, e.g. AAPL
        days: Number of trading days to return (1-1825)
    """
    days = max(1, min(1825, days))
    try:
        data = await fmp().get_historical_prices(symbol.upper(), timeseries=days)
        return json.dumps(data, default=str, indent=2)
    except FMPRateLimitError:
        return RATE_LIMIT_MESSAGE
    except FMPServiceError as e:
        return f"Error fetching price history: {e}"


@tool
async def screen_stocks(
    sector: str | None = None,
    industry: str | None = None,
    market_cap_min: float | None = None,
    market_cap_max: float | None = None,
    pe_min: float | None = None,
    pe_max: float | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    beta_max: float | None = None,
    dividend_min: float | None = None,
    revenue_growth_min: float | None = None,
    limit: int = 20,
) -> str:
    """Screen and filter stocks by fundamental and market criteria.

    Args:
        sector: e.g. 'Technology', 'Healthcare', 'Energy', 'Financials', 'Consumer Cyclical'
        industry: e.g. 'Semiconductors', 'Software', 'Banks'
        market_cap_min: Minimum market cap in USD (e.g. 10000000000 for $10B)
        market_cap_max: Maximum market cap in USD
        pe_min: Minimum P/E ratio
        pe_max: Maximum P/E ratio (e.g. 25 to find value stocks)
        price_min: Minimum stock price in USD
        price_max: Maximum stock price in USD
        beta_max: Maximum beta (e.g. 1.0 for low-volatility stocks)
        dividend_min: Minimum dividend yield as percentage (e.g. 2.0 for 2%+)
        revenue_growth_min: Minimum annual revenue growth as decimal (e.g. 0.15 for 15%+).
                            Applied as a post-filter since FMP does not support it natively.
        limit: Max results to return (default 20, max 50)
    """
    limit = max(1, min(50, limit))
    fetch_limit = min(limit * 5, 100) if revenue_growth_min is not None else limit

    try:
        results = await fmp().screen_stocks(
            market_cap_min=market_cap_min,
            market_cap_max=market_cap_max,
            pe_min=pe_min,
            pe_max=pe_max,
            price_min=price_min,
            price_max=price_max,
            beta_max=beta_max,
            dividend_min=dividend_min,
            sector=sector,
            industry=industry,
            limit=fetch_limit,
        )
    except FMPRateLimitError:
        return RATE_LIMIT_MESSAGE
    except FMPServiceError as e:
        return f"Error running screener: {e}"

    if not results:
        return "No stocks matched the given criteria."

    if revenue_growth_min is not None:
        filtered = []
        for stock in results:
            growth = stock.get("revenueGrowth") or stock.get("revenue_growth")
            if growth is not None and growth >= revenue_growth_min:
                filtered.append(stock)
        results = filtered[:limit]
        if not results:
            return "No stocks matched after applying revenue growth filter."

    output = []
    for s in results:
        output.append({
            "symbol": s.get("symbol"),
            "name": s.get("companyName"),
            "sector": s.get("sector"),
            "industry": s.get("industry"),
            "price": s.get("price"),
            "marketCap": s.get("marketCap"),
            "pe": s.get("pe"),
            "beta": s.get("beta"),
            "dividendYield": s.get("lastAnnualDividend"),
            "exchange": s.get("exchangeShortName"),
        })

    return json.dumps(output, default=str, indent=2)


@tool
async def compare_stocks(symbols: list[str], period: str = "annual") -> str:
    """Compare 2-4 stocks side by side on price, valuation, profitability, and growth metrics.

    Args:
        symbols: List of 2-4 ticker symbols to compare, e.g. ["AAPL", "MSFT", "GOOGL"]
        period: 'annual' or 'quarter' for financial metrics
    """
    if period not in ("annual", "quarter"):
        return "Invalid period. Use 'annual' or 'quarter'."
    if len(symbols) < 2:
        return "Provide at least 2 symbols to compare."
    if len(symbols) > 4:
        return "Compare at most 4 symbols at a time for a readable result."

    symbols = [s.upper() for s in symbols]
    svc = stock_service()

    async def _one(symbol: str) -> dict:
        try:
            dataset = await svc.get_company_dataset(symbol, period=period, limit=1)
        except FMPRateLimitError:
            return {"symbol": symbol, "error": "rate_limited"}
        except FMPServiceError as e:
            return {"symbol": symbol, "error": str(e)}

        # get_company_dataset returns each section as a list of rows
        profile = (dataset.get("profile") or [{}])[0]
        quote = (dataset.get("quote") or [{}])[0]
        ratios = (dataset.get("ratios") or [{}])[0]
        growth = (dataset.get("financial_growth") or [{}])[0]
        key_metrics = (dataset.get("key_metrics") or [{}])[0]

        return {
            "symbol": symbol,
            "name": profile.get("companyName") or profile.get("company_name"),
            "sector": profile.get("sector"),
            "industry": profile.get("industry"),
            "price": quote.get("price"),
            "marketCap": quote.get("marketCap") or quote.get("market_cap"),
            "peRatio": ratios.get("priceToEarningsRatio") or ratios.get("price_to_earnings_ratio"),
            "priceToSales": ratios.get("priceToSalesRatio") or ratios.get("price_to_sales_ratio"),
            "priceToBook": ratios.get("priceToBookRatio") or ratios.get("price_to_book_ratio"),
            "grossMargin": ratios.get("grossProfitMargin") or ratios.get("gross_profit_margin"),
            "netMargin": ratios.get("netProfitMargin") or ratios.get("net_profit_margin"),
            "returnOnEquity": key_metrics.get("returnOnEquity") or key_metrics.get("return_on_equity"),
            "revenueGrowth": growth.get("revenueGrowth") or growth.get("revenue_growth"),
            "netIncomeGrowth": growth.get("netIncomeGrowth") or growth.get("net_income_growth"),
            "debtToEquity": ratios.get("debtToEquityRatio") or ratios.get("debt_to_equity_ratio"),
            "dividendYield": ratios.get("dividendYieldPercentage") or ratios.get("dividend_yield_percentage"),
        }

    results = await asyncio.gather(*(_one(s) for s in symbols))

    if all("error" in r for r in results):
        if any(r["error"] == "rate_limited" for r in results):
            return RATE_LIMIT_MESSAGE
        return "Could not fetch data for any of the requested symbols."

    return json.dumps(list(results), default=str, indent=2)


TOOLS = [stock_quote, company_profile, company_financials, price_history, screen_stocks, compare_stocks]


# ---------------------------------------------------------------------------
# Per-stock chat tools — DB-only, no live FMP calls, plus UI navigation
# ---------------------------------------------------------------------------

STATEMENT_MODELS = {
    "income": IncomeStatement,
    "balance_sheet": BalanceSheet,
    "cash_flow": CashFlowStatement,
    "ratios": Ratios,
    "key_metrics": KeyMetrics,
    "financial_growth": FinancialGrowth,
}

VALID_TABS = (
    "overview",
    "financials",
    "results",
    "balance_sheet",
    "cash_flow",
    "ratios",
    "news",
    "watchlist",
)


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _row_to_dict(row: Any) -> dict:
    return {c.name: _serialize(getattr(row, c.name)) for c in row.__table__.columns}


async def _fetch_rows(model, symbol: str, period: str, limit: int) -> list:
    query = select(model).where(model.symbol == symbol.upper())
    if hasattr(model, "period"):
        query = query.where(_period_filter(model, period))
    if hasattr(model, "fiscal_year"):
        query = query.order_by(model.fiscal_year.desc())
    elif hasattr(model, "date"):
        query = query.order_by(model.date.desc())
    query = query.limit(limit)

    async with get_session() as session:
        result = await session.execute(query)
        return list(result.scalars().all())


async def symbol_has_data(symbol: str) -> bool:
    async with get_session() as session:
        result = await session.execute(select(Profile).where(Profile.symbol == symbol.upper()))
        return result.scalar_one_or_none() is not None


def _build_stock_tools(symbol: str) -> tuple[list, dict]:
    """Returns (tools, ui_action). navigate_to_tab writes into ui_action so the
    caller can read the triggered frontend action after the agent run completes."""
    ui_action: dict = {}

    @tool
    async def get_company_snapshot() -> str:
        """Get the company profile, latest quote, and latest ratios/key metrics for
        this stock, read directly from the database."""
        async with get_session() as session:
            profile_row = (
                await session.execute(select(Profile).where(Profile.symbol == symbol.upper()))
            ).scalar_one_or_none()
            quote_row = (
                await session.execute(select(Quote).where(Quote.symbol == symbol.upper()))
            ).scalar_one_or_none()

        if profile_row is None:
            return f"No cached data found for {symbol.upper()} in the database."

        ratios_rows = await _fetch_rows(Ratios, symbol, "annual", 1)
        metrics_rows = await _fetch_rows(KeyMetrics, symbol, "annual", 1)

        return json.dumps(
            {
                "profile": _row_to_dict(profile_row),
                "quote": _row_to_dict(quote_row) if quote_row else None,
                "latest_ratios": _row_to_dict(ratios_rows[0]) if ratios_rows else None,
                "latest_key_metrics": _row_to_dict(metrics_rows[0]) if metrics_rows else None,
            },
            default=str,
            indent=2,
        )

    @tool
    async def get_financial_statement(statement: str, period: str = "annual", limit: int = 5) -> str:
        """Get raw financial statement rows for this stock directly from the database.

        Args:
            statement: One of 'income', 'balance_sheet', 'cash_flow', 'ratios', 'key_metrics', 'financial_growth'
            period: 'annual' or 'quarter'
            limit: Number of most recent fiscal periods to return (1-12)
        """
        model = STATEMENT_MODELS.get(statement)
        if model is None:
            return f"Invalid statement type. Choose from: {', '.join(STATEMENT_MODELS)}"
        if period not in ("annual", "quarter"):
            return "Invalid period. Use 'annual' or 'quarter'."
        limit = max(1, min(12, limit))

        rows = await _fetch_rows(model, symbol, period, limit)
        if not rows:
            return f"No {statement} data cached for {symbol.upper()} in the database."
        return json.dumps([_row_to_dict(r) for r in rows], default=str, indent=2)

    @tool
    async def compute_yoy_growth(metric: str, statement: str = "income", period: str = "annual") -> str:
        """Compute year-over-year growth for a specific financial metric using the two
        most recent fiscal periods stored in the database.

        Args:
            metric: Exact column name of the metric, e.g. 'revenue', 'net_income', 'gross_profit',
                    'operating_income', 'eps', 'free_cash_flow', 'total_assets', 'total_debt'
            statement: Which statement the metric belongs to: 'income', 'balance_sheet',
                       'cash_flow', 'ratios', or 'key_metrics'
            period: 'annual' or 'quarter'
        """
        model = STATEMENT_MODELS.get(statement)
        if model is None:
            return f"Invalid statement type. Choose from: {', '.join(STATEMENT_MODELS)}"
        if not hasattr(model, metric):
            return f"'{metric}' is not a valid column on the {statement} statement."
        if period not in ("annual", "quarter"):
            return "Invalid period. Use 'annual' or 'quarter'."

        rows = await _fetch_rows(model, symbol, period, 2)
        if len(rows) < 2:
            return f"Not enough historical data cached for {symbol.upper()} to compute YoY growth on '{metric}'."

        latest, previous = rows[0], rows[1]
        latest_val = getattr(latest, metric)
        previous_val = getattr(previous, metric)

        if latest_val is None or previous_val is None:
            return f"'{metric}' is missing for one of the two most recent periods."
        if float(previous_val) == 0:
            return f"Cannot compute percentage growth for '{metric}' because the prior period value is 0."

        growth_pct = (float(latest_val) - float(previous_val)) / abs(float(previous_val)) * 100

        return json.dumps(
            {
                "symbol": symbol.upper(),
                "metric": metric,
                "statement": statement,
                "period": period,
                "latest_fiscal_year": latest.fiscal_year,
                "latest_value": _serialize(latest_val),
                "previous_fiscal_year": previous.fiscal_year,
                "previous_value": _serialize(previous_val),
                "yoy_growth_percent": round(growth_pct, 2),
            },
            indent=2,
        )

    @tool
    async def navigate_to_tab(tab: str) -> str:
        """Tell the frontend to switch the stock detail page to a specific tab and
        scroll to it.

        Args:
            tab: One of 'overview', 'financials', 'results', 'balance_sheet', 'cash_flow',
                 'ratios', 'news', 'watchlist'
        """
        if tab not in VALID_TABS:
            return f"Invalid tab. Choose from: {', '.join(VALID_TABS)}"
        ui_action["type"] = "navigate_tab"
        ui_action["tab"] = tab
        return f"Switched the UI to the '{tab}' tab."

    return [get_company_snapshot, get_financial_statement, compute_yoy_growth, navigate_to_tab], ui_action


# ---------------------------------------------------------------------------
# Shared agent orchestration
# ---------------------------------------------------------------------------

async def generate_title(first_message: str) -> str:
    """Generate a short chat title from the user's first message."""
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.5-flash-lite",
        google_api_key=get_settings().google_api_key,
        max_tokens=20,
    )
    response = await llm.ainvoke([
        SystemMessage(content=(
            "Generate a concise 3-6 word title for a chat session based on the user's message. "
            "Return only the title, no quotes, no punctuation at the end."
        )),
        HumanMessage(content=first_message),
    ])
    return _extract_text(response.content).strip()


def _build_agent(symbol: str | None):
    """Builds a fresh agent for one chat turn. Returns (agent, ui_action) —
    ui_action is a dict the navigate_to_tab tool writes into (empty for general chats)."""
    if symbol:
        tools, ui_action = _build_stock_tools(symbol)
        system_prompt = STOCK_SYSTEM_PROMPT_TEMPLATE.format(symbol=symbol.upper())
    else:
        tools, ui_action = TOOLS, {}
        system_prompt = SYSTEM_PROMPT

    llm = ChatGoogleGenerativeAI(
        model="gemini-3.5-flash-lite",
        google_api_key=get_settings().google_api_key,
        max_tokens=4096,
    )
    return create_agent(llm, tools, system_prompt=system_prompt), ui_action


def _build_history(history: list[dict] | None) -> list:
    if not history:
        return []
    messages = []
    for turn in history:
        role = turn.get("role")
        content = turn.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    return messages


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part["text"] for part in content if isinstance(part, dict) and part.get("type") == "text"
        )
    return str(content)


async def chat(message: str, history: list[dict] | None = None, symbol: str | None = None) -> dict:
    """Run a single chat turn. Returns {'reply': str, 'action': dict | None}.

    When `symbol` is set, the chat is scoped to that stock: answers are grounded
    only in data already cached in the database, and the agent may trigger a
    frontend tab-navigation action.
    """
    if symbol and not await symbol_has_data(symbol):
        return {
            "reply": (
                f"I don't have any cached data for {symbol.upper()} yet. "
                "Please open this stock's page first so its data loads, then ask again."
            ),
            "action": None,
        }

    agent, ui_action = _build_agent(symbol)
    messages = _build_history(history) + [HumanMessage(content=message)]
    result = await agent.ainvoke({"messages": messages})
    last = result["messages"][-1]
    reply = _extract_text(last.content) if hasattr(last, "content") else str(last)
    return {"reply": reply, "action": ui_action or None}


async def stream_chat(
    message: str,
    history: list[dict] | None = None,
    symbol: str | None = None,
    action_box: dict | None = None,
) -> AsyncIterator[str]:
    """Stream the agent's response token by token. If `action_box` is passed, it is
    updated in place with any triggered UI action once the stream completes —
    read it after the async generator is exhausted."""
    if symbol and not await symbol_has_data(symbol):
        message_text = (
            f"I don't have any cached data for {symbol.upper()} yet. "
            "Please open this stock's page first so its data loads, then ask again."
        )
        yield message_text
        return

    agent, ui_action = _build_agent(symbol)
    messages = _build_history(history) + [HumanMessage(content=message)]
    async for msg_chunk, metadata in agent.astream(
        {"messages": messages},
        stream_mode="messages",
    ):
        # Only forward the LLM's own generated tokens — ToolMessage chunks carry raw
        # tool output (e.g. JSON) and must not be streamed to the client.
        if not isinstance(msg_chunk, AIMessageChunk):
            continue
        text = _extract_text(msg_chunk.content)
        if text:
            yield text

    if action_box is not None:
        action_box.update(ui_action)
