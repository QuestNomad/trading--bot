#!/usr/bin/env python3
"""Arena Backtest - 6 Strategien, 38 Assets, 10 Jahre retrospektiv
(inkl. Trading 212 Gebuehren + Spread + Slippage).

Enhancements v2:
1. Per-Asset Performance Analysis for Score Trader
2. Out-of-Sample Test (7yr train / 3yr test)
3. Slippage Modelling (0.10% on top of fees)
4. Parameter Sensitivity Test for Score Trader

Enhancements v3:
5. Walk-Forward Analysis (rolling 3yr train / 1yr test)
6. Monte Carlo Simulation (bootstrap drawdown analysis)
7. Kelly Criterion (position sizing)

Enhancements v4:
8. Max-Exposure Rule (80% portfolio cap)
9. Sector Correlation Filter (max 4 positions per sector)
"""

import json, datetime as dt, numpy as np, pandas as pd, yfinance as yf, pathlib, textwrap

# -- Trading 212 Gebuehren ---------------------------------------------------
TRADING_FEE  = 0.0015   # 0.15% FX-Fee pro Trade (Trading 212, EUR->USD)
SPREAD_COST  = 0.0005   # 0.05% Spread-Simulation pro Trade
SLIPPAGE_COST = 0.001   # 0.10% Slippage pro Trade (NEW)
TOTAL_COST = TRADING_FEE + SPREAD_COST + SLIPPAGE_COST  # 0.30% total

# -- Risk Management Constants -----------------------------------------------
MAX_EXPOSURE = 0.80          # Maximum 80% of portfolio in risk at any time
KELLY_FRACTION = 0.0694      # Half Kelly

SECTORS = {
    "Tech":          ["AAPL", "MSFT", "GOOGL", "NVDA", "META", "XLK", "ARKK", "QQQ", "AMD", "AVGO", "PLTR", "SMCI", "SHOP"],
    "Finance":       ["JPM", "V", "BAC", "XLF", "COIN", "SOFI", "NU"],
    "Consumer":      ["AMZN", "TSLA", "HD", "PG", "COST", "MELI"],
    "Health":        ["UNH", "JNJ", "XLV", "LLY", "NVO", "MRNA", "XBI"],
    "Broad_ETF":     ["SPY", "IWM", "DIA", "VTI"],
    "International": ["EFA", "EEM", "EWJ", "FXI", "EWT", "AAXJ", "EWZ", "INDA", "VGK"],
    "Energy":        ["XLE", "USO", "XOM", "FSLR", "URA"],
    "Telecom":       ["XLC"],
    "Crypto":        ["IBIT", "BITO", "MSTR", "MARA"],
    "Commodities":   ["GLD", "SLV", "DBA", "UNG"],
    "Bonds":         ["TLT", "LQD", "BND", "HYG"],
    "Semiconductor": ["TSM", "ASML"],
    "Volatile":      ["SE", "SMCI"],
}
MAX_POSITIONS_PER_SECTOR = 4

# Build reverse lookup: asset -> sector
ASSET_TO_SECTOR = {}
for sector, tickers in SECTORS.items():
    for t in tickers:
        ASSET_TO_SECTOR[t] = sector

# -- Assets ------------------------------------------------------------------
ASSETS = [
    # Index ETFs
    "SPY", "QQQ", "IWM", "DIA", "VTI",
    # International ETFs
    "EFA", "EEM", "VGK", "EWJ", "FXI", "EWT", "AAXJ", "EWZ", "INDA",
    # Sektor ETFs
    "XLE", "XLF", "XLV", "XLK", "XLI", "XLU", "XLP", "XLY", "XLRE", "XLC",
    "VNQ", "XBI", "ARKK",
    # Rohstoffe
    "GLD", "SLV", "UNG", "USO", "DBA", "URA",
    # Anleihen
    "TLT", "HYG", "LQD", "BND",
    # Crypto Proxy
    "IBIT", "BITO", "MSTR", "COIN", "MARA",
    # Tech Einzelaktien
    "AAPL", "NVDA", "MSFT", "TSLA", "AMZN", "META", "GOOGL",
    "AMD", "AVGO", "PLTR", "SMCI", "SHOP", "TSM", "ASML",
    # Volatile / High-Beta
    "SOFI", "MRNA", "FSLR", "SE", "NU", "MELI",
    # Health / Pharma
    "LLY", "NVO",
    # Konsum / Energie
    "COST", "XOM",
]

