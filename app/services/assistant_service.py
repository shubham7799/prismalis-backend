import json
from typing import AsyncIterator

from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool

from app.core.config import get_settings
from app.mcp.services import fmp, stock_service
from app.services.fmp_service import FMPServiceError

SYSTEM_PROMPT = (
    "You are a financial research assistant for Prismalis, a stock analysis platform. "
    "You have access to real-time stock data tools. Use them to answer user questions about "
    "stocks, companies, financials, and market data. Be concise, accurate, and cite the data "
    "you retrieve. When discussing financials, highlight key metrics like revenue growth, "
    "margins, and valuation."
)


@tool
async def stock_quote(symbol: str) -> str:
    """Get the live price quote for a US stock ticker (price, change, volume, market cap, moving averages)."""
    try:
        data = await stock_service().get_quote_only(symbol.upper())
        return json.dumps(data, default=str, indent=2)
    except FMPServiceError as e:
        return f"Error fetching quote: {e}"


@tool
async def company_profile(symbol: str) -> str:
    """Get the company profile for a US stock ticker (name, sector, industry, description, CEO, exchange)."""
    try:
        data = await stock_service().get_profile_with_quote(symbol.upper())
        return json.dumps(data, default=str, indent=2)
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
    except FMPServiceError as e:
        return f"Error fetching price history: {e}"


TOOLS = [stock_quote, company_profile, company_financials, price_history]


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
