"""Codex's scoped market/news tools. No account credentials or database access."""

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from peat.market_tools import MarketTools

server = FastMCP(
    "peat_research",
    instructions="Read-only public market and news research. Use fresh quotes near the final answer, especially for ultra-short horizons. Match news to its actual event/publication time using get_price_history. Never place private account values, credentials or personal details in a news query. These tools cannot trade or read local files.",
)
readonly = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)


async def call(name, arguments):
    async with httpx.AsyncClient(timeout=25, trust_env=False, follow_redirects=False) as client:
        return await MarketTools(client).call(name, arguments)


@server.tool(annotations=readonly)
async def get_quote(symbol: str) -> dict:
    """Fetch a fresh quote with source timestamp, currency and pre/regular/post session."""
    return await call("get_quote", {"symbol": symbol})


@server.tool(annotations=readonly)
async def get_price_history(
    symbol: str,
    interval: str = "5m",
    period: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 160,
    extended: bool = True,
) -> dict:
    """Fetch OHLCV, optionally around an event using ISO start/end WITH UTC offsets. Use 1m/5m/15m + 5d, 1h + 1mo, or 1d + 1y. Returned coverage/truncation are explicit."""
    return await call("get_price_history", locals())


@server.tool(annotations=readonly)
async def search_news(query: str, days: int = 3) -> dict:
    """Search public company/industry news. Use public names, events and dates only."""
    return await call("search_news", {"query": query, "days": days})


@server.tool(annotations=readonly)
async def read_news_article(url: str) -> dict:
    """Read a public article; check original publication and event time before attributing price moves."""
    return await call("read_news_article", {"url": url})


if __name__ == "__main__":
    server.run(transport="stdio")
