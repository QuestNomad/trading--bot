import os
import json
import pandas as pd
import numpy as np
import yfinance as yf
import requests
from datetime import datetime

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

KAPITAL = 10000
MAX_RISIKO = 0.01
PERIODE = "2y"

# ── Assets (synchron mit bot.py) ──────────────────────────────
ASSETS = [
    {"name": "Bitcoin",       "id": "BTC-EUR"},
    {"name": "Ethereum",      "id": "ETH-EUR"},
    {"name": "S&P 500",       "id": "SPY"},
    {"name": "Apple",         "id": "AAPL"},
    {"name": "Nvidia",        "id": "NVDA"},
    {"name": "Tesla",         "id": "TSLA"},
    {"name": "Microsoft",     "id": "MSFT"},
    {"name": "Amazon",        "id": "AMZN"},
    {"name": "Meta",          "id": "META"},
    {"name": "Google",        "id": "GOOGL"},
    {"name": "DAX ETF",       "id": "EXS1.DE"},
    {"name": "SAP",           "id": "SAP.DE"},
    {"name": "Rheinmetall",   "id": "RHM.DE"},
    {"name": "Airbus",        "id": "AIR.DE"},
    {"name": "Gold",          "id": "GC=F"},
    {"name": "Silber",        "id": "SI=F"},
    {"name": "Russell 2000",  "id": "IWM"},
    {"name": "Nikkei ETF",    "id": "EWJ"},
]

PARAMETER_SETS = [
    {"name": "Original",     "kauf": 8, "verk": 3, "sl": 2, "tp": 4},
    {"name": "Aggressiv",    "kauf": 7, "verk": 3, "sl": 2, "tp": 6},
    {"name": "Locker",       "kauf": 7, "verk": 4, "sl": 3, "tp": 6},
    {"name": "Konservativ",  "kauf": 9, "verk": 2, "sl": 2, "tp": 5},
]


# ── Telegram ──────────────────────────────────────────
def send_text(msg):
    if not TELEGRAM_TOKEN:
        print(msg)
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "HTML"
        }, timeout=15)
    except Exception as e:
        print(f"Telegram Fehler: {e}")


# ── Technische Indikatoren (synchron mit bot.py) ──────────────
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
    """ATR mit echtem True Range (Close-to-Close Proxy) – synchron mit bot.py."""
    s = pd.Series(prices)
    tr = s.diff().abs()
    tr.iloc[0] = 0
    return float(tr.rolling(n).mean().iloc[-1])


def bb_val(prices, n=20):
    s = pd.Series(prices)
    m = float(s.rolling(n).mean().iloc[-1])
    std = float(s.rolling(n).std().iloc[-1])
    return m, std


# ── Signal (synchron mit bot.py) ──────────────────────────────
def berechne_signal(preise, kauf_schwelle=8, verk_schwelle=3, sw=0.0, seu=0.0):
    """
    Einheitliche Signalberechnung – identisch mit bot.py.
    sw/seu = 0.0 im Backtest (kein Live-Sentiment).
    """
    if len(preise) < 200:
        return "WARTEN", 0

    aktuell = preise[-1]
    s200 = sma(preise, 200)
    s50 = sma(preise, 50)
    r = rsi_val(preise)
    m, ms = macd_val(preise)
    bb_m, bb_s = bb_val(preise)
    sentiment = (sw * 0.3) + (seu * 0.2)

    punkte = 0
    if aktuell > s200:
        punkte += 3
    if aktuell > s50:
        punkte += 2
    if m > ms:
        punkte += 2
    if r < 70:
        punkte += 1
    if r > 30:
        punkte += 1
    if sentiment > 0.1:
        punkte += 2
    if aktuell < (bb_m + 2 * bb_s):
        punkte += 1

    if punkte >= kauf_schwelle:
        return "KAUFEN", punkte
    if punkte <= verk_schwelle:
        return "VERKAUFEN", punkte
    return "HALTEN", punkte


# ── Daten laden ───────────────────────────────────────
def lade_preise(asset_id):
    try:
        df = yf.download(asset_id, period=PERIODE, progress=False, auto_adjust=True)
        if df.empty or len(df) < 50:
            return None
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return [float(x) for x in close.values if not np.isnan(x)]
    except Exception:
        return None


