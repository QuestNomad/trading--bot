#!/usr/bin/env python3
"""
Paper Trading Module for Score Trader Strategy.

Simulates trades without real money using the same signal logic as
arena_backtest.py.  Tracks a virtual portfolio, logs all buy/sell signals,
records P&L, and persists state to paper_portfolio.json across runs.

Trading 212 fee model:
  TRADING_FEE  = 0.0015  (0.15% FX fee)
  SPREAD_COST  = 0.0005  (0.05% spread)
  SLIPPAGE_COST = 0.001  (0.10% slippage)

Signal scoring (arena_backtest aligned):
  BB(20) below lower band â +3, above upper â -2
  RSI(14) < 30 â +3, > 70 â -2, â¤ 50 â +1
  SMA(20) above â +3, below â -2
  Buy threshold: 5  (max score = +9)

Exit: trailing stop at 3ÃATR(14), no fixed TP/SL.
Sizing: Kelly fraction 0.0694 of portfolio per trade.
Risk: max 80 % exposure, max 4 positions per sector.

Can be run daily via GitHub Actions.
"""

import os
import sys
import json
import time
import math
import logging
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np
import yfinance as yf
import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Import alerts module (same directory)
try:
    from alerts import (
        send_trade_alert,
        send_daily_summary,
        send_drawdown_alert,
        send_custom_alert,
    )
    ALERTS_AVAILABLE = True
except ImportError:
    ALERTS_AVAILABLE = False
    print("Warning: alerts.py not found â Telegram alerts disabled.")

# ââ Configuration ââââââââââââââââââââââââââââââââââââââââââââ
STARTING_CAPITAL = 10_000.0

# Kelly sizing
KELLY_FRACTION = 0.0694

MAX_OPEN_POSITIONS = 10
PORTFOLIO_FILE = "paper_portfolio.json"

# Trading 212 fee model
TRADING_FEE = 0.0015
SPREAD_COST = 0.0005
SLIPPAGE_COST = 0.001
TOTAL_COST = TRADING_FEE + SPREAD_COST + SLIPPAGE_COST  # 0.30%

# Score Trader thresholds (arena_backtest aligned)
BUY_THRESHOLD = 5
VIX_LIMIT = 30

# Risk management
MAX_EXPOSURE = 0.80
MAX_POSITIONS_PER_SECTOR = 4

# Drawdown alert threshold
DRAWDOWN_ALERT_PCT = 5.0

DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [paper] %(message)s")
log = logging.getLogger(__name__)

analyzer = SentimentIntensityAnalyzer()
_yf_lock = threading.Lock()

# ââ Sector mapping âââââââââââââââââââââââââââââââââââââââââââ
SECTORS = {
    "Technology": ["AAPL", "MSFT", "NVDA", "GOOG", "AMZN"],
    "Finance": ["JPM", "V", "BRK-B"],
    "Healthcare": ["JNJ", "UNH", "PFE"],
    "Energy": ["XOM", "CVX"],
    "Consumer": ["WMT", "PG", "KO", "MCD", "NKE", "DIS"],
    "Industrial": ["CAT", "BA", "HON"],
    "Semiconductor": ["TSM", "ASML"],
    "ETF/Index": ["SPY", "QQQ", "IWM", "EFA", "GLD", "TLT"],
    "Crypto": ["BTC-USD", "ETH-USD"],
    "Short/Inverse": ["SH", "PSQ", "DOG"],
    "Commodity": ["USO", "SLV"],
}

# Build reverse mapping: symbol â sector
ASSET_TO_SECTOR: dict[str, str] = {}
for _sector, _symbols in SECTORS.items():
    for _sym in _symbols:
        ASSET_TO_SECTOR[_sym] = _sector

