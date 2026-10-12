"""
MCP SERVER 2 - Alpaca PAPER trading (our own local server, not Alpaca's MCP).
Transport: stdio (started automatically by the MCP client).

Read-only tools (given to the agents):
  get_account_info, get_positions, get_open_orders, get_market_clock, get_portfolio_history
Order tools (called only by the executor after the risk checks and,
if enabled, human approval):
  buy_dollars, buy_stock, sell_stock, close_position, cancel_orders

Keys come from ALPACA_API_KEY / ALPACA_SECRET_KEY. The base URL is the paper
endpoint, so no real money can ever be touched.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from trading import alpaca_rest as ar  # noqa: E402

mcp = FastMCP("AlpacaPaperTrading")


@mcp.tool()
def get_account_info() -> str:
    """Paper account equity, cash, buying power and yesterday's equity."""
    a = ar.get_account()
    if a.get("last_equity"):
        a["day_change_pct"] = round(100 * (a["equity"] / a["last_equity"] - 1), 2)
    return json.dumps(a)


@mcp.tool()
def get_positions(include_rows: bool = False):
    """All open long positions: qty, average entry, market value, unrealized P/L %."""
    pos = ar.get_positions()
    lines = [f"{s}: {p['qty']:g} sh, avg ${p['avg_entry']:.2f}, value ${p['market_value']:,.0f}, "
             f"P/L {p['pl_pct']:+.1f}%" for s, p in sorted(pos.items(), key=lambda x: -x[1]["market_value"])]
    if include_rows:
        return {"count": len(pos), "positions": pos}
    return f"{len(pos)} open positions\n" + ("\n".join(lines) or "(none)")


@mcp.tool()
def get_open_orders() -> dict:
    """Open (unfilled) orders."""
    o = ar.list_open_orders()
    return {"count": len(o), "orders": o}


@mcp.tool()
def get_market_clock() -> dict:
    """Is the US market open now, and the next open/close times (ET)."""
    return ar.get_clock()


@mcp.tool()
def get_portfolio_history(period: str = "1M") -> dict:
    """Daily equity curve of the paper account. period: 1W, 1M, 3M."""
    return ar.get_portfolio_history(period, "1D")


@mcp.tool()
def buy_dollars(symbol: str, dollars: float) -> dict:
    """Market BUY for a dollar amount (fractional shares where allowed).
    Cancels open orders on the symbol first to avoid wash-trade rejections."""
    ar.cancel_orders_for(symbol)
    return ar.submit_market_order(symbol, "buy", notional=float(dollars))


@mcp.tool()
def buy_stock(symbol: str, qty: float) -> dict:
    """Market BUY for a number of shares."""
    ar.cancel_orders_for(symbol)
    return ar.submit_market_order(symbol, "buy", qty=float(qty))


@mcp.tool()
def sell_stock(symbol: str, qty: float) -> dict:
    """Market SELL for a number of shares (never more than held)."""
    held = ar.get_positions().get(symbol.upper(), {}).get("qty", 0)
    q = min(float(qty), held)
    if q <= 0:
        return {"symbol": symbol.upper(), "status": "skipped", "note": "no shares held"}
    ar.cancel_orders_for(symbol)
    return ar.submit_market_order(symbol, "sell", qty=round(q, 6))


@mcp.tool()
def close_position(symbol: str) -> dict:
    """Sell the entire position in one symbol."""
    ar.cancel_orders_for(symbol)
    return ar.close_position(symbol)


@mcp.tool()
def cancel_orders(symbol: str = "") -> dict:
    """Cancel open orders for one symbol, or all open orders if symbol is empty."""
    n = ar.cancel_orders_for(symbol or None)
    return {"cancelled": "all" if n == -1 else n, "symbol": symbol.upper() or "ALL"}


if __name__ == "__main__":
    mcp.run(transport="stdio")
