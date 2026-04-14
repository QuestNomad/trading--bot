"""
backtest_os.py - Retrospektiver Backtest der OS-Strategie.
Methode: synthetische Mini-Futures (Hebel 7x, KO-Buffer 1%) auf historische Spots.
"""
import os as _os
from universe import all_assets
import yfinance as yf
import pandas as pd
import numpy as np
import math

KELLY = 0.0694
MAX_POS = 10
MAX_PER_SECTOR = 4
TOTAL_COST = 0.003
BUY_THRESHOLD = int(_os.environ.get("BUY_THRESHOLD", "5"))
SELL_THRESHOLD = -3
LEVERAGE = 7.0
KO_BUFFER_PCT = 1.0
STARTING_CAPITAL = 10000.0
LOOKBACK_DAYS = int(_os.environ.get("LOOKBACK_DAYS", "365"))

ASSETS = all_assets()
ASSET_TO_SECTOR = {a["id"]: a["sektor"] for a in ASSETS}


def fetch_history(ticker, days):
    try:
        df = yf.download(ticker, period=f"{days+100}d", interval="1d",
                         progress=False, auto_adjust=True)
    except Exception:
        return None
    if df.empty: return None
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = close.dropna()
    if len(close) < 100: return None
    return close


def rsi(s, n=14):
    d = s.diff()
    g = d.where(d > 0, 0).rolling(n).mean()
    l = -d.where(d < 0, 0).rolling(n).mean()
    return 100 - (100 / (1 + (g / l.replace(0, np.nan))))


def compute_score_at(close_series, idx):
    window = close_series.iloc[:idx+1]
    if len(window) < 50: return None
    current = float(window.iloc[-1])
    sma20 = float(window.rolling(20).mean().iloc[-1])
    std20 = float(window.rolling(20).std().iloc[-1])
    bb_lower = sma20 - 2 * std20
    bb_upper = sma20 + 2 * std20
    r = float(rsi(window).iloc[-1])
    if not math.isfinite(r): return None
    score = 0
    if current < bb_lower: score += 3
    elif current > bb_upper: score -= 2
    if r < 30: score += 3
    elif r > 70: score -= 2
    elif r <= 50: score += 1
    if current > sma20: score += 3
    else: score -= 2
    return score


def make_mini(spot, direction):
    bv = 0.1
    if direction == "LONG":
        target_price = spot / LEVERAGE
        strike = spot - target_price / bv
        ko = strike * (1 + KO_BUFFER_PCT/100)
    else:
        target_price = spot / LEVERAGE
        strike = spot + target_price / bv
        ko = strike * (1 - KO_BUFFER_PCT/100)
    return {"strike": strike, "ko": ko, "bv": bv, "type": direction, "entry_spot": spot}


def mini_price(mini, spot):
    if mini["type"] == "LONG":
        if spot <= mini["ko"]: return 0.0
        return max(0.0, (spot - mini["strike"]) * mini["bv"])
    else:
        if spot >= mini["ko"]: return 0.0
        return max(0.0, (mini["strike"] - spot) * mini["bv"])


def is_ko(mini, spot):
    return mini_price(mini, spot) <= 0