# ââ Assets (same as bot.py) ââââââââââââââââââââââââââââââââââ
ASSETS = [
    {"name": "Bitcoin",        "typ": "crypto", "id": "bitcoin",    "symbol": "BTC"},
    {"name": "Ethereum",       "typ": "crypto", "id": "ethereum",   "symbol": "ETH"},
    {"name": "S&P 500",        "typ": "aktie",  "id": "SPY",        "symbol": "SPY"},
    {"name": "Apple",          "typ": "aktie",  "id": "AAPL",       "symbol": "AAPL"},
    {"name": "Nvidia",         "typ": "aktie",  "id": "NVDA",       "symbol": "NVDA"},
    {"name": "Tesla",          "typ": "aktie",  "id": "TSLA",       "symbol": "TSLA"},
    {"name": "Microsoft",      "typ": "aktie",  "id": "MSFT",       "symbol": "MSFT"},
    {"name": "Amazon",         "typ": "aktie",  "id": "AMZN",       "symbol": "AMZN"},
    {"name": "Meta",           "typ": "aktie",  "id": "META",       "symbol": "META"},
    {"name": "Google",         "typ": "aktie",  "id": "GOOGL",      "symbol": "GOOGL"},
    {"name": "DAX ETF",        "typ": "aktie",  "id": "EXS1.DE",    "symbol": "DAX"},
    {"name": "SAP",            "typ": "aktie",  "id": "SAP.DE",     "symbol": "SAP"},
    {"name": "Rheinmetall",    "typ": "aktie",  "id": "RHM.DE",     "symbol": "RHM"},
    {"name": "Airbus",         "typ": "aktie",  "id": "AIR.DE",     "symbol": "AIR"},
    {"name": "Zalando",        "typ": "aktie",  "id": "ZAL.DE",     "symbol": "ZAL"},
    {"name": "Delivery Hero",  "typ": "aktie",  "id": "DHER.DE",    "symbol": "DHER"},
    {"name": "Deutsche Bank",  "typ": "aktie",  "id": "DBK.DE",     "symbol": "DBK"},
    {"name": "BNP Paribas",    "typ": "aktie",  "id": "BNP.PA",     "symbol": "BNP"},
    {"name": "UBS",            "typ": "aktie",  "id": "UBSG.SW",    "symbol": "UBS"},
    {"name": "Nikkei ETF",     "typ": "aktie",  "id": "EWJ",        "symbol": "EWJ"},
    {"name": "Toyota",         "typ": "aktie",  "id": "7203.T",     "symbol": "Toyota"},
    {"name": "Sony",           "typ": "aktie",  "id": "6758.T",     "symbol": "Sony"},
    {"name": "China ETF",      "typ": "aktie",  "id": "FXI",        "symbol": "FXI"},
    {"name": "Alibaba HK",     "typ": "aktie",  "id": "9988.HK",    "symbol": "Alibaba"},
    {"name": "Tencent",        "typ": "aktie",  "id": "0700.HK",    "symbol": "Tencent"},
    {"name": "Indien ETF",     "typ": "aktie",  "id": "INDA",       "symbol": "INDA"},
    {"name": "Brasilien ETF",  "typ": "aktie",  "id": "EWZ",        "symbol": "EWZ"},
    {"name": "EM ETF",         "typ": "aktie",  "id": "VWO",        "symbol": "VWO"},
    {"name": "Russell 2000",   "typ": "aktie",  "id": "IWM",        "symbol": "IWM"},
    {"name": "Gold",           "typ": "aktie",  "id": "GC=F",       "symbol": "Gold"},
    {"name": "Silber",         "typ": "aktie",  "id": "SI=F",       "symbol": "Silber"},
    {"name": "Oil",            "typ": "aktie",  "id": "BZ=F",       "symbol": "Oil"},
    {"name": "Kupfer",         "typ": "aktie",  "id": "HG=F",       "symbol": "Kupfer"},
    {"name": "Weizen",         "typ": "aktie",  "id": "ZW=F",       "symbol": "Weizen"},
    {"name": "Short S&P 500",  "typ": "aktie",  "id": "XSPS.L",    "symbol": "XSPS", "short": True},
    {"name": "Short DAX",      "typ": "aktie",  "id": "DXSN.DE",   "symbol": "DXSN", "short": True},
    {"name": "Short Nasdaq",   "typ": "aktie",  "id": "QQQS.L",    "symbol": "QQQS", "short": True},
    {"name": "Short Krypto",   "typ": "aktie",  "id": "BITI",       "symbol": "BITI", "short": True},
]

NEWS_FEEDS = {
    "welt": [
        "https://feeds.reuters.com/reuters/businessNews",
        "http://feeds.bbci.co.uk/news/business/rss.xml",
    ],
    "europa": [
        "https://www.derstandard.at/rss/wirtschaft",
        "https://euronews.com/rss?format=mrss&level=theme&name=business",
    ],
}


# ââ Data Loading âââââââââââââââââââââââââââââââââââââââââââââ

