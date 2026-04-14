#!/usr/bin/env python3
"""
paper_trading_os.py - Score Trader auf Open-End Turbos (Mini-Futures)

v2.0 - 2026-04-14

Aenderungen ggue. paper_trading.py:
  * Universum: 62 Underlyings (universe.py) statt 38
  * Trade-Asset: Mini-Future statt Spot (Hebel 5-10x)
  * Signal-Logik unveraendert (BB/RSI/SMA Score)
  * Statt Spot-Position wird Mini-Future via os_selector.find_mini_future() gewaehlt
  * Pricing: LS Exchange Live-Quotes (os_quotes), Fallback theoretischer Preis
  * Knock-Out-Monitoring: bei Knock-Out wird Position automatisch geschlossen
  * SHORT moeglich via SHORT-Mini-Future (kein separater Inverse-ETF noetig)
  * Eigene State-Files: paper_portfolio_os.json + journal_os.csv (parallel zum
    Spot-Bot - kein Eingriff in den bestehenden Live-Bot).

NaN-Defenses aus dem Spot-Bot uebernommen.
"""
import os
import sys
import csv
import json
import math
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

# Local modules
from universe import all_assets, build_lookup
from os_selector import find_mini_future, is_knocked_out, mini_future_price
from os_quotes import get_quote_or_compute

try:
    from alerts import (
        send_trade_alert,
        send_daily_summary,
        send_drawdown_alert,
    )
    ALERTS_AVAILABLE = True
except ImportError:
    ALERTS_AVAILABLE = False

# ── Configuration ─────────────────────────────────────────────
STARTING_CAPITAL = 10_000.0
KELLY_FRACTION = 0.0694
MAX_OPEN_POSITIONS = 10
PORTFOLIO_FILE = "paper_portfolio_os.json"
JOURNAL_FILE = "journal_os.csv"

TRADING_FEE = 0.0015
SPREAD_COST = 0.0005
SLIPPAGE_COST = 0.001
TOTAL_COST = TRADING_FEE + SPREAD_COST + SLIPPAGE_COST

BUY_THRESHOLD = 5
VIX_LIMIT = 30
MAX_EXPOSURE = 0.80
MAX_POSITIONS_PER_SECTOR = 4
DRAWDOWN_ALERT_PCT = 5.0

LEVERAGE_TARGET = 7.0
LEVERAGE_RANGE = (5.0, 10.0)
KNOCK_OUT_BUFFER_PCT = 2.0

DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(message)s",
                    force=True)
# Sub-Logger explizit auf INFO setzen, damit os_selector/os_quotes Logs sichtbar sind
for name in ["os_selector", "os_quotes", "paper_trading_os", "__main__"]:
    logging.getLogger(name).setLevel(logging.INFO)
log = logging.getLogger("paper-os")
log.info(f"Universum: {len(all_assets())} Underlyings geladen")

ASSETS = all_assets()
ASSET_LOOKUP = build_lookup()
ASSET_TO_SECTOR = {a["id"]: a["sektor"] for a in ASSETS}
_yf_lock = threading.Lock()


def get_prices(asset):
    try:
        with _yf_lock:
            df = yf.download(asset["id"], period="300d", interval="1d",
                             progress=False, auto_adjust=True)
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
        log.warning(f"yfinance error for {asset['id']}: {exc}")
        return None


def get_vix():
    """Hole VIX. Mehrere Ticker-Versuche, bei Fehler 0.0 (= kein Risk-Off)."""
    for ticker in ["^VIX", "VIX", "VIXY"]:
        try:
            with _yf_lock:
                df = yf.download(ticker, period="30d", interval="1d",
                                 progress=False, auto_adjust=True)
            if df.empty: continue
            close = df["Close"].dropna()
            if len(close) == 0: continue
            v = float(close.iloc[-1])
            if math.isfinite(v) and v > 0:
                log.info(f"VIX from {ticker}: {v:.2f}")
                return v
        except Exception as exc:
            log.debug(f"VIX fetch {ticker} failed: {exc}")
            continue
    log.warning("VIX unavailable - assuming neutral (0)")
    return 0.0


