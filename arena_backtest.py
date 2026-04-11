#!/usr/bin/env python3
"""Arena Backtest - 6 Strategien, 38 Assets, 10 Jahre retrospektiv
(inkl. Trading 212 Gebuehren + Spread + Slippage).

Enhancements v2:
  1. Per-Asset Performance Analysis for Score Trader
  2. Out-of-Sample Test (7yr train / 3yr test)
  3. Slippage Modelling (0.10% on top of fees)
  4. Parameter Sensitivity Test for Score Trader
"""

import json, datetime as dt, numpy as np, pandas as pd, yfinance as yf, pathlib, textwrap

# -- Trading 212 Gebuehren ---------------------------------------------------
TRADING_FEE  = 0.0015   # 0.15% FX-Fee pro Trade (Trading 212, EUR->USD)
SPREAD_COST  = 0.0005   # 0.05% Spread-Simulation pro Trade
SLIPPAGE_COST = 0.001   # 0.10% Slippage pro Trade (NEW)
TOTAL_COST   = TRADING_FEE + SPREAD_COST + SLIPPAGE_COST  # 0.30% total

# -- Assets ------------------------------------------------------------------
ASSETS = [
    "SPY","QQQ","IWM","EFA","EEM","VGK","EWJ","FXI","VNQ","XLE","XLF","XLV",
    "XLK","XLI","XLU","XLP","XLY","XLRE","XBI","ARKK","GLD","SLV","TLT",
    "HYG","LQD","BND","UNG","USO","DBA","MSTR","NVDA", "AAPL","MSFT","TSLA",
    "IBIT","BITO","COIN","XLC"
]
BENCH = "SPY"; VIX = "^VIX"; RF = 0.045; REBAL_DAYS = 5
end   = dt.date.today(); start = end - dt.timedelta(days=10*365+30)

# -- Daten laden ------------------------------------------------------------
print("Downloading data ...")
tickers = list(set(ASSETS + [VIX]))
raw = yf.download(tickers, start=str(start), end=str(end),
                   group_by="ticker", auto_adjust=True)
close = pd.DataFrame({t: raw[t]["Close"] for t in tickers
                       if t in raw.columns.get_level_values(0)}).dropna(how="all").ffill()
ret   = close[ASSETS].pct_change().fillna(0)
spy   = close[BENCH]; sma200 = spy.rolling(200).mean()
risk_off = spy < sma200   # True = Cash

# -- Hilfsfunktionen --------------------------------------------------------
def sharpe(eq):
    r = eq.pct_change().dropna()
    return (r.mean()*252 - RF) / (r.std()*np.sqrt(252)+1e-9)

def max_dd(eq):
    peak = eq.cummax(); dd = (eq - peak) / peak
    return dd.min()

def kpi(eq, trades=0):
    total = eq.iloc[-1]/eq.iloc[0]-1
    return {"Return%": round(total*100, 2),
            "Sharpe":  round(sharpe(eq), 2),
            "MaxDD%":  round(max_dd(eq)*100, 2),
            "Trades":  trades}

# -- Strategien -------------------------------------------------------------
dates = ret.index[200:]   # nach SMA200 warm-up

def strat_buyhold():
    w = 1.0 / len(ASSETS)
    daily = ret[ASSETS].loc[dates].mean(axis=1) * w * len(ASSETS)
    eq = (1 + daily).cumprod() * 10000
    return eq, kpi(eq)

def strat_crash_guard():
    vals = [10000.0]; prev = 10000.0; was_off = None
    for d in dates:
        is_off = risk_off.loc[d]
        if was_off is not None and is_off != was_off:
            prev *= (1 - TOTAL_COST)   # Fee + Spread + Slippage bei Switch
        was_off = is_off
        r = ret.loc[d, BENCH] if not is_off else 0.0
        prev *= (1 + r); vals.append(prev)
    eq = pd.Series(vals[1:], index=dates)
    switches = int(risk_off.loc[dates].astype(int).diff().abs().sum())
    return eq, kpi(eq, switches)