def get_crypto_prices(coin_id: str):
    """Fetch ~300 days of daily crypto prices from CoinGecko."""
    try:
        import requests

        r = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
            params={"vs_currency": "eur", "days": "300", "interval": "daily"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if "prices" not in data:
            return None
        return [p[1] for p in data["prices"]]
    except Exception as exc:
        log.warning(f"CoinGecko error for {coin_id}: {exc}")
        return None


def get_stock_prices(ticker: str):
    """Fetch ~300 days of daily stock prices via yfinance."""
    try:
        with _yf_lock:
            df = yf.download(
                ticker, period="300d", interval="1d",
                progress=False, auto_adjust=True,
            )
        if df.empty or len(df) < 50:
            return None
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = close.dropna()
        if len(close) < 50:
            return None
        prices = [float(x) for x in close.values
                  if math.isfinite(float(x)) and float(x) > 0]
        if len(prices) < 50:
            return None
        return prices
    except Exception as exc:
        log.warning(f"yfinance error for {ticker}: {exc}")
        return None


def get_prices(asset: dict):
    """Unified price loader for any asset."""
    if asset["typ"] == "crypto":
        return get_crypto_prices(asset["id"])
    return get_stock_prices(asset["id"])


def get_current_price(asset: dict) -> float | None:
    """Get the latest price for an asset."""
    prices = get_prices(asset)
    if prices and len(prices) > 0:
        return float(prices[-1])
    return None


# ââ Technical Indicators âââââââââââââââââââââââââââââââââââââ

def sma(prices, n):
    return pd.Series(prices).rolling(n).mean()


def rsi_val(prices, n=14):
    s = pd.Series(prices)
    d = s.diff()
    g = d.where(d > 0, 0).rolling(n).mean()
    l = -d.where(d < 0, 0).rolling(n).mean()
    avg_loss = float(l.iloc[-1])
    if avg_loss == 0:
        return 100.0
    return float((100 - (100 / (1 + (g / l)))).iloc[-1])


def atr_val(prices, n=14):
    s = pd.Series(prices)
    tr = s.diff().abs()
    tr.iloc[0] = 0
    return float(tr.rolling(n).mean().iloc[-1])


def bollinger_bands(prices, n=20, k=2):
    """Return (middle, upper, lower) Bollinger Bands."""
    s = pd.Series(prices)
    middle = s.rolling(n).mean()
    std = s.rolling(n).std()
    upper = middle + k * std
    lower = middle - k * std
    return float(middle.iloc[-1]), float(upper.iloc[-1]), float(lower.iloc[-1])


# ââ Score Trader Signal (arena_backtest aligned) âââââââââââââ

def compute_signal(prices, sw=0.0, seu=0.0):
    """
    Compute Score Trader signal aligned with arena_backtest.py.

    Scoring:
      BB(20) below lower band â +3, above upper â -2
      RSI(14) < 30 â +3, > 70 â -2, â¤ 50 â +1
      SMA(20) above â +3, below â -2
      Buy threshold: 5  (max possible = +9)

    Sentiment infrastructure is kept but NOT included in the score.

    Returns (signal, score, details).
    """
    if len(prices) < 50:
        return "WAIT", 0, {}

    current = float(prices[-1])

    # Indicators
    r = rsi_val(prices)
    a = atr_val(prices)
    sma20 = float(sma(prices, 20).iloc[-1])
    bb_mid, bb_upper, bb_lower = bollinger_bands(prices, 20, 2)

    # Sentiment (computed but not scored)
    sentiment = (sw * 0.3) + (seu * 0.2)

    score = 0

    # Bollinger Band score
    if current < bb_lower:
        score += 3
    elif current > bb_upper:
        score -= 2

    # RSI score
    if r < 30:
        score += 3
    elif r > 70:
        score -= 2
    elif r <= 50:
        score += 1

    # SMA(20) score
    if current > sma20:
        score += 3
    else:
        score -= 2

    # Trailing stop initial level
    trailing_stop_long = current - (a * 3)
    trailing_stop_short = current + (a * 3)

    details = {
        "sma20": sma20,
        "rsi": r,
        "atr": a,
        "bb_mid": bb_mid,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "trailing_stop": trailing_stop_long,
        "score": score,
        "sentiment": sentiment,
    }

    if score >= BUY_THRESHOLD:
        return "BUY", score, details

    # Sell when score is very negative (all three bearish = -6)
    if score <= -2:
        return "SELL", score, details

    return "HOLD", score, details


# ââ Trailing Stop Management âââââââââââââââââââââââââââââââââ

def aktualisiere_trailing_stops(portfolio: dict, price_cache: dict):
    """
    Update trailing stops for every open position.

    Long:  new_stop = price - 3ÃATR;  trailing = max(old, new)
    Short: new_stop = price + 3ÃATR;  trailing = min(old, new)

    Requires price_cache to contain current prices AND
    a second pass to compute ATR from full price history.
    We store ATR in position on entry so we can also use
    the live ATR from the latest price series when available.
    """
    for asset_id, pos in portfolio["positions"].items():
        price = price_cache.get(asset_id)
        if price is None:
            continue

        atr = pos.get("atr", 0)
        if atr <= 0:
            continue

        old_stop = pos.get("trailing_stop", 0)
        is_short = pos.get("is_short", False)

        if is_short:
            new_stop = price + (3 * atr)
            # For shorts, a lower stop is tighter (better), so use min
            pos["trailing_stop"] = min(old_stop, new_stop) if old_stop > 0 else new_stop
        else:
            new_stop = price - (3 * atr)
            # For longs, a higher stop is tighter (better), so use max
            pos["trailing_stop"] = max(old_stop, new_stop)


# ââ Sentiment (same as bot.py) âââââââââââââââââââââââââââââââ

_sentiment_cache = {}


def get_sentiment(category="welt"):
    if category in _sentiment_cache:
        return _sentiment_cache[category]
    scores = []
    for url in NEWS_FEEDS.get(category, []):
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                text = entry.get("title", "") + " " + entry.get("summary", "")
                scores.append(analyzer.polarity_scores(text)["compound"])
        except Exception:
            pass
    result = round(sum(scores) / len(scores), 3) if scores else 0.0
    _sentiment_cache[category] = result
    return result


# ââ Risk Checks ââââââââââââââââââââââââââââââââââââââââââââââ

def check_exposure(portfolio: dict, price_cache: dict, trade_value: float) -> bool:
    """Return True if adding *trade_value* keeps total exposure â¤ MAX_EXPOSURE."""
    portfolio_value = calculate_portfolio_value(portfolio, price_cache)
    if portfolio_value <= 0:
        return False
    current_exposure = calculate_positions_value(portfolio, price_cache) / portfolio_value
    added_exposure = trade_value / portfolio_value
    return (current_exposure + added_exposure) <= MAX_EXPOSURE


def count_sector_positions(portfolio: dict, symbol: str) -> int:
    """Count how many open positions share the same sector as *symbol*."""
    sector = ASSET_TO_SECTOR.get(symbol, "Other")
    count = 0
    for _aid, pos in portfolio["positions"].items():
        pos_symbol = pos.get("symbol", "")
        if ASSET_TO_SECTOR.get(pos_symbol, "Other") == sector:
            count += 1
    return count


# ââ Portfolio State Management âââââââââââââââââââââââââââââââ

def default_portfolio() -> dict:
    """Return a fresh portfolio state."""
    return {
        "capital": STARTING_CAPITAL,
        "cash": STARTING_CAPITAL,
        "positions": {},       # asset_id -> position dict
        "trade_history": [],   # list of completed trades
        "daily_snapshots": [], # list of daily snapshot dicts
        "peak_value": STARTING_CAPITAL,
        "total_fees_paid": 0.0,
        "created_at": datetime.now().isoformat(),
        "last_run": None,
    }


def load_portfolio() -> dict:
    """Load portfolio from JSON file, or create a new one."""
    path = Path(PORTFOLIO_FILE)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                portfolio = json.load(f)
            log.info(f"Portfolio loaded from {PORTFOLIO_FILE}")
            return portfolio
        except (json.JSONDecodeError, KeyError) as exc:
            log.warning(f"Corrupt portfolio file, starting fresh: {exc}")
    return default_portfolio()


def save_portfolio(portfolio: dict):
    """Persist portfolio state to JSON."""
    portfolio["last_run"] = datetime.now().isoformat()
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, indent=2, ensure_ascii=False)
    log.info(f"Portfolio saved to {PORTFOLIO_FILE}")