def backtest():
    print(f"Lade {len(ASSETS)} Underlyings ({LOOKBACK_DAYS}d)...")
    histories = {}
    for asset in ASSETS:
        h = fetch_history(asset["id"], LOOKBACK_DAYS)
        if h is not None and len(h) >= 100:
            histories[asset["id"]] = h
    print(f"OK: {len(histories)}/{len(ASSETS)} Underlyings geladen.")
    if not histories:
        print("Keine Daten - Abbruch."); return
    all_dates = sorted(set().union(*[h.index for h in histories.values()]))
    backtest_dates = all_dates[-LOOKBACK_DAYS:] if len(all_dates) > LOOKBACK_DAYS else all_dates
    print(f"Backtest-Tage: {len(backtest_dates)} ({backtest_dates[0].date()} - {backtest_dates[-1].date()})")

    cash = STARTING_CAPITAL
    positions = {}
    trades = []
    daily_pv = []

    for date in backtest_dates:
        spots = {}
        for aid, h in histories.items():
            try:
                s = float(h.loc[date])
                if math.isfinite(s) and s > 0:
                    spots[aid] = s
            except KeyError: continue

        # KO + Reversal
        for aid in list(positions.keys()):
            spot = spots.get(aid)
            if spot is None: continue
            pos = positions[aid]
            if is_ko(pos["mini"], spot):
                trades.append({"asset": aid, "direction": pos["mini"]["type"],
                               "entry": pos["entry_price"], "exit": 0.0, "qty": pos["qty"],
                               "pnl": -pos["qty"]*pos["entry_price"], "pnl_pct": -100.0,
                               "entry_date": pos["entry_date"],
                               "exit_date": str(date.date()), "reason": "KO"})
                del positions[aid]; continue
            idx = histories[aid].index.get_loc(date)
            sc = compute_score_at(histories[aid], idx)
            if sc is None: continue
            if (pos["mini"]["type"] == "LONG" and sc <= SELL_THRESHOLD) or \
               (pos["mini"]["type"] == "SHORT" and sc >= BUY_THRESHOLD):
                exit_price = mini_price(pos["mini"], spot)
                proceeds = pos["qty"] * exit_price * (1 - TOTAL_COST)
                pnl = proceeds - pos["qty"] * pos["entry_price"]
                cash += proceeds
                trades.append({"asset": aid, "direction": pos["mini"]["type"],
                               "entry": pos["entry_price"], "exit": exit_price, "qty": pos["qty"],
                               "pnl": pnl, "pnl_pct": (pnl/(pos["qty"]*pos["entry_price"]))*100,
                               "entry_date": pos["entry_date"], "exit_date": str(date.date()),
                               "reason": "Reversal"})
                del positions[aid]

        # Neue Signale
        for asset in ASSETS:
            aid = asset["id"]
            if aid in positions: continue
            if len(positions) >= MAX_POS: break
            spot = spots.get(aid)
            if spot is None: continue
            sector = ASSET_TO_SECTOR.get(aid, "Other")
            sec_count = sum(1 for p in positions.values()
                            if ASSET_TO_SECTOR.get(p["asset_id"], "Other") == sector)
            if sec_count >= MAX_PER_SECTOR: continue
            idx = histories[aid].index.get_loc(date)
            sc = compute_score_at(histories[aid], idx)
            if sc is None: continue
            direction = None
            if sc >= BUY_THRESHOLD: direction = "LONG"
            elif sc <= SELL_THRESHOLD: direction = "SHORT"
            else: continue
            mini = make_mini(spot, direction)
            entry_price = mini_price(mini, spot)
            if entry_price <= 0: continue
            pv_now = cash + sum(mini_price(p["mini"], spots.get(p["asset_id"], p["mini"]["entry_spot"]))*p["qty"]
                                for p in positions.values())
            trade_val = pv_now * KELLY
            qty = trade_val / entry_price
            cost = trade_val * (1 + TOTAL_COST)
            if cost > cash: continue
            cash -= cost
            positions[aid] = {"mini": mini, "qty": qty, "entry_price": entry_price,
                              "entry_date": str(date.date()), "asset_id": aid, "score": sc}

        pv = cash + sum(mini_price(p["mini"], spots.get(p["asset_id"], p["mini"]["entry_spot"]))*p["qty"]
                        for p in positions.values())
        daily_pv.append((date, pv, cash, len(positions)))

    # Final close
    final_date = backtest_dates[-1]
    final_spots = {aid: float(h.loc[final_date]) for aid, h in histories.items()
                   if final_date in h.index}
    for aid, pos in list(positions.items()):
        spot = final_spots.get(aid, pos["mini"]["entry_spot"])
        exit_price = mini_price(pos["mini"], spot)
        proceeds = pos["qty"] * exit_price * (1 - TOTAL_COST)
        pnl = proceeds - pos["qty"] * pos["entry_price"]
        cash += proceeds
        trades.append({"asset": aid, "direction": pos["mini"]["type"],
                       "entry": pos["entry_price"], "exit": exit_price, "qty": pos["qty"],
                       "pnl": pnl, "pnl_pct": (pnl/(pos["qty"]*pos["entry_price"]))*100,
                       "entry_date": pos["entry_date"], "exit_date": str(final_date.date()),
                       "reason": "Final"})
    return cash, trades, daily_pv


if __name__ == "__main__":
    res = backtest()
    if not res: import sys; sys.exit(1)
    cash_final, trades, daily_pv = res
    pv_final = daily_pv[-1][1]
    total_return = (pv_final / STARTING_CAPITAL - 1) * 100
    print(f"\n{'='*60}\nBACKTEST ERGEBNISSE\n{'='*60}")
    print(f"Startkapital: ${STARTING_CAPITAL:,.2f}")
    print(f"Endwert:      ${pv_final:,.2f}")
    print(f"Total Return: {total_return:+.2f}%")
    print(f"Periode:      {daily_pv[0][0].date()} - {daily_pv[-1][0].date()} ({len(daily_pv)} Tage)")
    print(f"\nTrades: {len(trades)}")
    if trades:
        winners = [t for t in trades if t["pnl"] > 0]
        losers  = [t for t in trades if t["pnl"] <= 0]
        ko = [t for t in trades if t["reason"] == "KO"]
        print(f"  Winners:    {len(winners)} ({100*len(winners)/len(trades):.1f}%)")
        print(f"  Losers:     {len(losers)} ({100*len(losers)/len(trades):.1f}%)")
        print(f"  KO:         {len(ko)}")
        if winners: print(f"  Avg Win:    {np.mean([t['pnl_pct'] for t in winners]):+.2f}%")
        if losers: print(f"  Avg Loss:   {np.mean([t['pnl_pct'] for t in losers]):+.2f}%")
        print(f"  Best/Worst: {max(t['pnl_pct'] for t in trades):+.2f}% / {min(t['pnl_pct'] for t in trades):+.2f}%")
        print(f"  Sum PnL:    ${sum(t['pnl'] for t in trades):+,.2f}")
    pvs = [pv for _, pv, _, _ in daily_pv]
    peak = pvs[0]; max_dd = 0
    for v in pvs:
        peak = max(peak, v); dd = (peak - v) / peak * 100; max_dd = max(max_dd, dd)
    print(f"\nMax Drawdown: {max_dd:.2f}%")
    rets = pd.Series(pvs).pct_change().dropna()
    if len(rets) > 1 and rets.std() > 0:
        print(f"Sharpe (ann): {(rets.mean() / rets.std()) * np.sqrt(252):.2f}")