BENCH = "SPY"; VIX = "^VIX"; RF = 0.045; REBAL_DAYS = 5
end = dt.date.today(); start = end - dt.timedelta(days=10*365+30)

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
                    prev *= (1 - TOTAL_COST)        # Fee + Spread + Slippage: Kauf
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
                       atr_sl_mult=3.0, track_per_asset=False,
                       use_regime_filter=False):
    """Score Trader with configurable parameters.

    Enhancements v4:
    - Max-Exposure Rule: total exposure capped at MAX_EXPOSURE (80%).
      Each position sized at KELLY_FRACTION (6.94%), scaled down if needed.
    - Sector Correlation Filter: max MAX_POSITIONS_PER_SECTOR (4) per sector.

    Enhancement v5 (2026-04-24):
    - SMA200 Regime Filter (optional): block new BUY entries when
      SPY < SMA200 (risk_off == True). Exits bleiben unbetroffen.

    Args:
        date_range: tuple (start_idx, end_idx) to slice dates, or None for all
        bb_period: Bollinger Band period (default 20)
        rsi_period: RSI period (default 14)
        atr_sl_mult: ATR multiplier for stop-loss (default 3.0)
        track_per_asset: if True, collect per-asset statistics
        use_regime_filter: if True, skip BUY when SPY<SMA200
    """
    use_dates = dates[date_range[0]:date_range[1]] if date_range else dates
    vals  = [10000.0]; prev = 10000.0; positions = {}; trades = 0

    # Precompute indicators with configurable periods
    atr_ind = {}; rsi_ind = {}
    for a in ASSETS:
        h = close[a]
        delta = h.diff()
        gain = delta.clip(lower=0).rolling(rsi_period).mean()
        loss = (-delta.clip(upper=0)).rolling(rsi_period).mean()
        rsi_ind[a] = 100 - 100/(1 + gain/(loss+1e-9))
        atr_ind[a] = h.diff().abs().rolling(rsi_period).mean()

    # Per-asset tracking
    asset_stats = {a: {"trades": 0, "wins": 0, "returns": [],
                       "holding_days": []} for a in ASSETS} if track_per_asset else None
    asset_entry_day = {}   # ticker -> index of entry day

    # Risk management tracking (v4)
    rm_max_positions = 0
    rm_exposure_sum = 0.0
    rm_exposure_count = 0
    rm_sector_skips = 0
    rm_exposure_caps = 0
    rm_regime_skips = 0   # v5: BUY geblockt weil SPY<SMA200
    rm_sector_distribution = {s: 0 for s in SECTORS}   # total entries per sector

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
                score = 0
                if p > sma_bb:          score += 3
                if p < bb_mid + 0.5*bb_std: score += 3
                if rsi_ind[a].loc[d] < 55:  score += 2
                if score >= 8:
                    # --- SMA200 Regime Filter (v5) ---
                    if use_regime_filter and risk_off.loc[d]:
                        rm_regime_skips += 1
                        continue
                    # --- Sector Correlation Filter (v4) ---
                    sector = ASSET_TO_SECTOR.get(a, "Other")
                    sector_count = sum(
                        1 for pos_ticker in positions
                        if ASSET_TO_SECTOR.get(pos_ticker, "Other") == sector
                    )
                    if sector_count >= MAX_POSITIONS_PER_SECTOR:
                        rm_sector_skips += 1
                        continue

                    # --- Max Exposure Cap (v4) ---
                    current_exposure = len(positions) * KELLY_FRACTION
                    if current_exposure + KELLY_FRACTION > MAX_EXPOSURE:
                        rm_exposure_caps += 1
                        continue

                    atr = atr_ind[a].loc[d]
                    n_pos = max(len(positions) + 1, 1)
                    prev *= (1 - TOTAL_COST / n_pos)   # Fee + Spread + Slippage (anteilig)
                    positions[a] = (p, p - atr_sl_mult*atr, atr, p)
                    trades += 1

                    # Track sector distribution
                    if sector in rm_sector_distribution:
                        rm_sector_distribution[sector] += 1
                    else:
                        rm_sector_distribution[sector] = 1

                    if track_per_asset:
                        asset_stats[a]["trades"] += 1   # entry counted
                        asset_entry_day[a] = i
            except:
                pass

        # -- Position sizing with Max-Exposure cap (v4) ---
        n_pos = len(positions)
        if n_pos > 0:
            raw_exposure = KELLY_FRACTION * n_pos
            if raw_exposure > MAX_EXPOSURE:
                position_size = MAX_EXPOSURE / n_pos
            else:
                position_size = KELLY_FRACTION
            r = sum(ret.loc[d, a] * position_size for a in positions)

            # Track risk management stats
            actual_exposure = position_size * n_pos
            rm_exposure_sum += actual_exposure
            rm_exposure_count += 1
            rm_max_positions = max(rm_max_positions, n_pos)
        else:
            r = 0.0
            rm_exposure_sum += 0.0
            rm_exposure_count += 1

        prev *= (1 + r); vals.append(prev)

    eq = pd.Series(vals[1:], index=use_dates)
    win = sum(1 for v1, v2 in zip(vals[:-1], vals[1:]) if v2 > v1)
    wr  = round(win / len(use_dates) * 100, 1)
    k   = kpi(eq, trades); k["WinRate%"] = wr

    # Close any still-open positions for per-asset stats
    if track_per_asset:
        for a in list(positions):
            entry = positions[a][0]
            p = close[a].iloc[-1]
            pnl = (p - entry) / entry
            asset_stats[a]["returns"].append(pnl)
            if pnl > 0:
                asset_stats[a]["wins"] += 1
            if a in asset_entry_day:
                asset_stats[a]["holding_days"].append(len(use_dates) - asset_entry_day[a])

    # Build risk management summary (v4)
    risk_management = {
        "max_simultaneous_positions": rm_max_positions,
        "average_exposure%": round(
            (rm_exposure_sum / rm_exposure_count * 100) if rm_exposure_count > 0 else 0.0, 2
        ),
        "max_exposure_cap%": MAX_EXPOSURE * 100,
        "kelly_fraction%": KELLY_FRACTION * 100,
        "exposure_cap_triggers": rm_exposure_caps,
        "sector_filter_skips": rm_sector_skips,
        "regime_filter_skips": rm_regime_skips,
        "regime_filter_active": use_regime_filter,
        "sector_distribution": rm_sector_distribution,
        "max_positions_per_sector": MAX_POSITIONS_PER_SECTOR,
    }

    return eq, k, asset_stats, risk_management