# ââ Portfolio Calculations âââââââââââââââââââââââââââââââââââ

def calculate_positions_value(portfolio: dict, price_cache: dict) -> float:
    """Calculate total value of all open positions using cached prices."""
    total = 0.0
    for asset_id, pos in portfolio["positions"].items():
        price = price_cache.get(asset_id)
        if price is not None:
            total += price * pos["quantity"]
        else:
            total += pos["entry_price"] * pos["quantity"]
    return total


def calculate_portfolio_value(portfolio: dict, price_cache: dict) -> float:
    """Total portfolio value = cash + positions value."""
    return portfolio["cash"] + calculate_positions_value(portfolio, price_cache)


def apply_fee(amount: float) -> tuple[float, float]:
    """Apply trading fees. Returns (net_amount, fee_paid)."""
    fee = amount * TOTAL_COST
    return amount - fee, fee


# ââ Trade Execution (Paper) ââââââââââââââââââââââââââââââââââ

def execute_buy(portfolio: dict, asset: dict, price: float,
                details: dict, price_cache: dict) -> bool:
    """Execute a paper BUY order with Kelly sizing and risk checks."""
    asset_id = asset["id"]
    symbol = asset.get("symbol", asset_id)

    # FIX: Schutz vor NaN/ungueltigen Preisen
    if not math.isfinite(price) or price <= 0:
        log.warning(f"  Skip BUY {asset['name']}: invalid price={price}")
        return False

    # Skip if already holding
    if asset_id in portfolio["positions"]:
        log.info(f"  Already holding {asset['name']} â skip BUY.")
        return False

    # Skip if max positions reached
    if len(portfolio["positions"]) >= MAX_OPEN_POSITIONS:
        log.info(f"  Max positions ({MAX_OPEN_POSITIONS}) reached â skip BUY {asset['name']}.")
        return False

    # Sector limit check
    if count_sector_positions(portfolio, symbol) >= MAX_POSITIONS_PER_SECTOR:
        sector = ASSET_TO_SECTOR.get(symbol, "Other")
        log.info(f"  Sector '{sector}' already has {MAX_POSITIONS_PER_SECTOR} positions â skip BUY {asset['name']}.")
        return False

    # Kelly position sizing
    portfolio_value = calculate_portfolio_value(portfolio, price_cache)
    trade_value = (portfolio_value * KELLY_FRACTION)
    quantity = trade_value / price

    if trade_value < 10:  # minimum trade value
        log.info(f"  Trade value too small for {asset['name']} â skip.")
        return False

    # Exposure check
    if not check_exposure(portfolio, price_cache, trade_value):
        log.info(
            f"  Adding {asset['name']} would exceed {MAX_EXPOSURE*100:.0f}% "
            f"max exposure â skip BUY."
        )
        return False

    # Apply fees
    net_cost, fee = apply_fee(trade_value)
    total_cost = trade_value + fee

    if total_cost > portfolio["cash"]:
        log.info(
            f"  Insufficient cash for {asset['name']} "
            f"(need ${total_cost:.2f}, have ${portfolio['cash']:.2f})."
        )
        return False

    # Trailing stop initial value
    atr = details.get("atr", 0)
    is_short = asset.get("short", False)
    if is_short:
        trailing_stop = price + (3 * atr) if atr > 0 else price * 1.05
    else:
        trailing_stop = price - (3 * atr) if atr > 0 else price * 0.95

    # Execute
    portfolio["cash"] -= total_cost
    portfolio["total_fees_paid"] += fee
    portfolio["positions"][asset_id] = {
        "name": asset["name"],
        "symbol": symbol,
        "entry_price": price,
        "quantity": quantity,
        "trailing_stop": trailing_stop,
        "atr": atr,
        "entry_date": datetime.now().isoformat(),
        "signal": "BUY",
        "score": details["score"],
        "is_short": is_short,
    }

    log.info(
        f"  BUY {asset['name']}: {quantity:.4f} @ ${price:,.2f} "
        f"(cost ${total_cost:,.2f}, fee ${fee:.2f}, "
        f"trailing_stop ${trailing_stop:,.2f})"
    )
    return True