# ── Backtest-Kern ─────────────────────────────────────
def backtest_params(preise_list, params):
    kauf = params["kauf"]
    verk = params["verk"]
    sl_m = params["sl"]
    tp_m = params["tp"]

    gesamt_bot = 0
    gesamt_hold = 0
    gesamt_trades = 0
    gewonnen = 0
    verloren = 0

    for preise in preise_list:
        if not preise or len(preise) < 220:
            continue
        kapital = float(KAPITAL)
        position = None
        trades = []
        hold_start = preise[200]

        for i in range(200, len(preise)):
            slice_ = preise[:i + 1]
            aktuell = preise[i]
            signal, _ = berechne_signal(slice_, kauf, verk)
            a = atr_val(slice_)
            sl = aktuell - a * sl_m
            tp = aktuell + a * tp_m

            if signal == "KAUFEN" and position is None and sl < aktuell:
                risiko_euro = kapital * MAX_RISIKO
                shares = risiko_euro / (aktuell - sl)
                kosten = shares * aktuell
                if kosten < kapital * 0.5:
                    position = {
                        "shares": shares, "entry": aktuell,
                        "sl": sl, "tp": tp
                    }
                    kapital -= kosten
            elif position:
                exit_grund = None
                if aktuell <= position["sl"]:
                    exit_grund = "SL"
                elif aktuell >= position["tp"]:
                    exit_grund = "TP"
                elif signal == "VERKAUFEN":
                    exit_grund = "Signal"

                if exit_grund:
                    exit_wert = position["shares"] * aktuell
                    pnl = exit_wert - position["shares"] * position["entry"]
                    kapital += exit_wert
                    trades.append(pnl > 0)
                    if pnl > 0:
                        gewonnen += 1
                    else:
                        verloren += 1
                    position = None

        if position:
            exit_wert = position["shares"] * preise[-1]
            kapital += exit_wert

        gesamt_bot += (kapital / KAPITAL - 1) * 100
        gesamt_hold += (preise[-1] / preise[200] - 1) * 100
        gesamt_trades += len(trades)

    n = len(preise_list)
    return {
        "bot": round(gesamt_bot / n, 1) if n > 0 else 0,
        "hold": round(gesamt_hold / n, 1) if n > 0 else 0,
        "trades": gesamt_trades,
        "gewonnen": gewonnen,
        "verloren": verloren,
        "winrate": round(gewonnen / (gewonnen + verloren) * 100, 1) if (gewonnen + verloren) > 0 else 0,
    }


# ── Hauptfunktion ─────────────────────────────────────
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

    msg = f"<b>Backtest Optimierung – {heute}</b>\n"
    msg += f"📊 {PERIODE} Zeitraum – {len(preise_list)} Assets\n\n"

    resultate = []
    beste = None
    bester_name = ""

    for params in PARAMETER_SETS:
        print(f"Teste {params['name']}...")
        r = backtest_params(preise_list, params)
        diff = r["bot"] - r["hold"]
        icon = "✅" if diff > 0 else "⚠️"

        msg += (
            f"{icon} <b>{params['name']}</b> "
            f"(Kauf≥{params['kauf']} SL×{params['sl']} TP×{params['tp']})\n"
            f"   Bot: {r['bot']:+.1f}% vs Hold: {r['hold']:+.1f}% "
            f"({r['trades']} Trades, WR: {r['winrate']}%)\n\n"
        )

        resultate.append({
            "name": params["name"],
            "params": params,
            "bot_return": r["bot"],
            "hold_return": r["hold"],
            "trades": r["trades"],
            "winrate": r["winrate"],
            "gewonnen": r["gewonnen"],
            "verloren": r["verloren"],
            "diff": round(diff, 1),
        })

        if beste is None or r["bot"] > beste:
            beste = r["bot"]
            bester_name = params["name"]

    msg += f"🏆 <b>Beste Strategie: {bester_name}</b> mit {beste:+.1f}%"
    send_text(msg)

    # JSON-Export für weitere Analyse
    export = {
        "datum": heute,
        "periode": PERIODE,
        "assets_count": len(preise_list),
        "beste_strategie": bester_name,
        "resultate": resultate,
    }
    json_path = "backtest_results.json"
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(export, f, indent=2, ensure_ascii=False)
        print(f"JSON Export: {json_path}")
    except Exception as e:
        print(f"JSON Export Fehler: {e}")

    print("=== Fertig ===")


if __name__ == "__main__":
    main()
