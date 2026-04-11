#!/usr/bin/env python3
"""Arena Backtest - 5 Strategien, 38 Assets, 2 Jahre retrospektiv."""
import json, datetime as dt, numpy as np, pandas as pd, yfinance as yf, pathlib, textwrap

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
    vals = [10000.0]; prev = 10000.0
    for d in dates:
        r = ret.loc[d, BENCH] if not risk_off.loc[d] else 0.0
        prev *= (1 + r); vals.append(prev)
    eq = pd.Series(vals[1:], index=dates)
    switches = (risk_off.loc[dates].astype(int).diff().abs().sum())
    return eq, kpi(eq, int(switches))

def strat_momentum():
    vals = [10000.0]; prev = 10000.0; held = []; trades = 0
    for i, d in enumerate(dates):
        if i % REBAL_DAYS == 0:
            if risk_off.loc[d]:
                if held: trades += len(held)
                held = []
            else:
                mom = close[ASSETS].loc[:d].pct_change(63).iloc[-1].nlargest(10).index.tolist()
                if set(mom) != set(held): trades += len(mom)
                held = mom
        if held:
            r = ret.loc[d, held].mean()
        else:
            r = 0.0
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
                    positions[a] = (p, p - 3*atr, p + 8*atr); trades += 1
            except: pass
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
                trades += len(mom)
            if 'mom' in dir() and mom:
                r = ret.loc[d, mom].mean()
            else:
                r = 0.0

        prev *= (1 + r); vals.append(prev)
    eq = pd.Series(vals[1:], index=dates)
    return eq, kpi(eq, trades)


# -- Ausfuehrung ------------------------------------------------------------
print("Running strategies ...")
results = {}
for name, fn in [("Buy & Hold", strat_buyhold), ("Crash Guard", strat_crash_guard),
                  ("Momentum", strat_momentum), ("Score Trader", strat_score_trader),
                  ("Adaptiv", strat_adaptiv)]:
    eq, k = fn()
    results[name] = {"equity": eq, "kpi": k}
    print(f"  {name}: {k}")

# -- JSON --------------------------------------------------------------------
out = {name: v["kpi"] for name, v in results.items()}
out["_meta"] = {"generated": str(dt.date.today()), "assets": len(ASSETS), "period_days": len(dates)}
pathlib.Path("arena_backtest_results.json").write_text(json.dumps(out, indent=2))

# -- HTML Dashboard --------------------------------------------------------
colors = ["#2563eb","#dc2626","#16a34a","#f59e0b","#8b5cf6"]
equity_datasets = []
for i, (name, v) in enumerate(results.items()):
    eq = v["equity"]
    sampled = eq.iloc[::5]
    equity_datasets.append(f'{{label:"{name}",data:{json.dumps([round(x,0) for x in sampled.values.tolist()])},borderColor:"{colors[i]}",fill:false,tension:0.3,pointRadius:0}}')
labels_eq = json.dumps([str(d.date()) for d in results["Buy & Hold"]["equity"].iloc[::5].index])

dd_datasets = []
for i, (name, v) in enumerate(results.items()):
    eq = v["equity"]; peak = eq.cummax(); dd = ((eq-peak)/peak*100)
    sampled = dd.iloc[::5]
    dd_datasets.append(f'{{label:"{name}",data:{json.dumps([round(x,2) for x in sampled.values.tolist()])},borderColor:"{colors[i]}",fill:false,tension:0.3,pointRadius:0}}')

rows = ""
ranked = sorted(results.items(), key=lambda x: x[1]["kpi"]["Return%"], reverse=True)
for rank, (name, v) in enumerate(ranked, 1):
    k = v["kpi"]
    wr = k.get("WinRate%", "-")
    rows += f"<tr><td>{rank}</td><td><b>{name}</b></td><td>{k['Return%']}%</td><td>{k['Sharpe']}</td><td>{k['MaxDD%']}%</td><td>{wr}</td><td>{k['Trades']}</td></tr>"

html = textwrap.dedent(f"""\
<!DOCTYPE html><html><head><meta charset="utf-8"><title>Arena Backtest Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>body{{font-family:system-ui;margin:20px;background:#0f172a;color:#e2e8f0}}
h1{{text-align:center}}table{{border-collapse:collapse;width:100%;margin:20px 0}}
th,td{{border:1px solid #334155;padding:8px;text-align:center}}th{{background:#1e293b}}
.chart-box{{background:#1e293b;border-radius:12px;padding:16px;margin:20px 0}}
canvas{{max-height:350px}}</style></head><body>
<h1>Arena Backtest Dashboard</h1>
<p style="text-align:center">{len(ASSETS)} Assets | {len(dates)} Trading Days | Generated {dt.date.today()}</p>
<table><tr><th>#</th><th>Strategy</th><th>Return</th><th>Sharpe</th><th>Max DD</th><th>Win Rate</th><th>Trades</th></tr>{rows}</table>
<div class="chart-box"><canvas id="eq"></canvas></div>
<div class="chart-box"><canvas id="dd"></canvas></div>
<script>
new Chart(document.getElementById("eq"),{{type:"line",data:{{labels:{labels_eq},datasets:[{",".join(equity_datasets)}]}},options:{{plugins:{{title:{{display:true,text:"Equity Curves",color:"#e2e8f0"}}}},scales:{{x:{{display:false}},y:{{ticks:{{color:"#94a3b8"}}}}}}}}}});
new Chart(document.getElementById("dd"),{{type:"line",data:{{labels:{labels_eq},datasets:[{",".join(dd_datasets)}]}},options:{{plugins:{{title:{{display:true,text:"Drawdown %",color:"#e2e8f0"}}}},scales:{{x:{{display:false}},y:{{ticks:{{color:"#94a3b8"}}}}}}}}}});
</script></body></html>""")
pathlib.Path("arena_backtest_dashboard.html").write_text(html)
print("Done - arena_backtest_results.json + arena_backtest_dashboard.html written.")