def execute_sell(portfolio: dict, asset_id: str, price: float,
                 reason: str) -> dict | None:
    """Execute a paper SELL (close position). Returns trade record or None."""
    if asset_id not in portfolio["positions"]:
        return None

    # FIX: NaN-Preis wuerde cash & total_fees_paid zerstoeren
    if not math.isfinite(price) or price <= 0:
        log.warning(f"  Skip SELL {asset_id}: invalid price={price}")
        return None

    pos = portfolio["positions"][asset_id]
    trade_value = pos["quantity"] * price
    net_proceeds, fee = apply_fee(trade_value)

    portfolio["cash"] += net_proceeds
    portfolio["total_fees_paid"] += fee

    # Calculate P&L
    entry_cost = pos["quantity"] * pos["entry_price"]
    pnl = net_proceeds - entry_cost
    pnl_pct = (pnl / entry_cost) * 100 if entry_cost > 0 else 0.0

    trade_record = {
        "asset": pos["name"],
        "asset_id": asset_id,
        "signal": pos["signal"],
        "entry_price": pos["entry_price"],
        "exit_price": price,
        "quantity": pos["quantity"],
        "entry_date": pos["entry_date"],
        "exit_date": datetime.now().isoformat(),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "fee_paid": round(fee, 2),
        "reason": reason,
    }
    portfolio["trade_history"].append(trade_record)
    del portfolio["positions"][asset_id]

    log.info(
        f"  SELL {pos['name']}: {pos['quantity']:.4f} @ ${price:,.2f} "
        f"| P&L: ${pnl:+,.2f} ({pnl_pct:+.2f}%) | Reason: {reason}"
    )
    return trade_record


# ââ Journal CSV ââââââââââââââââââââââââââââââââââââââââââââââ

def append_journal_csv(trade_record: dict):
    """Append a closed trade to the journal CSV file."""
    csv_path = Path("paper_journal.csv")
    header_needed = not csv_path.exists()
    try:
        with open(csv_path, "a", encoding="utf-8") as f:
            if header_needed:
                f.write(
                    "asset,asset_id,signal,entry_price,exit_price,quantity,"
                    "entry_date,exit_date,pnl,pnl_pct,fee_paid,reason\n"
                )
            f.write(
                f"{trade_record['asset']},{trade_record['asset_id']},"
                f"{trade_record['signal']},{trade_record['entry_price']:.4f},"
                f"{trade_record['exit_price']:.4f},{trade_record['quantity']:.6f},"
                f"{trade_record['entry_date']},{trade_record['exit_date']},"
                f"{trade_record['pnl']:.2f},{trade_record['pnl_pct']:.2f},"
                f"{trade_record['fee_paid']:.2f},{trade_record['reason']}\n"
            )
    except Exception as exc:
        log.warning(f"Journal CSV write error: {exc}")


# ââ Health Check âââââââââââââââââââââââââââââââââââââââââââââ

def health_check(portfolio: dict, price_cache: dict) -> dict:
    """Return a quick health-check dict for monitoring."""
    pv = calculate_portfolio_value(portfolio, price_cache)
    peak = portfolio.get("peak_value", STARTING_CAPITAL)
    dd = ((peak - pv) / peak) * 100 if peak > 0 else 0.0
    total_trades = len(portfolio.get("trade_history", []))
    wins = sum(1 for t in portfolio.get("trade_history", []) if t["pnl"] > 0)
    return {
        "portfolio_value": round(pv, 2),
        "cash": round(portfolio["cash"], 2),
        "open_positions": len(portfolio["positions"]),
        "total_trades": total_trades,
        "win_rate_pct": round((wins / total_trades) * 100, 1) if total_trades else 0.0,
        "drawdown_pct": round(dd, 2),
        "peak_value": round(peak, 2),
        "fees_paid": round(portfolio["total_fees_paid"], 2),
        "last_run": portfolio.get("last_run"),
    }