def strat_adaptiv():
    """Adaptiv: VIX-basierter Moduswechsel (Momentum/Crash Guard/Cash) mit Hysterese."""
    vix_close = close[VIX] if VIX in close.columns else pd.Series(20, index=close.index)
    vals = [10000.0]; prev = 10000.0; trades = 0; modus = "momentum"

    for i, d in enumerate(dates):
        vix = vix_close.loc[d] if d in vix_close.index else 20
        # Modus bestimmen mit Hysterese
        modus_alt = modus
        if vix > 30:
            modus = "cash"
        elif vix > 20:
            modus = "crash_guard"
        elif vix < 18 or modus_alt == "momentum":
            modus = "momentum"
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
        else:   # momentum
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
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rsi14[a] = 100 - 100/(1 + gain/(loss+1e-9))
        atr14[a] = h.diff().abs().rolling(14).mean()
        sma20_all[a] = h.rolling(20).mean()
        sma200_all[a]= h.rolling(200).mean()
        mom63[a]     = h.pct_change(63)

    for i, d in enumerate(dates):
        for a in list(positions.keys()):
            try:
                p = close[a].loc[d]
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
                s20 = sma20_all[a].loc[d]
                rsi_val = rsi14[a].loc[d]
                score = 0
                if not np.isnan(s20) and p > s20: score += 2
                if not np.isnan(rsi_val):
                    if rsi_val < 35: score += 2
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
    eq = pd.Series(vals[1:], index=dates)
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
    eq, k, asset_stats, risk_mgmt = strat_score_trader(track_per_asset=True)

    per_asset = {}
    for a in ASSETS:
        s = asset_stats[a]
        n_trades = s["trades"]
        returns  = s["returns"]
        wins     = s["wins"]
        holdings = s["holding_days"]
        per_asset[a] = {
            "n_trades":        n_trades,
            "total_return%":   round(sum(returns) * 100, 2) if returns else 0.0,
            "avg_return%":     round(np.mean(returns) * 100, 2) if returns else 0.0,
            "win_rate%":       round(wins / max(n_trades, 1) * 100, 1),
            "avg_holding_days": round(np.mean(holdings), 1) if holdings else 0.0,
        }
    return eq, k, per_asset, risk_mgmt


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
    eq_train, k_train, _, _ = strat_score_trader(
        date_range=(train_start, train_end), track_per_asset=False)
    # Test period
    eq_test, k_test, _, _ = strat_score_trader(
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

    bb_periods  = [18, 20, 22]
    rsi_periods = [12, 14, 16]
    atr_mults   = [2.5, 3.0, 3.5]

    results = []
    for bb in bb_periods:
        for rsi_p in rsi_periods:
            for atr_m in atr_mults:
                eq, k, _, _ = strat_score_trader(
                    bb_period=bb, rsi_period=rsi_p, atr_sl_mult=atr_m,
                    track_per_asset=False)
                results.append({
                    "bb_period": bb, "rsi_period": rsi_p, "atr_sl_mult": atr_m,
                    "Return%": k["Return%"], "Sharpe": k["Sharpe"],
                    "MaxDD%": k["MaxDD%"], "Trades": k["Trades"],
                    "WinRate%": k["WinRate%"],
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


# ============================================================================
# ENHANCEMENT 5: Walk-Forward Analysis
# ============================================================================
def walk_forward_analysis():
    """Rolling 3yr train / 1yr test windows for Score Trader.

    Splits the full date range into overlapping windows:
    - Window 0: years 0-3 train, year 3-4 test
    - Window 1: years 1-4 train, year 4-5 test
    - etc.

    Runs Score Trader on each train period to validate, then measures on test.
    Reports consistency of performance across windows.
    """
    print("  Running Walk-Forward Analysis ...")

    total_days = len(dates)
    trading_days_per_year = 252
    train_len   = 3 * trading_days_per_year   # 3 years
    test_len    = 1 * trading_days_per_year    # 1 year
    window_step = 1 * trading_days_per_year    # slide by 1 year

    windows = []
    start_idx = 0

    while start_idx + train_len + test_len <= total_days:
        train_start = start_idx
        train_end   = start_idx + train_len
        test_start  = train_end
        test_end    = min(train_end + test_len, total_days)

        # Run Score Trader on train window
        eq_train, k_train, _, _ = strat_score_trader(
            date_range=(train_start, train_end), track_per_asset=False)

        # Run Score Trader on test window
        eq_test, k_test, _, _ = strat_score_trader(
            date_range=(test_start, test_end), track_per_asset=False)

        windows.append({
            "window": len(windows) + 1,
            "train_start": str(dates[train_start]),
            "train_end":   str(dates[train_end - 1]),
            "test_start":  str(dates[test_start]),
            "test_end":    str(dates[test_end - 1]),
            "train_return%": k_train["Return%"],
            "test_return%":  k_test["Return%"],
            "train_sharpe":  k_train["Sharpe"],
            "test_sharpe":   k_test["Sharpe"],
            "train_maxdd%":  k_train["MaxDD%"],
            "test_maxdd%":   k_test["MaxDD%"],
            "train_trades":  k_train["Trades"],
            "test_trades":   k_test["Trades"],
        })
        start_idx += window_step

    # Aggregate statistics across all windows
    if windows:
        train_returns = [w["train_return%"] for w in windows]
        test_returns  = [w["test_return%"]  for w in windows]
        train_sharpes = [w["train_sharpe"]  for w in windows]
        test_sharpes  = [w["test_sharpe"]   for w in windows]

        # Consistency: how often does test period remain profitable?
        profitable_tests = sum(1 for r in test_returns if r > 0)

        summary = {
            "n_windows": len(windows),
            "train_return_mean%":  round(np.mean(train_returns), 2),
            "train_return_std%":   round(np.std(train_returns), 2),
            "test_return_mean%":   round(np.mean(test_returns), 2),
            "test_return_std%":    round(np.std(test_returns), 2),
            "test_profitable_pct%": round(profitable_tests / len(windows) * 100, 1),
            "train_sharpe_mean":   round(np.mean(train_sharpes), 2),
            "test_sharpe_mean":    round(np.mean(test_sharpes), 2),
            "avg_return_degradation%": round(
                np.mean(train_returns) - np.mean(test_returns), 2),
        }
    else:
        summary = {"n_windows": 0, "error": "Not enough data for walk-forward"}

    return {"windows": windows, "summary": summary}


# ============================================================================
# ENHANCEMENT 6: Monte Carlo Simulation
# ============================================================================
def monte_carlo_simulation(n_sims=1000):
    """Bootstrap shuffle of daily returns from Score Trader.

    Randomly reshuffles the daily return sequence 1000 times to build a
    distribution of possible outcomes. For each simulation:
    - Compute total return and max drawdown

    Reports median, 5th, and 95th percentile for drawdowns and returns,
    plus probability of experiencing >20% and >30% drawdowns.

    Uses TOTAL_COST (0.30%) applied proportionally in the base equity curve.
    """
    print("  Running Monte Carlo Simulation (n={}) ...".format(n_sims))

    # Get the Score Trader equity curve and extract daily returns
    eq_st, _, _, _ = strat_score_trader(track_per_asset=False)
    daily_returns = eq_st.pct_change().dropna().values.copy()
    n_days = len(daily_returns)

    sim_total_returns  = []
    sim_max_drawdowns  = []
    sim_final_equity   = []

    rng = np.random.RandomState(42)   # reproducible

    for _ in range(n_sims):
        # Bootstrap: shuffle daily returns (preserves return distribution,
        # destroys autocorrelation to test path-dependency)
        shuffled = daily_returns.copy()
        rng.shuffle(shuffled)

        # Build equity curve from shuffled returns
        equity = np.empty(n_days + 1)
        equity[0] = 10000.0
        for j in range(n_days):
            equity[j + 1] = equity[j] * (1 + shuffled[j])

        # Total return
        total_ret = (equity[-1] / equity[0]) - 1.0
        sim_total_returns.append(total_ret)
        sim_final_equity.append(equity[-1])

        # Max drawdown
        running_max = np.maximum.accumulate(equity)
        drawdowns   = (equity - running_max) / running_max
        sim_max_drawdowns.append(drawdowns.min())

    sim_total_returns = np.array(sim_total_returns)
    sim_max_drawdowns = np.array(sim_max_drawdowns)
    sim_final_equity  = np.array(sim_final_equity)

    result = {
        "n_simulations": n_sims,
        "n_days_per_sim": n_days,
        "total_return": {
            "median%":       round(np.median(sim_total_returns) * 100, 2),
            "percentile_5%": round(np.percentile(sim_total_returns, 5) * 100, 2),
            "percentile_95%":round(np.percentile(sim_total_returns, 95) * 100, 2),
            "mean%":         round(np.mean(sim_total_returns) * 100, 2),
            "std%":          round(np.std(sim_total_returns) * 100, 2),
        },
        "max_drawdown": {
            "median%":       round(np.median(sim_max_drawdowns) * 100, 2),
            "percentile_5%": round(np.percentile(sim_max_drawdowns, 5) * 100, 2),
            "percentile_95%":round(np.percentile(sim_max_drawdowns, 95) * 100, 2),
            "mean%":         round(np.mean(sim_max_drawdowns) * 100, 2),
        },
        "drawdown_probabilities": {
            "prob_gt_20%": round( np.mean(sim_max_drawdowns < -0.20) * 100, 1),
            "prob_gt_30%": round( np.mean(sim_max_drawdowns < -0.30) * 100, 1),
            "prob_gt_40%": round( np.mean(sim_max_drawdowns < -0.40) * 100, 1),
        },
        "final_equity": {
            "median":        round(float(np.median(sim_final_equity)), 2),
            "percentile_5":  round(float(np.percentile(sim_final_equity, 5)), 2),
            "percentile_95": round(float(np.percentile(sim_final_equity, 95)), 2),
        },
    }
    return result


# ============================================================================
# ENHANCEMENT 7: Kelly Criterion
# ============================================================================
def kelly_criterion():
    """Compute Kelly fraction and position sizing for Score Trader.

    Uses actual trade-level win rate and average win/loss from per-asset analysis.
    Calculates:
    - Full Kelly fraction (f*)
    - Half Kelly and Quarter Kelly (conservative sizing)
    - Theoretical annual return estimates at each Kelly fraction
    - Risk of ruin estimate

    Formula: f* = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win

    Uses TOTAL_COST (0.30%) deducted from each trade's P&L.
    """
    print("  Running Kelly Criterion analysis ...")

    # Run Score Trader with per-asset tracking to get trade-level data
    eq_st, k_st, asset_stats, _ = strat_score_trader(track_per_asset=True)

    # Collect all individual trade returns across all assets
    all_returns = []
    for a in ASSETS:
        for r in asset_stats[a]["returns"]:
            # Each trade return already reflects market movement;
            # additionally deduct TOTAL_COST for round-trip cost
            net_return = r - TOTAL_COST
            all_returns.append(net_return)

    if not all_returns:
        return {"error": "No trades found for Kelly calculation"}

    all_returns = np.array(all_returns)
    wins   = all_returns[all_returns > 0]
    losses = all_returns[all_returns <= 0]

    n_trades = len(all_returns)
    n_wins   = len(wins)
    n_losses = len(losses)

    win_rate = n_wins / n_trades if n_trades > 0 else 0.0
    avg_win  = float(np.mean(wins))  if len(wins) > 0  else 0.0
    avg_loss = float(np.mean(np.abs(losses))) if len(losses) > 0 else 0.001

    # Kelly formula: f* = (p * b - q) / b
    # where p = win_rate, q = 1 - win_rate, b = avg_win / avg_loss
    if avg_win > 0 and avg_loss > 0:
        b = avg_win / avg_loss   # win/loss ratio
        kelly_full = (win_rate * b - (1 - win_rate)) / b
    else:
        b = 0.0
        kelly_full = 0.0

    kelly_half    = kelly_full / 2.0
    kelly_quarter = kelly_full / 4.0

    # Theoretical geometric growth rate: g = p * ln(1 + f*b) + q * ln(1 - f)
    def growth_rate(f, p, b_ratio):
        """Geometric growth rate per trade at fraction f."""
        if f <= 0 or f >= 1:
            return 0.0
        q = 1 - p
        try:
            g = p * np.log(1 + f * b_ratio) + q * np.log(1 - f)
            return g
        except:
            return 0.0

    # Estimate trades per year from actual data
    total_period_years = len(dates) / 252.0
    trades_per_year = k_st["Trades"] / total_period_years if total_period_years > 0 else 50

    # Annual growth estimates at each Kelly level
    g_full    = growth_rate(max(kelly_full, 0),    win_rate, b)
    g_half    = growth_rate(max(kelly_half, 0),    win_rate, b)
    g_quarter = growth_rate(max(kelly_quarter, 0), win_rate, b)

    annual_g_full    = g_full * trades_per_year
    annual_g_half    = g_half * trades_per_year
    annual_g_quarter = g_quarter * trades_per_year

    # Risk of ruin estimate (simplified): P(ruin) ~ ((1-p)/p)^(bankroll_units)
    # Using a more practical estimate based on consecutive losses
    max_consecutive_losses = 0
    current_streak = 0
    for r in all_returns:
        if r <= 0:
            current_streak += 1
            max_consecutive_losses = max(max_consecutive_losses, current_streak)
        else:
            current_streak = 0

    result = {
        "trade_statistics": {
            "total_trades": n_trades,
            "wins": n_wins,
            "losses": n_losses,
            "win_rate%": round(win_rate * 100, 2),
            "avg_win%": round(avg_win * 100, 2),
            "avg_loss%": round(avg_loss * 100, 2),
            "win_loss_ratio": round(b, 3),
            "expectancy%": round((win_rate * avg_win - (1 - win_rate) * avg_loss) * 100, 3),
            "max_consecutive_losses": max_consecutive_losses,
        },
        "kelly_fractions": {
            "full_kelly%":    round(kelly_full * 100, 2),
            "half_kelly%":    round(kelly_half * 100, 2),
            "quarter_kelly%": round(kelly_quarter * 100, 2),
        },
        "theoretical_annual_growth": {
            "full_kelly%":    round(annual_g_full * 100, 2),
            "half_kelly%":    round(annual_g_half * 100, 2),
            "quarter_kelly%": round(annual_g_quarter * 100, 2),
        },
        "position_sizing": {
            "recommended": "half_kelly",
            "recommended_pct%": round(kelly_half * 100, 2),
            "rationale": ("Half Kelly balances growth vs. drawdown risk. "
                         "Full Kelly is mathematically optimal but assumes "
                         "perfect edge estimation and infinite time horizon."),
            "trades_per_year": round(trades_per_year, 1),
        },
        "cost_assumptions": {
            "total_cost_per_trade%": round(TOTAL_COST * 100, 2),
            "breakdown": "Trading 212: 0.15% FX + 0.05% Spread + 0.10% Slippage",
        },
    }
    return result


# -- Run all strategies ----------------------------------------------------
strategies = [
    ("Buy & Hold",   strat_buyhold),
    ("Crash Guard",  strat_crash_guard),
    ("Momentum",     strat_momentum),
    ("Adaptiv",      strat_adaptiv),
    ("Ensemble",     strat_ensemble),
]

results = {}
for name, func in strategies:
    print(f"  Running {name} ...")
    eq, k = func()
    results[name] = k

# Score Trader with per-asset tracking (Enhancement 1) + risk management (v4)
print("  Running Score Trader ...")
eq_st, k_st, per_asset_data, risk_mgmt_data = run_score_trader_per_asset()
results["Score Trader"] = k_st
results["score_trader_per_asset"] = per_asset_data
results["risk_management"] = risk_mgmt_data

# Score Trader + SMA200 Regime Filter (v5) - direkter A/B-Vergleich
print("  Running Score+Regime (SMA200 Filter) ...")
eq_sr, k_sr, _, risk_mgmt_sr = strat_score_trader(use_regime_filter=True)
results["Score+Regime"] = k_sr
results["score_regime_risk_management"] = risk_mgmt_sr
results["regime_filter_impact"] = {
    "score_trader": {
        "return%":  k_st.get("Return%"),
        "max_dd%":  k_st.get("MaxDD%"),
        "sharpe":   k_st.get("Sharpe"),
        "win_rate%": k_st.get("WinRate%"),
    },
    "score_regime": {
        "return%":  k_sr.get("Return%"),
        "max_dd%":  k_sr.get("MaxDD%"),
        "sharpe":   k_sr.get("Sharpe"),
        "win_rate%": k_sr.get("WinRate%"),
    },
    "buy_signals_blocked_by_regime": risk_mgmt_sr.get("regime_filter_skips"),
    "interpretation": (
        "Vergleiche Return, MaxDD und Sharpe. Regime-Filter sollte MaxDD "
        "senken bei moderatem Rendite-Verlust (oder besser gleich). "
        "Wenn Sharpe steigt -> besseres Risiko/Rendite-Verhaeltnis."
    ),
}

# Out-of-Sample test (Enhancement 2)
results["out_of_sample"] = run_out_of_sample()

# Parameter Sensitivity (Enhancement 4)
results["parameter_sensitivity"] = run_parameter_sensitivity()

# Walk-Forward Analysis (Enhancement 5)
results["walk_forward"] = walk_forward_analysis()

# Monte Carlo Simulation (Enhancement 6)
results["monte_carlo"] = monte_carlo_simulation(n_sims=1000)

# Kelly Criterion (Enhancement 7)
results["kelly_criterion"] = kelly_criterion()

# Meta
results["_meta"] = {
    "generated":  str(dt.date.today()),
    "assets":     len(ASSETS),
    "period_days": len(dates),
    "fees": ("Trading 212: 0.15% FX-Fee + 0.05% Spread + 0.10% Slippage "
             "= 0.30% pro Trade (EUR->USD)"),
    "enhancements": [
        "per-asset Score Trader analysis",
        "out-of-sample 7yr/3yr split",
        "slippage modelling (0.10%)",
        "parameter sensitivity (BB/RSI/ATR grid)",
        "walk-forward analysis (3yr train / 1yr test rolling windows)",
        "Monte Carlo simulation (1000 bootstrap reshuffles)",
        "Kelly criterion (position sizing + growth estimates)",
        "max-exposure rule (80% portfolio cap with Half Kelly sizing)",
        "sector correlation filter (max 4 positions per sector)",
        "SMA200 regime filter A/B (Score Trader vs Score+Regime)",
    ],
}

with open("arena_backtest_results.json", "w") as f:
    json.dump(results, f, indent=2)

print("Done - arena_backtest_results.json written.")