def sma(prices, n): return pd.Series(prices).rolling(n).mean()

def rsi_val(prices, n=14):
    s = pd.Series(prices); d = s.diff()
    g = d.where(d > 0, 0).rolling(n).mean()
    l = -d.where(d < 0, 0).rolling(n).mean()
    if float(l.iloc[-1]) == 0: return 100.0
    return float((100 - (100 / (1 + (g / l)))).iloc[-1])

def atr_val(prices, n=14):
    s = pd.Series(prices); tr = s.diff().abs(); tr.iloc[0] = 0
    a = float(tr.rolling(n).mean().iloc[-1])
    return a if math.isfinite(a) else 0.0

def bollinger_bands(prices, n=20, k=2):
    s = pd.Series(prices)
    m = s.rolling(n).mean(); std = s.rolling(n).std()
    return float(m.iloc[-1]), float((m + k*std).iloc[-1]), float((m - k*std).iloc[-1])


def compute_signal(prices):
    if len(prices) < 50: return "WAIT", 0, {}
    current = float(prices[-1])
    r = rsi_val(prices); a = atr_val(prices)
    sma20 = float(sma(prices, 20).iloc[-1])
    bb_mid, bb_upper, bb_lower = bollinger_bands(prices, 20, 2)
    score = 0
    if current < bb_lower: score += 3
    elif current > bb_upper: score -= 2
    if r < 30: score += 3
    elif r > 70: score -= 2
    elif r <= 50: score += 1
    if current > sma20: score += 3
    else: score -= 2
    if score >= BUY_THRESHOLD: signal = "BUY"
    elif score <= -3: signal = "SELL"
    else: signal = "WAIT"
    return signal, score, {"price": current, "rsi": r, "atr": a, "sma20": sma20, "score": score}


# ── Portfolio I/O ────────────────────────────────────────────

def default_portfolio():
    return {"capital": STARTING_CAPITAL, "cash": STARTING_CAPITAL,
            "positions": {}, "trade_history": [], "daily_snapshots": [],
            "peak_value": STARTING_CAPITAL, "total_fees_paid": 0.0,
            "created_at": datetime.now().isoformat()}

def load_portfolio():
    p = Path(PORTFOLIO_FILE)
    if not p.exists(): return default_portfolio()
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning(f"Corrupt portfolio - starting fresh: {exc}")
        return default_portfolio()

def save_portfolio(portfolio):
    portfolio["last_run"] = datetime.now().isoformat()
    Path(PORTFOLIO_FILE).write_text(
        json.dumps(portfolio, indent=2, ensure_ascii=False), encoding="utf-8")


def count_sector_positions(portfolio, asset_id):
    sector = ASSET_TO_SECTOR.get(asset_id, "Other")
    return sum(1 for p in portfolio["positions"].values()
               if ASSET_TO_SECTOR.get(p["underlying_id"], "Other") == sector)


def calculate_positions_value(portfolio, spot_cache):
    total = 0.0
    for asset_id, pos in portfolio["positions"].items():
        spot = spot_cache.get(pos["underlying_id"], pos.get("entry_spot", 0))
        if not math.isfinite(spot) or spot <= 0:
            spot = pos.get("entry_spot", 0)
        price = mini_future_price(pos["mini"], spot)
        total += price * pos["quantity"]
    return total

def calculate_portfolio_value(portfolio, spot_cache):
    return portfolio["cash"] + calculate_positions_value(portfolio, spot_cache)

def apply_fee(amount):
    fee = amount * TOTAL_COST
    return amount - fee, fee