# ââ Charts (equity curve PNG) ââââââââââââââââââââââââââââââââ

def save_equity_chart(portfolio: dict):
    """Save a simple equity-curve PNG from daily snapshots."""
    snapshots = portfolio.get("daily_snapshots", [])
    if len(snapshots) < 2:
        return
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        dates = [s["date"] for s in snapshots]
        values = [s["portfolio_value"] for s in snapshots]

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(dates, values, linewidth=1.5, color="#2563eb")
        ax.axhline(STARTING_CAPITAL, linestyle="--", color="gray", linewidth=0.8)
        ax.set_title("Paper Trading â Equity Curve")
        ax.set_ylabel("Portfolio Value ($)")
        ax.tick_params(axis="x", rotation=45)
        # Show only every Nth label to avoid clutter
        n = max(1, len(dates) // 20)
        ax.set_xticks(range(0, len(dates), n))
        ax.set_xticklabels([dates[i] for i in range(0, len(dates), n)])
        fig.tight_layout()
        fig.savefig("paper_equity.png", dpi=120)
        plt.close(fig)
        log.info("Equity chart saved to paper_equity.png")
    except Exception as exc:
        log.warning(f"Chart generation error: {exc}")


# ââ Main Paper Trading Logic ââââââââââââââââââââââââââââââââ

def run_paper_trading():
    """Main paper trading loop â meant to be run once daily."""
    start_time = time.time()
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    log.info(f"=== Paper Trading Started â {today} ===")

    # Load portfolio
    portfolio = load_portfolio()
    log.info(
        f"Portfolio: cash=${portfolio['cash']:,.2f}, "
        f"{len(portfolio['positions'])} positions, "
        f"fees paid=${portfolio['total_fees_paid']:.2f}"
    )

    # VIX check
    vix_value = None
    try:
        vix_df = yf.download(
            "^VIX", period="1d", interval="1d",
            progress=False, auto_adjust=True,
        )
        vix_close = vix_df["Close"]
        if isinstance(vix_close, pd.DataFrame):
            vix_close = vix_close.iloc[:, 0]
        vix_value = float(vix_close.iloc[-1])
        log.info(f"VIX: {vix_value:.1f}")
        if vix_value > VIX_LIMIT:
            msg = f"VIX at {vix_value:.1f} (>{VIX_LIMIT}) â no new trades today."
            log.warning(msg)
            if ALERTS_AVAILABLE:
                send_custom_alert(f"ð¨ <b>Paper Trading:</b> {msg}")
    except Exception as exc:
        log.warning(f"VIX fetch error: {exc}")

    # Sentiment
    sw = get_sentiment("welt")
    seu = get_sentiment("europa")
    log.info(f"Sentiment â World: {sw}, EU: {seu}")

    # Build price cache and fetch full series for ATR updates
    price_cache: dict[str, float] = {}
    price_series_cache: dict[str, list] = {}
    asset_lookup = {a["id"]: a for a in ASSETS}

    # Pre-fetch prices for existing positions (needed for trailing stop updates)
    for asset_id in list(portfolio["positions"].keys()):
        asset = asset_lookup.get(asset_id)
        if not asset:
            continue
        prices = get_prices(asset)
        if prices and len(prices) > 0:
            last_price = float(prices[-1])
            # FIX: nur gueltige Preise in den Cache
            if math.isfinite(last_price) and last_price > 0:
                price_cache[asset_id] = last_price
                price_series_cache[asset_id] = prices
                # Update ATR in position from latest data
                if len(prices) >= 14:
                    atr = atr_val(prices)
                    if math.isfinite(atr):
                        portfolio["positions"][asset_id]["atr"] = atr

    # Phase 1: Update trailing stops with latest prices
    aktualisiere_trailing_stops(portfolio, price_cache)

    # Phase 2: Check trailing-stop exits
    trades_today = []
    for asset_id in list(portfolio["positions"].keys()):
        pos = portfolio["positions"][asset_id]
        price = price_cache.get(asset_id)
        if price is None:
            continue

        is_short = pos.get("is_short", False)
        trailing_stop = pos.get("trailing_stop", 0)

        # Check trailing stop hit
        if is_short:
            if price >= trailing_stop and trailing_stop > 0:
                trade = execute_sell(portfolio, asset_id, price, "Trailing-Stop")
                if trade:
                    trades_today.append(trade)
                    append_journal_csv(trade)
        else:
            if price <= trailing_stop and trailing_stop > 0:
                trade = execute_sell(portfolio, asset_id, price, "Trailing-Stop")
                if trade:
                    trades_today.append(trade)
                    append_journal_csv(trade)

    # Phase 3: Scan for new signals (only if VIX allows)
    new_signals = []
    if vix_value is None or vix_value <= VIX_LIMIT:
        for asset in ASSETS:
            try:
                # Use cached series if available, otherwise fetch
                asset_id = asset["id"]
                if asset_id in price_series_cache:
                    prices = price_series_cache[asset_id]
                else:
                    prices = get_prices(asset)

                if prices is None or len(prices) < 50:
                    continue

                current_price = float(prices[-1])
                price_cache[asset_id] = current_price

                signal, score, details = compute_signal(prices, sw, seu)

                if signal == "WAIT":
                    continue

                # Invert signal for short ETFs
                if asset.get("short"):
                    if signal == "BUY":
                        signal = "SELL"
                    elif signal == "SELL":
                        signal = "BUY"
                    # Mirror trailing stop for shorts
                    a = details.get("atr", 0)
                    details["trailing_stop"] = current_price + (3 * a)

                if signal == "BUY":
                    success = execute_buy(
                        portfolio, asset, current_price, details, price_cache,
                    )
                    if success:
                        new_signals.append({
                            "asset": asset,
                            "signal": signal,
                            "price": current_price,
                            "score": score,
                            "details": details,
                        })

                        # Send trade alert
                        if ALERTS_AVAILABLE:
                            send_trade_alert(
                                asset_name=asset["name"],
                                signal="KAUFEN",
                                price=current_price,
                                score=score,
                                stop_loss=details.get("trailing_stop", 0),
                                take_profit=0,
                                rsi=details.get("rsi", 0),
                                atr=details.get("atr", 0),
                                position_size=0,
                                is_paper=True,
                            )

                elif signal == "SELL" and asset_id in portfolio["positions"]:
                    trade = execute_sell(
                        portfolio, asset_id, current_price, "Signal-SELL",
                    )
                    if trade:
                        trades_today.append(trade)
                        append_journal_csv(trade)

                        if ALERTS_AVAILABLE:
                            send_trade_alert(
                                asset_name=asset["name"],
                                signal="VERKAUFEN",
                                price=current_price,
                                score=score,
                                stop_loss=details.get("trailing_stop", 0),
                                take_profit=0,
                                rsi=details.get("rsi", 0),
                                atr=details.get("atr", 0),
                                is_paper=True,
                            )

            except Exception as exc:
                log.error(f"Error analyzing {asset['name']}: {exc}")

    # Phase 4: Calculate portfolio value and snapshots
    portfolio_value = calculate_portfolio_value(portfolio, price_cache)

    # Update peak and check drawdown
    if portfolio_value > portfolio.get("peak_value", STARTING_CAPITAL):
        portfolio["peak_value"] = portfolio_value

    peak = portfolio.get("peak_value", STARTING_CAPITAL)
    drawdown_pct = ((peak - portfolio_value) / peak) * 100 if peak > 0 else 0.0

    if drawdown_pct >= DRAWDOWN_ALERT_PCT and ALERTS_AVAILABLE:
        send_drawdown_alert(
            current_value=portfolio_value,
            peak_value=peak,
            drawdown_pct=drawdown_pct,
            is_paper=True,
        )

    # Daily snapshot
    snapshot = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "portfolio_value": round(portfolio_value, 2),
        "cash": round(portfolio["cash"], 2),
        "positions_value": round(portfolio_value - portfolio["cash"], 2),
        "num_positions": len(portfolio["positions"]),
        "peak_value": round(peak, 2),
        "drawdown_pct": round(drawdown_pct, 2),
        "trades_today": len(trades_today) + len(new_signals),
        "vix": vix_value,
        "sentiment_world": sw,
        "sentiment_eu": seu,
    }
    portfolio["daily_snapshots"].append(snapshot)

    # Phase 5: Compare with backtest expectations
    backtest_comparison = compare_with_backtest(portfolio)

    # Phase 6: Health check
    hc = health_check(portfolio, price_cache)
    log.info(f"Health check: {json.dumps(hc)}")

    # Phase 7: Print daily summary
    total_pnl = portfolio_value - STARTING_CAPITAL
    total_pnl_pct = (total_pnl / STARTING_CAPITAL) * 100

    winners_today = [t for t in trades_today if t["pnl"] > 0]
    losers_today = [t for t in trades_today if t["pnl"] <= 0]
    daily_pnl = sum(t["pnl"] for t in trades_today)

    # Top positions for summary
    top_positions = []
    for asset_id, pos in portfolio["positions"].items():
        price = price_cache.get(asset_id, pos["entry_price"])
        pos_pnl_pct = ((price - pos["entry_price"]) / pos["entry_price"]) * 100
        top_positions.append({"asset": pos["name"], "pnl_pct": round(pos_pnl_pct, 2)})
    top_positions.sort(key=lambda x: x["pnl_pct"], reverse=True)

    print_daily_summary(
        portfolio_value=portfolio_value,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        daily_pnl=daily_pnl,
        open_positions=len(portfolio["positions"]),
        trades_today=len(trades_today) + len(new_signals),
        winners=len(winners_today),
        losers=len(losers_today),
        drawdown_pct=drawdown_pct,
        top_positions=top_positions,
        backtest_comparison=backtest_comparison,
        runtime=time.time() - start_time,
        vix=vix_value,
    )

    # Send Telegram daily summary
    if ALERTS_AVAILABLE:
        send_daily_summary(
            portfolio_value=portfolio_value,
            starting_capital=STARTING_CAPITAL,
            daily_pnl=daily_pnl,
            total_pnl_pct=total_pnl_pct,
            open_positions=len(portfolio["positions"]),
            trades_today=len(trades_today) + len(new_signals),
            winners_today=len(winners_today),
            losers_today=len(losers_today),
            top_positions=top_positions,
            is_paper=True,
        )

    # Save equity chart
    save_equity_chart(portfolio)

    # Save portfolio
    save_portfolio(portfolio)

    log.info(f"=== Paper Trading Complete ({time.time() - start_time:.1f}s) ===")


