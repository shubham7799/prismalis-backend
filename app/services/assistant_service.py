import json
from typing import AsyncIterator

from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool

from app.core.config import get_settings
from app.mcp.services import fmp, stock_service
from app.services.fmp_service import FMPRateLimitError, FMPServiceError

SYSTEM_PROMPT = (
    "You are a financial research assistant for Prismalis, a stock analysis platform. "
    "You have access to real-time stock data tools. Use them to answer user questions about "
    "stocks, companies, financials, and market data. Be concise, accurate, and cite the data "
    "you retrieve. When discussing financials, highlight key metrics like revenue growth, "
    "margins, and valuation."
)


RATE_LIMIT_MESSAGE = (
    "The stock data provider is currently rate-limited. Do not retry this tool again in this turn — "
    "tell the user the data is temporarily unavailable and to try again in a minute."
)


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


TOOLS = [stock_quote, company_profile, company_financials, price_history, screen_stocks]


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


def _make_agent():
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.5-flash-lite",
        google_api_key=get_settings().google_api_key,
        max_tokens=4096,
    )
    return create_agent(llm, TOOLS, system_prompt=SYSTEM_PROMPT)


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


async def chat(message: str, history: list[dict] | None = None) -> str:
    """Run a single chat turn and return the final text response."""
    agent = _make_agent()
    messages = _build_history(history) + [HumanMessage(content=message)]
    result = await agent.ainvoke({"messages": messages})
    last = result["messages"][-1]
    return _extract_text(last.content) if hasattr(last, "content") else str(last)


async def stream_chat(message: str, history: list[dict] | None = None) -> AsyncIterator[str]:
    """Stream the final output of the agent response token by token."""
    agent = _make_agent()
    messages = _build_history(history) + [HumanMessage(content=message)]
    async for chunk in agent.astream({"messages": messages}):
        if "agent" in chunk:
            for msg in chunk["agent"].get("messages", []):
                if hasattr(msg, "content"):
                    text = _extract_text(msg.content)
                    if text:
                        yield text