def strat_momentum():
    vals = [10000.0]; prev = 10000.0; held = []; trades = 0
    for i, d in enumerate(dates):
        if i % REBAL_DAYS == 0:
            if risk_off.loc[d]:
                if held:
                    prev *= (1 - TOTAL_COST)   # Fee + Spread + Slippage: Verkauf
                    trades += len(held)
                held = []
            else:
                mom = close[ASSETS].loc[:d].pct_change(63).iloc[-1].nlargest(10).index.tolist()
                if set(mom) != set(held):
                    if held:
                        prev *= (1 - TOTAL_COST)   # Fee + Spread + Slippage: Verkauf
                    prev *= (1 - TOTAL_COST)       # Fee + Spread + Slippage: Kauf
                    trades += len(mom)
                held = mom
        if held:
            r = ret.loc[d, held].mean()
        else:
            r = 0.0
        prev *= (1 + r); vals.append(prev)
    eq = pd.Series(vals[1:], index=dates)
    return eq, kpi(eq, trades)

def strat_score_trader(date_range=None, bb_period=20, rsi_period=14,
                        atr_sl_mult=3.0, track_per_asset=False):
    """Score Trader with configurable parameters.

    Args:
        date_range: tuple (start_idx, end_idx) to slice dates, or None for all
        bb_period: Bollinger Band period (default 20)
        rsi_period: RSI period (default 14)
        atr_sl_mult: ATR multiplier for stop-loss (default 3.0)
        track_per_asset: if True, collect per-asset statistics
    """
    use_dates = dates[date_range[0]:date_range[1]] if date_range else dates

    vals = [10000.0]; prev = 10000.0; positions = {}; trades = 0

    # Precompute indicators with configurable periods
    atr_ind = {}; rsi_ind = {}
    for a in ASSETS:
        h = close[a]
        delta = h.diff()
        gain  = delta.clip(lower=0).rolling(rsi_period).mean()
        loss  = (-delta.clip(upper=0)).rolling(rsi_period).mean()
        rsi_ind[a] = 100 - 100/(1 + gain/(loss+1e-9))
        atr_ind[a] = h.diff().abs().rolling(rsi_period).mean()

    # Per-asset tracking
    asset_stats = {a: {"trades": 0, "wins": 0, "returns": [],
                        "holding_days": []} for a in ASSETS} if track_per_asset else None
    asset_entry_day = {}   # ticker -> index of entry day

    for i, d in enumerate(use_dates):
        # -- Check exits
        for a in list(positions):
            entry, sl, atr_entry, high = positions[a]
            p = close[a].loc[d]
            new_high = max(high, p)
            trailing_stop = new_high - atr_sl_mult * atr_entry
            effective_sl  = max(sl, trailing_stop)
            if p <= effective_sl:
                n_pos = max(len(positions), 1)
                prev *= (1 - TOTAL_COST / n_pos)   # Fee + Spread + Slippage (anteilig)
                trades += 1
                # Per-asset tracking
                if track_per_asset:
                    pnl = (p - entry) / entry
                    asset_stats[a]["trades"] += 1
                    asset_stats[a]["returns"].append(pnl)
                    if pnl > 0:
                        asset_stats[a]["wins"] += 1
                    if a in asset_entry_day:
                        asset_stats[a]["holding_days"].append(i - asset_entry_day[a])
                        del asset_entry_day[a]
                del positions[a]
            else:
                positions[a] = (entry, sl, atr_entry, new_high)

        # -- Check entries
        for a in ASSETS:
            if a in positions:
                continue
            try:
                p      = close[a].loc[d]
                sma_bb = close[a].loc[:d].rolling(bb_period).mean().iloc[-1]
                bb_mid = sma_bb
                bb_std = close[a].loc[:d].rolling(bb_period).std().iloc[-1]
                bb_low = bb_mid - 2*bb_std
                score  = 0
                if p > sma_bb:        score += 3
                if p < bb_mid + 0.5*bb_std: score += 3
                if rsi_ind[a].loc[d] < 55:  score += 2
                if score >= 8:
                    atr   = atr_ind[a].loc[d]
                    n_pos = max(len(positions) + 1, 1)
                    prev *= (1 - TOTAL_COST / n_pos)   # Fee + Spread + Slippage (anteilig)
                    positions[a] = (p, p - atr_sl_mult*atr, atr, p)
                    trades += 1
                    if track_per_asset:
                        asset_stats[a]["trades"] += 1  # entry counted
                        asset_entry_day[a] = i
            except:
                pass

        if positions:
            r = np.mean([ret.loc[d, a] for a in positions])
        else:
            r = 0.0
        prev *= (1 + r); vals.append(prev)

    eq  = pd.Series(vals[1:], index=use_dates)
    win = sum(1 for v1, v2 in zip(vals[:-1], vals[1:]) if v2 > v1)
    wr  = round(win / len(use_dates) * 100, 1)
    k   = kpi(eq, trades); k["WinRate%"] = wr

    # Close any still-open positions for per-asset stats
    if track_per_asset:
        for a in list(positions):
            entry = positions[a][0]
            p     = close[a].iloc[-1]
            pnl   = (p - entry) / entry
            asset_stats[a]["returns"].append(pnl)
            if pnl > 0:
                asset_stats[a]["wins"] += 1
            if a in asset_entry_day:
                asset_stats[a]["holding_days"].append(len(use_dates) - asset_entry_day[a])

    return eq, k, asset_stats


