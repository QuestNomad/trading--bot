import os
import pandas as pd
import numpy as np
import yfinance as yf
import requests
from datetime import datetime

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
KAPITAL          = 10000
PERIODE          = "2y"

ASSETS = [
    {"name": "Bitcoin",     "id": "BTC-EUR"},
    {"name": "Ethereum",    "id": "ETH-EUR"},
    {"name": "S&P 500",     "id": "SPY"},
    {"name": "Apple",       "id": "AAPL"},
    {"name": "Nvidia",      "id": "NVDA"},
    {"name": "Tesla",       "id": "TSLA"},
    {"name": "Microsoft",   "id": "MSFT"},
    {"name": "Gold",        "id": "GC=F"},
    {"name": "Silber",      "id": "SI=F"},
    {"name": "Amazon",      "id": "AMZN"},
    {"name": "Meta",        "id": "META"},
    {"name": "Google",      "id": "GOOGL"},
    {"name": "Rheinmetall", "id": "RHM.DE"},
    {"name": "Airbus",      "id": "AIR.DE"},
]

PARAMETER_SETS = [
    {"name": "Original",   "kauf": 8, "verk": 3, "sl": 2, "tp": 4},
    {"name": "Aggressiv",  "kauf": 7, "verk": 3, "sl": 2, "tp": 6},
    {"name": "Locker",     "kauf": 7, "verk": 4, "sl": 3, "tp": 6},
    {"name": "Konservativ","kauf": 9, "verk": 2, "sl": 2, "tp": 5},
]

def send_text(msg):
    if not TELEGRAM_TOKEN:
        print(msg)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"})

def sma(prices, n):
    return float(pd.Series(prices).rolling(n).mean().iloc[-1])

def rsi_val(prices, n=14):
    s = pd.Series(prices)
    d = s.diff()
    g = d.where(d > 0, 0).rolling(n).mean()
    l = (-d.where(d < 0, 0)).rolling(n).mean()
    rs = g / l
    return float((100 - 100 / (1 + rs)).iloc[-1])

def macd_val(prices):
    s = pd.Series(prices)
    m = s.ewm(span=12).mean() - s.ewm(span=26).mean()
    sig = m.ewm(span=9).mean()
    return float(m.iloc[-1]), float(sig.iloc[-1])

def atr_val(prices, n=14):
    s = pd.Series(prices)
    return float((s.rolling(2).max() - s.rolling(2).min()).rolling(n).mean().iloc[-1])

def bb_val(prices, n=20):
    s = pd.Series(prices)
    m = float(s.rolling(n).mean().iloc[-1])
    std = float(s.rolling(n).std().iloc[-1])
    return m, std

def berechne_signal(preise, kauf, verk):
    if len(preise) < 200:
        return "WARTEN", 0
    aktuell = preise[-1]
    s200 = sma(preise, 200)
    s50  = sma(preise, 50)
    r    = rsi_val(preise)
    m, ms = macd_val(preise)
    bb_m, bb_s = bb_val(preise)
    punkte = 0
    if aktuell > s200:               punkte += 3
    if aktuell > s50:                punkte += 2
    if m > ms:                       punkte += 2
    if r < 70:                       punkte += 1
    if r > 30:                       punkte += 1
    if aktuell < (bb_m + 2 * bb_s): punkte += 1
    if punkte >= kauf:  return "KAUFEN",    punkte
    if punkte <= verk:  return "VERKAUFEN", punkte
    return "HALTEN", punkte

def lade_preise(asset_id):
    try:
        df = yf.download(asset_id, period=PERIODE, progress=False, auto_adjust=True)
        if df.empty or len(df) < 50:
            return None
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return [float(x) for x in close.values if not np.isnan(x)]
    except:
        return None

def backtest_params(preise_list, params):
    kauf = params["kauf"]
    verk = params["verk"]
    sl_m = params["sl"]
    tp_m = params["tp"]
    gesamt_bot  = 0
    gesamt_hold = 0
    gesamt_trades = 0

    for preise in preise_list:
        if not preise or len(preise) < 220:
            continue
        kapital    = float(KAPITAL)
        position   = None
        trades     = []
        hold_start = preise[200]

        for i in range(200, len(preise)):
            slice_  = preise[:i + 1]
            aktuell = preise[i]
            signal, _ = berechne_signal(slice_, kauf, verk)
            a  = atr_val(slice_)
            sl = aktuell - a * sl_m
            tp = aktuell + a * tp_m

            if signal == "KAUFEN" and position is None and sl < aktuell:
                risiko_euro = kapital * 0.01
                shares      = risiko_euro / (aktuell - sl)
                kosten      = shares * aktuell
                if kosten < kapital * 0.5:
                    position = {"shares": shares, "entry": aktuell, "sl": sl, "tp": tp}
                    kapital -= kosten
            elif position:
                exit_grund = None
                if aktuell <= position["sl"]:   exit_grund = "SL"
                elif aktuell >= position["tp"]: exit_grund = "TP"
                elif signal == "VERKAUFEN":     exit_grund = "Signal"
                if exit_grund:
                    exit_wert = position["shares"] * aktuell
                    pnl       = exit_wert - position["shares"] * position["entry"]
                    kapital  += exit_wert
                    trades.append(pnl > 0)
                    position = None

        if position:
            exit_wert = position["shares"] * preise[-1]
            kapital  += exit_wert

        gesamt_bot  += (kapital / KAPITAL - 1) * 100
        gesamt_hold += (preise[-1] / preise[200] - 1) * 100
        gesamt_trades += len(trades)

    n = len(preise_list)
    return {
        "bot":    round(gesamt_bot / n, 1) if n > 0 else 0,
        "hold":   round(gesamt_hold / n, 1) if n > 0 else 0,
        "trades": gesamt_trades,
    }

def main():
    print("=== Parameter-Optimierung gestartet ===")
    heute = datetime.now().strftime("%d.%m.%Y")

    print("Lade Preisdaten...")
    preise_list = []
    for asset in ASSETS:
        p = lade_preise(asset["id"])
        if p:
            preise_list.append(p)
    print(f"{len(preise_list)} Assets geladen")

    msg  = f"Backtest Optimierung - {heute}\n"
    msg += f"2 Jahre - {len(preise_list)} Assets\n\n"

    beste = None
    bester_name = ""

    for params in PARAMETER_SETS:
        print(f"Teste {params['name']}...")
        r = backtest_params(preise_list, params)
        diff = r["bot"] - r["hold"]
        icon = "OK" if diff > 0 else "!!"
        msg += f"{icon} {params['name']} (Kauf>={params['kauf']} SL*{params['sl']} TP*{params['tp']})\n"
        msg += f"   Bot {r['bot']:+.1f}% vs Hold {r['hold']:+.1f}% ({r['trades']} Trades)\n\n"
        if beste is None or r["bot"] > beste:
            beste = r["bot"]
            bester_name = params["name"]

    msg += f"Beste Strategie: {bester_name} mit {beste:+.1f}%"
    send_text(msg)
    print("=== Fertig ===")

if __name__ == "__main__":
    main()