def execute_buy(portfolio, asset, spot, details, spot_cache, direction="LONG"):
    asset_id = asset["id"]
    if not math.isfinite(spot) or spot <= 0: return False
    if asset_id in portfolio["positions"]: return False
    if len(portfolio["positions"]) >= MAX_OPEN_POSITIONS: return False
    if count_sector_positions(portfolio, asset_id) >= MAX_POSITIONS_PER_SECTOR: return False

    mini = find_mini_future(asset_id, direction=direction,
                            leverage_target=LEVERAGE_TARGET,
                            leverage_range=LEVERAGE_RANGE)
    if not mini:
        log.info(f"  No suitable Mini-Future for {asset['name']} {direction}")
        return False

    ko_dist = abs(spot - mini["knock_out"]) / spot * 100
    if ko_dist < KNOCK_OUT_BUFFER_PCT:
        log.info(f"  KO too close ({ko_dist:.1f}%) for {asset['name']}")
        return False

    quote_price, source = get_quote_or_compute(mini, spot)
    if not math.isfinite(quote_price) or quote_price <= 0:
        log.info(f"  Invalid mini price for {asset['name']}")
        return False

    pv = calculate_portfolio_value(portfolio, spot_cache)
    trade_value = pv * KELLY_FRACTION
    if trade_value < 10: return False
    qty = trade_value / quote_price

    net_cost, fee = apply_fee(trade_value)
    total_cost = trade_value + fee
    if total_cost > portfolio["cash"]:
        log.info(f"  Insufficient cash for {asset['name']}")
        return False

    portfolio["cash"] -= total_cost
    portfolio["total_fees_paid"] += fee
    portfolio["positions"][asset_id] = {
        "name": asset["name"], "underlying_id": asset_id,
        "direction": direction, "mini": mini,
        "entry_spot": spot, "entry_price": quote_price,
        "entry_price_source": source, "quantity": qty,
        "score": details.get("score", 0),
        "entry_date": datetime.now().isoformat(),
    }
    log.info(f"  BUY {direction} {asset['name']}: WKN {mini['wkn']} qty={qty:.2f} @ {quote_price:.4f}")
    return True


def execute_sell(portfolio, asset_id, spot, reason):
    if asset_id not in portfolio["positions"]: return None
    if not math.isfinite(spot) or spot <= 0:
        log.warning(f"  Skip SELL {asset_id}: invalid spot")
        return None
    pos = portfolio["positions"][asset_id]
    quote_price, source = get_quote_or_compute(pos["mini"], spot)
    if not math.isfinite(quote_price) or quote_price < 0:
        log.warning(f"  Skip SELL {asset_id}: invalid quote")
        return None
    trade_value = pos["quantity"] * quote_price
    net_proceeds, fee = apply_fee(trade_value)
    portfolio["cash"] += net_proceeds
    portfolio["total_fees_paid"] += fee
    entry_cost = pos["quantity"] * pos["entry_price"]
    pnl = net_proceeds - entry_cost
    pnl_pct = (pnl / entry_cost) * 100 if entry_cost > 0 else 0.0
    record = {
        "asset": pos["name"], "underlying_id": pos["underlying_id"],
        "wkn": pos["mini"]["wkn"], "emittent": pos["mini"]["emittent"],
        "direction": pos["direction"],
        "entry_price": pos["entry_price"], "exit_price": quote_price,
        "exit_source": source, "quantity": pos["quantity"],
        "entry_spot": pos["entry_spot"], "exit_spot": spot,
        "entry_date": pos["entry_date"], "exit_date": datetime.now().isoformat(),
        "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
        "fee_paid": round(fee, 2), "reason": reason,
    }
    portfolio["trade_history"].append(record)
    del portfolio["positions"][asset_id]
    log.info(f"  SELL {asset_id} ({pos['mini']['wkn']}): P&L {pnl:+.2f} ({pnl_pct:+.2f}%) | {reason}")
    append_journal(record)
    return record


def append_journal(record):
    p = Path(JOURNAL_FILE)
    is_new = not p.exists()
    fields = ["entry_date", "exit_date", "asset", "underlying_id", "wkn",
              "emittent", "direction", "entry_price", "exit_price",
              "entry_spot", "exit_spot", "quantity", "pnl", "pnl_pct",
              "fee_paid", "reason", "exit_source"]
    with p.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if is_new: w.writeheader()
        w.writerow(record)