def strat_adaptiv():
    """Adaptiv: VIX-basierter Moduswechsel (Momentum/Crash Guard/Cash) mit Hysterese."""
    vix_close = close[VIX] if VIX in close.columns else pd.Series(20, index=close.index)
    vals = [10000.0]; prev = 10000.0; trades = 0; modus = "momentum"
    for i, d in enumerate(dates):
        vix = vix_close.loc[d] if d in vix_close.index else 20
        # Modus bestimmen mit Hysterese
        modus_alt = modus
        if vix > 30:    modus = "cash"
        elif vix > 20:  modus = "crash_guard"
        elif vix < 18 or modus_alt == "momentum": modus = "momentum"
        # else: bleibe im aktuellen Modus (Hysterese)

        if modus != modus_alt:
            prev *= (1 - TOTAL_COST)   # Fee + Spread + Slippage bei Moduswechsel
            trades += 1

        if modus == "cash":
            r = 0.0
        elif modus == "crash_guard":
            if not risk_off.loc[d]:
                r = ret.loc[d, BENCH]
            else:
                r = 0.0
        else:  # momentum
            if i % REBAL_DAYS == 0:
                mom = close[ASSETS].loc[:d].pct_change(63).iloc[-1].nlargest(10).index.tolist()
                prev *= (1 - TOTAL_COST)   # Fee + Spread + Slippage: Rebalancing
                trades += len(mom)
            if 'mom' in dir() and mom:
                r = ret.loc[d, mom].mean()
            else:
                r = 0.0
        prev *= (1 + r); vals.append(prev)
    eq = pd.Series(vals[1:], index=dates)
    return eq, kpi(eq, trades)


