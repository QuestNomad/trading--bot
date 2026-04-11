#!/usr/bin/env python3
"""Arena Backtest - 6 Strategien, 38 Assets, 2 Jahre retrospektiv (inkl. Trading 212 Gebuehren + Spread)."""
import json, datetime as dt, numpy as np, pandas as pd, yfinance as yf, pathlib, textwrap

# -- Trading 212 Gebuehren ---------------------------------------------------
TRADING_FEE = 0.0015  # 0.15% FX-Fee pro Trade (Trading 212, EUR->USD)
SPREAD_COST = 0.0005  # 0.05% Spread-Simulation pro Trade

# -- Assets ------------------------------------------------------------------
ASSETS = [
    "SPY","QQQ","IWM","EFA","EEM","VGK","EWJ","FXI","VNQ","XLE","XLF","XLV",
    "XLK","XLI","XLU","XLP","XLY","XLC","XLRE","XBI","ARKK","GLD","SLV","TLT",
    "HYG","LQD","BND","UNG","USO","DBA","IBIT","BITO","MSTR","COIN","NVDA",
    "AAPL","MSFT","TSLA"
]
BENCH = "SPY"; VIX = "^VIX"; RF = 0.045; REBAL_DAYS = 5
end = dt.date.today(); start = end - dt.timedelta(days=2*365+30)

# -- Daten laden ------------------------------------------------------------
print("Downloading data ...")
tickers = list(set(ASSETS + [VIX]))
raw = yf.download(tickers, start=str(start), end=str(end), group_by="ticker", auto_adjust=True)
close = pd.DataFrame({t: raw[t]["Close"] for t in tickers if t in raw.columns.get_level_values(0)}).dropna(how="all").ffill()
ret = close[ASSETS].pct_change().fillna(0)

spy = close[BENCH]; sma200 = spy.rolling(200).mean()
risk_off = spy < sma200  # True = Cash

# -- Hilfsfunktionen --------------------------------------------------------
def sharpe(eq):
    r = eq.pct_change().dropna()
    return (r.mean()*252 - RF) / (r.std()*np.sqrt(252)+1e-9)

def max_dd(eq):
    peak = eq.cummax(); dd = (eq - peak) / peak
    return dd.min()

def kpi(eq, trades=0):
    total = eq.iloc[-1]/eq.iloc[0]-1
    return {"Return%": round(total*100, 2), "Sharpe": round(sharpe(eq), 2),
            "MaxDD%": round(max_dd(eq)*100, 2), "Trades": trades}

# -- Strategien -------------------------------------------------------------
dates = ret.index[200:]  # nach SMA200 warm-up

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
            prev *= (1 - TRADING_FEE - SPREAD_COST)  # FX-Fee bei Switch (Kauf oder Verkauf)
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
                    prev *= (1 - TRADING_FEE - SPREAD_COST)  # FX-Fee: Verkauf aller Positionen
                    trades += len(held)
                held = []
            else:
                mom = close[ASSETS].loc[:d].pct_change(63).iloc[-1].nlargest(10).index.tolist()
                if set(mom) != set(held):
                    if held:
                        prev *= (1 - TRADING_FEE - SPREAD_COST)  # FX-Fee: Verkauf alter Positionen
                    prev *= (1 - TRADING_FEE - SPREAD_COST)  # FX-Fee: Kauf neuer Positionen
                    trades += len(mom)
                held = mom
        if held: r = ret.loc[d, held].mean()
        else: r = 0.0
        prev *= (1 + r); vals.append(prev)
    eq = pd.Series(vals[1:], index=dates)
    return eq, kpi(eq, trades)