# ââ Backtest Comparison ââââââââââââââââââââââââââââââââââââââ

def compare_with_backtest(portfolio: dict) -> dict | None:
    """
    Compare paper trading results against backtest predictions.
    Reads arena_backtest_results.json if available.
    """
    backtest_file = Path("arena_backtest_results.json")
    if not backtest_file.exists():
        log.info("No arena_backtest_results.json found â skipping comparison.")
        return None

    try:
        with open(backtest_file, "r") as f:
            backtest = json.load(f)

        score_trader = backtest.get("Score Trader", {})
        bt_return = score_trader.get("Return%", 0)
        bt_sharpe = score_trader.get("Sharpe", 0)
        bt_maxdd = score_trader.get("MaxDD%", 0)
        bt_winrate = score_trader.get("WinRate%", 0)

        # Paper trading stats
        total_trades = len(portfolio.get("trade_history", []))
        if total_trades > 0:
            wins = sum(1 for t in portfolio["trade_history"] if t["pnl"] > 0)
            paper_winrate = (wins / total_trades) * 100
        else:
            paper_winrate = 0.0

        snapshots = portfolio.get("daily_snapshots", [])
        n_days = len(snapshots)

        comparison = {
            "backtest_return_pct": bt_return,
            "backtest_sharpe": bt_sharpe,
            "backtest_maxdd_pct": bt_maxdd,
            "backtest_winrate_pct": bt_winrate,
            "paper_trades": total_trades,
            "paper_winrate_pct": round(paper_winrate, 1),
            "paper_days_running": n_days,
            "note": "Backtest covers ~10yr; paper trading is live forward-test.",
        }

        log.info(
            f"Backtest comparison: BT WinRate={bt_winrate}%, "
            f"Paper WinRate={paper_winrate:.1f}% "
            f"({total_trades} trades over {n_days} days)"
        )
        return comparison

    except Exception as exc:
        log.warning(f"Backtest comparison error: {exc}")
        return None