def strat_ensemble():
    """Ensemble: Handelt nur wenn ALLE Signale uebereinstimmen, woechentlich"""
    vals = [10000.0]; prev = 10000.0; positions = {}; trades = 0
    cooldown = {}   # ticker -> cooldown_until_index
    MAX_POSITIONS = 5

    atr14 = {}; rsi14 = {}; sma20_all = {}; sma200_all = {}; mom63 = {}
    for a in ASSETS:
        h = close[a]
        delta = h.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rsi14[a]     = 100 - 100/(1 + gain/(loss+1e-9))
        atr14[a]     = h.diff().abs().rolling(14).mean()
        sma20_all[a] = h.rolling(20).mean()
        sma200_all[a]= h.rolling(200).mean()
        mom63[a]     = h.pct_change(63)

    for i, d in enumerate(dates):
        for a in list(positions.keys()):
            try:
                p   = close[a].loc[d]
                pos = positions[a]
                if p <= pos[1] or p >= pos[2]:
                    prev *= (1 - TOTAL_COST)   # Fee + Spread + Slippage
                    trades += 1
                    cooldown[a] = i + 10
                    del positions[a]
            except:
                pass

        is_monday = hasattr(d, 'weekday') and d.weekday() == 0
        if is_monday and len(positions) < MAX_POSITIONS:
            for a in ASSETS:
                if a in positions or (a in cooldown and i < cooldown[a]):
                    continue
                try:
                    p = close[a].loc[d]
                except:
                    continue

                signals = 0; total_checks = 0
                s20     = sma20_all[a].loc[d]
                rsi_val = rsi14[a].loc[d]
                score   = 0
                if not np.isnan(s20) and p > s20:    score += 2
                if not np.isnan(rsi_val):
                    if rsi_val < 35:   score += 2
                    elif rsi_val < 50: score += 1
                if score >= 3: signals += 1
                total_checks += 1

                r63 = mom63[a].loc[d]
                if not np.isnan(r63):
                    if r63 > 0.05: signals += 1
                    total_checks += 1

                s200 = sma200_all[a].loc[d]
                if not np.isnan(s200):
                    if p > s200: signals += 1
                    total_checks += 1

                if not np.isnan(rsi_val):
                    if 30 < rsi_val < 65: signals += 1
                    total_checks += 1

                if signals >= 4 and total_checks >= 4 and len(positions) < MAX_POSITIONS:
                    atr = atr14[a].loc[d]
                    if np.isnan(atr) or atr <= 0: atr = p * 0.02
                    n_pos = max(len(positions) + 1, 1)
                    prev *= (1 - TOTAL_COST / n_pos)   # Fee + Spread + Slippage (anteilig)
                    positions[a] = (p, p - 4 * atr, p + 10 * atr); trades += 1

        if positions:
            r = np.mean([ret.loc[d, a] for a in positions])
        else:
            r = 0.0
        prev *= (1 + r); vals.append(prev)

    eq  = pd.Series(vals[1:], index=dates)
    win = sum(1 for v1, v2 in zip(vals[:-1], vals[1:]) if v2 > v1)
    wr  = round(win / len(dates) * 100, 1)
    k   = kpi(eq, trades); k["WinRate%"] = wr
    return eq, k

# ============================================================================
# ENHANCEMENT 1: Per-Asset Performance Analysis for Score Trader
# ============================================================================
def run_score_trader_per_asset():
    """Run Score Trader with per-asset tracking enabled."""
    print("  Running Score Trader per-asset analysis ...")
    eq, k, asset_stats = strat_score_trader(track_per_asset=True)

    per_asset = {}
    for a in ASSETS:
        s = asset_stats[a]
        n_trades  = s["trades"]
        returns   = s["returns"]
        wins      = s["wins"]
        holdings  = s["holding_days"]
        per_asset[a] = {
            "n_trades":          n_trades,
            "total_return%":     round(sum(returns) * 100, 2) if returns else 0.0,
            "avg_return%":       round(np.mean(returns) * 100, 2) if returns else 0.0,
            "win_rate%":         round(wins / max(n_trades, 1) * 100, 1),
            "avg_holding_days":  round(np.mean(holdings), 1) if holdings else 0.0,
        }
    return eq, k, per_asset

# ============================================================================
# ENHANCEMENT 2: Out-of-Sample Test
# ============================================================================
def run_out_of_sample():
    """Split 10yr into 7yr train + 3yr test, run Score Trader on both."""
    print("  Running Out-of-Sample test ...")
    total_days = len(dates)
    split_idx  = int(total_days * 0.7)   # 70% train, 30% test

    train_start = 0
    train_end   = split_idx
    test_start  = split_idx
    test_end    = total_days

    # Train period
    eq_train, k_train, _ = strat_score_trader(
        date_range=(train_start, train_end), track_per_asset=False)
    # Test period
    eq_test, k_test, _ = strat_score_trader(
        date_range=(test_start, test_end), track_per_asset=False)

    oos = {
        "train_period": {
            "start": str(dates[train_start]),
            "end":   str(dates[train_end - 1]),
            "days":  train_end - train_start,
            **k_train
        },
        "test_period": {
            "start": str(dates[test_start]),
            "end":   str(dates[test_end - 1]),
            "days":  test_end - test_start,
            **k_test
        },
        "return_degradation%": round(k_train["Return%"] - k_test["Return%"], 2),
        "sharpe_degradation":  round(k_train["Sharpe"] - k_test["Sharpe"], 2),
    }
    return oos