def main():
    log.info(f"=== Paper Trading OS Bot {'(DRY-RUN)' if DRY_RUN else ''} ===")
    portfolio = load_portfolio()
    log.info(f"Loaded portfolio: cash=${portfolio['cash']:.2f}, positions={len(portfolio['positions'])}")
    vix = get_vix()
    log.info(f"VIX: {vix}")
    spot_cache = {}
    series_cache = {}

    # Phase 1: Spots fuer offene Positionen
    for asset_id in list(portfolio["positions"].keys()):
        pos = portfolio["positions"][asset_id]
        underlying = ASSET_LOOKUP.get(pos["underlying_id"])
        if not underlying: continue
        prices = get_prices(underlying)
        if prices and len(prices) > 0:
            last = float(prices[-1])
            if math.isfinite(last) and last > 0:
                spot_cache[pos["underlying_id"]] = last
                series_cache[pos["underlying_id"]] = prices

    # Phase 2: Knock-Out & Signal-Reversal-Check
    trades_today = []
    for asset_id in list(portfolio["positions"].keys()):
        pos = portfolio["positions"][asset_id]
        spot = spot_cache.get(pos["underlying_id"])
        if spot is None: continue
        if is_knocked_out(pos["mini"], spot):
            t = execute_sell(portfolio, asset_id, spot, "KNOCK-OUT")
            if t: trades_today.append(t)
            continue
        prices = series_cache.get(pos["underlying_id"])
        if prices:
            sig, sc, _ = compute_signal(prices)
            if (pos["direction"] == "LONG"  and sc <= -3) or \
               (pos["direction"] == "SHORT" and sc >=  5):
                t = execute_sell(portfolio, asset_id, spot, f"Signal-Reversal score={sc}")
                if t: trades_today.append(t)

    # Phase 3: Neue Signale
    new_signals = 0
    stats = {"scanned": 0, "no_data": 0, "buy_signal": 0, "sell_signal": 0,
             "wait": 0, "buy_executed": 0, "sell_executed": 0}
    if vix is None or vix <= VIX_LIMIT:
        for asset in ASSETS:
            asset_id = asset["id"]
            if asset_id in portfolio["positions"]: continue
            stats["scanned"] += 1
            prices = series_cache.get(asset_id) or get_prices(asset)
            if not prices or len(prices) < 50:
                stats["no_data"] += 1
                continue
            current = float(prices[-1])
            if not math.isfinite(current) or current <= 0:
                stats["no_data"] += 1
                continue
            spot_cache[asset_id] = current
            sig, sc, det = compute_signal(prices)
            if sig == "BUY":
                stats["buy_signal"] += 1
                if execute_buy(portfolio, asset, current, det, spot_cache, "LONG"):
                    new_signals += 1
                    stats["buy_executed"] += 1
            elif sig == "SELL":
                stats["sell_signal"] += 1
                if execute_buy(portfolio, asset, current, det, spot_cache, "SHORT"):
                    new_signals += 1
                    stats["sell_executed"] += 1
            else:
                stats["wait"] += 1
    log.info(f"Scan-Stats: {stats}")

    # Phase 4: Snapshot
    pv = calculate_portfolio_value(portfolio, spot_cache)
    if pv > portfolio.get("peak_value", STARTING_CAPITAL):
        portfolio["peak_value"] = pv
    peak = portfolio["peak_value"]
    dd = ((peak - pv) / peak) * 100 if peak > 0 else 0.0
    snap = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "portfolio_value": round(pv, 2),
        "cash": round(portfolio["cash"], 2),
        "positions_value": round(pv - portfolio["cash"], 2),
        "num_positions": len(portfolio["positions"]),
        "drawdown_pct": round(dd, 2),
        "trades_today": len(trades_today) + new_signals,
        "vix": vix,
    }
    portfolio["daily_snapshots"].append(snap)
    if not DRY_RUN:
        save_portfolio(portfolio)
        log.info(f"Saved. PV=${pv:,.2f}, cash=${portfolio['cash']:,.2f}, positions={len(portfolio['positions'])}")
    else:
        log.info(f"[DRY-RUN] PV=${pv:,.2f}, trades={snap['trades_today']}")


if __name__ == "__main__":
    main()