# ââ Console Summary ââââââââââââââââââââââââââââââââââââââââââ

def print_daily_summary(
    portfolio_value,
    total_pnl,
    total_pnl_pct,
    daily_pnl,
    open_positions,
    trades_today,
    winners,
    losers,
    drawdown_pct,
    top_positions,
    backtest_comparison,
    runtime,
    vix,
):
    """Print a formatted daily summary to console."""
    print("\n" + "=" * 60)
    print("  PAPER TRADING â DAILY SUMMARY")
    print("=" * 60)
    print(f"  Date:             {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Portfolio Value:  ${portfolio_value:,.2f}")
    print(f"  Starting Capital: ${STARTING_CAPITAL:,.2f}")
    print(f"  Total P&L:        ${total_pnl:+,.2f} ({total_pnl_pct:+.2f}%)")
    print(f"  Daily P&L:        ${daily_pnl:+,.2f}")
    print(f"  Drawdown:         -{drawdown_pct:.2f}%")
    if vix is not None:
        print(f"  VIX:              {vix:.1f}")
    print(f"  Open Positions:   {open_positions}")
    print(f"  Trades Today:     {trades_today} (W:{winners} / L:{losers})")
    print(f"  Kelly Fraction:   {KELLY_FRACTION}")
    print(f"  Max Exposure:     {MAX_EXPOSURE*100:.0f}%")

    if top_positions:
        print("\n  Top Positions:")
        for pos in top_positions[:5]:
            indicator = "+" if pos["pnl_pct"] >= 0 else ""
            print(f"    {pos['asset']:20s} {indicator}{pos['pnl_pct']:.2f}%")

    if backtest_comparison:
        print("\n  Backtest Comparison:")
        print(f"    BT WinRate:     {backtest_comparison['backtest_winrate_pct']}%")
        print(f"    Paper WinRate:  {backtest_comparison['paper_winrate_pct']}%")
        print(f"    Paper Trades:   {backtest_comparison['paper_trades']}")
        print(f"    Days Running:   {backtest_comparison['paper_days_running']}")

    print(f"\n  Runtime: {runtime:.1f}s")
    print("=" * 60 + "\n")


# ââ Entry Point ââââââââââââââââââââââââââââââââââââââââââââââ

if __name__ == "__main__":
    run_paper_trading()