# ============================================================================
# ENHANCEMENT 4: Parameter Sensitivity Test
# ============================================================================
def run_parameter_sensitivity():
    """Run Score Trader with varied parameters to check robustness."""
    print("  Running Parameter Sensitivity test ...")
    bb_periods    = [18, 20, 22]
    rsi_periods   = [12, 14, 16]
    atr_mults     = [2.5, 3.0, 3.5]

    results = []
    for bb in bb_periods:
        for rsi_p in rsi_periods:
            for atr_m in atr_mults:
                eq, k, _ = strat_score_trader(
                    bb_period=bb, rsi_period=rsi_p,
                    atr_sl_mult=atr_m, track_per_asset=False)
                results.append({
                    "bb_period":      bb,
                    "rsi_period":     rsi_p,
                    "atr_sl_mult":    atr_m,
                    "Return%":        k["Return%"],
                    "Sharpe":         k["Sharpe"],
                    "MaxDD%":         k["MaxDD%"],
                    "Trades":         k["Trades"],
                    "WinRate%":       k["WinRate%"],
                })

    # Summary statistics
    rets    = [r["Return%"] for r in results]
    sharpes = [r["Sharpe"]  for r in results]
    summary = {
        "combinations_tested": len(results),
        "return_mean%":  round(np.mean(rets), 2),
        "return_std%":   round(np.std(rets), 2),
        "return_min%":   round(min(rets), 2),
        "return_max%":   round(max(rets), 2),
        "sharpe_mean":   round(np.mean(sharpes), 2),
        "sharpe_std":    round(np.std(sharpes), 2),
        "sharpe_min":    round(min(sharpes), 2),
        "sharpe_max":    round(max(sharpes), 2),
    }
    return {"grid_results": results, "summary": summary}


# -- Run all strategies ----------------------------------------------------
strategies = [
    ("Buy & Hold",    strat_buyhold),
    ("Crash Guard",   strat_crash_guard),
    ("Momentum",      strat_momentum),
    ("Adaptiv",       strat_adaptiv),
    ("Ensemble",      strat_ensemble),
]

results = {}
for name, func in strategies:
    print(f"  Running {name} ...")
    eq, k = func()
    results[name] = k

# Score Trader with per-asset tracking (Enhancement 1)
print("  Running Score Trader ...")
eq_st, k_st, per_asset_data = run_score_trader_per_asset()
results["Score Trader"] = k_st
results["score_trader_per_asset"] = per_asset_data

# Out-of-Sample test (Enhancement 2)
results["out_of_sample"] = run_out_of_sample()

# Parameter Sensitivity (Enhancement 4)
results["parameter_sensitivity"] = run_parameter_sensitivity()

# Meta
results["_meta"] = {
    "generated":   str(dt.date.today()),
    "assets":      len(ASSETS),
    "period_days": len(dates),
    "fees": ("Trading 212: 0.15% FX-Fee + 0.05% Spread + 0.10% Slippage "
             "= 0.30% pro Trade (EUR->USD)"),
    "enhancements": [
        "per-asset Score Trader analysis",
        "out-of-sample 7yr/3yr split",
        "slippage modelling (0.10%)",
        "parameter sensitivity (BB/RSI/ATR grid)",
    ],
}

with open("arena_backtest_results.json", "w") as f:
    json.dump(results, f, indent=2)

print("Done - arena_backtest_results.json written.")