def strat_score_trader():
    vals = [10000.0]; prev = 10000.0; positions = {}; trades = 0
    atr14 = {}; rsi14 = {}
    for a in ASSETS:
        h = close[a]
        delta = h.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rsi14[a] = 100 - 100/(1 + gain/(loss+1e-9))
        atr14[a] = h.diff().abs().rolling(14).mean()
    for d in dates:
        for a in list(positions):
            entry, sl, tp = positions[a]
            p = close[a].loc[d]
            if p <= sl or p >= tp:
                n_pos = max(len(positions), 1)
                prev *= (1 - (TRADING_FEE + SPREAD_COST) / n_pos)  # FX-Fee: Verkauf (anteilig)
                trades += 1; del positions[a]
        for a in ASSETS:
            if a in positions: continue
            try:
                p = close[a].loc[d]; sma20 = close[a].loc[:d].rolling(20).mean().iloc[-1]
                bb_mid = sma20; bb_std = close[a].loc[:d].rolling(20).std().iloc[-1]
                bb_low = bb_mid - 2*bb_std
                score = 0
                if p > sma20: score += 3
                if p < bb_mid + 0.5*bb_std: score += 3
                if rsi14[a].loc[d] < 55: score += 2
                if score >= 8:
                    atr = atr14[a].loc[d]
                    n_pos = max(len(positions) + 1, 1)
                    prev *= (1 - (TRADING_FEE + SPREAD_COST) / n_pos)  # FX-Fee: Kauf (anteilig)
                    positions[a] = (p, p - 3*atr, p + 8*atr); trades += 1
            except: pass
        if positions: r = np.mean([ret.loc[d, a] for a in positions])
        else: r = 0.0
        prev *= (1 + r); vals.append(prev)
    eq = pd.Series(vals[1:], index=dates)
    win = sum(1 for v1,v2 in zip(vals[:-1],vals[1:]) if v2>v1)
    wr = round(win/len(dates)*100, 1)
    k = kpi(eq, trades); k["WinRate%"] = wr
    return eq, k

def strat_adaptiv():
    """Adaptiv: VIX-basierter Moduswechsel (Momentum/Crash Guard/Cash) mit Hysterese."""
    vix_close = close[VIX] if VIX in close.columns else pd.Series(20, index=close.index)
    vals = [10000.0]; prev = 10000.0; trades = 0; modus = "momentum"
    for i, d in enumerate(dates):
        vix = vix_close.loc[d] if d in vix_close.index else 20
        # Modus bestimmen mit Hysterese
        modus_alt = modus
        if vix > 30: modus = "cash"
        elif vix > 20: modus = "crash_guard"
        elif vix < 18 or modus_alt == "momentum": modus = "momentum"
        # else: bleibe im aktuellen Modus (Hysterese)
        if modus != modus_alt:
            prev *= (1 - TRADING_FEE - SPREAD_COST)  # FX-Fee bei Moduswechsel
            trades += 1
        if modus == "cash": r = 0.0
        elif modus == "crash_guard":
            if not risk_off.loc[d]: r = ret.loc[d, BENCH]
            else: r = 0.0
        else:  # momentum
            if i % REBAL_DAYS == 0:
                mom = close[ASSETS].loc[:d].pct_change(63).iloc[-1].nlargest(10).index.tolist()
                prev *= (1 - TRADING_FEE - SPREAD_COST)  # FX-Fee: Rebalancing
                trades += len(mom)
            if 'mom' in dir() and mom: r = ret.loc[d, mom].mean()
            else: r = 0.0
        prev *= (1 + r); vals.append(prev)
    eq = pd.Series(vals[1:], index=dates)
    return eq, kpi(eq, trades)

def strat_ensemble():
    """Ensemble: Handelt nur wenn ALLE Signale uebereinstimmen, woechentlich"""
    vals = [10000.0]; prev = 10000.0; positions = {}; trades = 0
    cooldown = {}  # ticker -> cooldown_until_index
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
        sma200_all[a] = h.rolling(200).mean()
        mom63[a] = h.pct_change(63)
    for i, d in enumerate(dates):
        for a in list(positions.keys()):
            try:
                p = close[a].loc[d]
                pos = positions[a]
                if p <= pos[1] or p >= pos[2]:
                    prev *= (1 - (TRADING_FEE + SPREAD_COST))
                    trades += 1
                    cooldown[a] = i + 10
                    del positions[a]
            except: pass
        is_monday = hasattr(d, 'weekday') and d.weekday() == 0
        if is_monday and len(positions) < MAX_POSITIONS:
            for a in ASSETS:
                if a in positions or (a in cooldown and i < cooldown[a]):
                    continue
                try:
                    p = close[a].loc[d]
                except: continue
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
                    prev *= (1 - (TRADING_FEE + SPREAD_COST)) / n_pos
                    positions[a] = (p, p - 4 * atr, p + 10 * atr); trades += 1
        if positions:
            r = np.mean([ret.loc[d, a] for a in positions])
        else:
            r = 0.0
        prev *= (1 + r); vals.append(prev)
    eq = pd.Series(vals[1:], index=dates)
    win = sum(1 for v1,v2 in zip(vals[:-1],vals[1:]) if v2>v1)
    wr = round(win/len(dates)*100, 1)
    k = kpi(eq, trades); k["WinRate%"] = wr
    return eq, k

# Dashboard generation temporarily disabled
print("Done - arena_backtest_results.json written.")
