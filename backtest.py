import os
import pandas as pd
import numpy as np
import yfinance as yf
import requests
from datetime import datetime

# ── Konfiguration ──────────────────────────────────────────

TELEGRAM_TOKEN   = os.environ.get(“TELEGRAM_TOKEN”)
TELEGRAM_CHAT_ID = os.environ.get(“TELEGRAM_CHAT_ID”)
KAPITAL          = 10000
MAX_RISIKO       = 0.01
PERIODE          = “2y”   # 2 Jahre historische Daten

ASSETS = [
{“name”: “Bitcoin”,     “typ”: “crypto_yf”, “id”: “BTC-EUR”},
{“name”: “Ethereum”,    “typ”: “crypto_yf”, “id”: “ETH-EUR”},
{“name”: “S&P 500”,     “typ”: “aktie”,     “id”: “SPY”},
{“name”: “Apple”,       “typ”: “aktie”,     “id”: “AAPL”},
{“name”: “Nvidia”,      “typ”: “aktie”,     “id”: “NVDA”},
{“name”: “Tesla”,       “typ”: “aktie”,     “id”: “TSLA”},
{“name”: “Microsoft”,   “typ”: “aktie”,     “id”: “MSFT”},
{“name”: “DAX ETF”,     “typ”: “aktie”,     “id”: “EXS1.DE”},
{“name”: “SAP”,         “typ”: “aktie”,     “id”: “SAP.DE”},
{“name”: “Gold”,        “typ”: “aktie”,     “id”: “GC=F”},
{“name”: “Silber”,      “typ”: “aktie”,     “id”: “SI=F”},
{“name”: “Amazon”,      “typ”: “aktie”,     “id”: “AMZN”},
{“name”: “Meta”,        “typ”: “aktie”,     “id”: “META”},
{“name”: “Google”,      “typ”: “aktie”,     “id”: “GOOGL”},
{“name”: “Rheinmetall”, “typ”: “aktie”,     “id”: “RHM.DE”},
{“name”: “Airbus”,      “typ”: “aktie”,     “id”: “AIR.DE”},
]

# ── Telegram ───────────────────────────────────────────────

def send_text(msg):
if not TELEGRAM_TOKEN:
print(msg)
return
url = f”https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage”
requests.post(url, data={“chat_id”: TELEGRAM_CHAT_ID, “text”: msg, “parse_mode”: “HTML”})

# ── Indikatoren ────────────────────────────────────────────

def sma(prices, n):
s = pd.Series(prices)
return float(s.rolling(n).mean().iloc[-1])

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

# ── Score-System (identisch zu bot.py) ────────────────────

def berechne_signal(preise, sentiment=0):
if len(preise) < 200:
return “WARTEN”, 0
aktuell = preise[-1]
s200 = sma(preise, 200)
s50  = sma(preise, 50)
r    = rsi_val(preise)
m, ms = macd_val(preise)
a    = atr_val(preise)
bb_m, bb_s = bb_val(preise)
punkte = 0
if aktuell > s200:               punkte += 3
if aktuell > s50:                punkte += 2
if m > ms:                       punkte += 2
if sentiment > 0.1:              punkte += 2
if r < 70:                       punkte += 1
if r > 30:                       punkte += 1
if aktuell < (bb_m + 2 * bb_s): punkte += 1
if punkte >= 8:  return “KAUFEN”,    punkte
if punkte <= 3:  return “VERKAUFEN”, punkte
return “HALTEN”, punkte

# ── Daten laden ────────────────────────────────────────────

def lade_preise(asset):
try:
df = yf.download(asset[“id”], period=PERIODE, progress=False, auto_adjust=True)
if df.empty or len(df) < 50:
return None, None
close = df[“Close”]
if isinstance(close, pd.DataFrame):
close = close.iloc[:, 0]
preise = [float(x) for x in close.values if not np.isnan(x)]
daten  = [x.to_pydatetime() for x in df.index]
return preise, daten
except Exception as e:
print(f”Fehler {asset[‘name’]}: {e}”)
return None, None

# ── Backtest für ein Asset ─────────────────────────────────

def backtest_asset(asset):
preise, daten = lade_preise(asset)
if not preise or len(preise) < 220:
return None

```
kapital    = float(KAPITAL)
position   = None
trades     = []
hold_start = preise[200]

for i in range(200, len(preise)):
    slice_   = preise[:i + 1]
    aktuell  = preise[i]
    signal, punkte = berechne_signal(slice_)
    a        = atr_val(slice_)
    sl       = aktuell - a * 2
    tp       = aktuell + a * 4

    if signal == "KAUFEN" and position is None and sl < aktuell:
        risiko_euro = kapital * MAX_RISIKO
        shares      = risiko_euro / (aktuell - sl)
        kosten      = shares * aktuell
        if kosten < kapital * 0.5:
            position = {
                "shares": shares,
                "entry":  aktuell,
                "sl":     sl,
                "tp":     tp,
                "datum":  daten[i] if daten else i,
            }
            kapital -= kosten

    elif position:
        exit_grund = None
        if aktuell <= position["sl"]:
            exit_grund = "Stop Loss"
        elif aktuell >= position["tp"]:
            exit_grund = "Take Profit"
        elif signal == "VERKAUFEN":
            exit_grund = "Signal"

        if exit_grund:
            exit_wert = position["shares"] * aktuell
            pnl       = exit_wert - position["shares"] * position["entry"]
            kapital  += exit_wert
            trades.append({
                "datum":  position["datum"],
                "pnl":    round(pnl, 2),
                "grund":  exit_grund,
                "win":    pnl > 0,
            })
            position = None

# offene Position schließen
if position:
    exit_wert = position["shares"] * preise[-1]
    pnl       = exit_wert - position["shares"] * position["entry"]
    kapital  += exit_wert
    trades.append({"datum": "offen", "pnl": round(pnl, 2), "grund": "Ende", "win": pnl > 0})

hold_return = (preise[-1] / hold_start - 1) * 100
bot_return  = (kapital / KAPITAL - 1) * 100
wins        = sum(1 for t in trades if t["win"])
win_rate    = (wins / len(trades) * 100) if trades else 0

return {
    "name":        asset["name"],
    "bot_return":  round(bot_return, 1),
    "hold_return": round(hold_return, 1),
    "trades":      len(trades),
    "win_rate":    round(win_rate, 1),
    "endkapital":  round(kapital, 0),
    "schlaegt":    bot_return > hold_return,
}
```

# ── Hauptfunktion ──────────────────────────────────────────

def main():
print(”=== Backtest gestartet ===”)
heute = datetime.now().strftime(”%d.%m.%Y”)
ergebnisse = []

```
for asset in ASSETS:
    print(f"Teste {asset['name']}...")
    r = backtest_asset(asset)
    if r:
        ergebnisse.append(r)

if not ergebnisse:
    print("Keine Ergebnisse")
    return

# Sortieren: Bot-Return absteigend
ergebnisse.sort(key=lambda x: x["bot_return"], reverse=True)

# Gesamtstatistik
schlaegt   = sum(1 for e in ergebnisse if e["schlaegt"])
avg_bot    = round(sum(e["bot_return"] for e in ergebnisse) / len(ergebnisse), 1)
avg_hold   = round(sum(e["hold_return"] for e in ergebnisse) / len(ergebnisse), 1)
total_trades = sum(e["trades"] for e in ergebnisse)

# Telegram Nachricht
msg = f"📊 <b>Backtest Report – {heute}</b>\n"
msg += f"Zeitraum: {PERIODE} · {len(ergebnisse)} Assets\n\n"
msg += f"🤖 Ø Bot Return:      {avg_bot:+.1f}%\n"
msg += f"📈 Ø Buy & Hold:      {avg_hold:+.1f}%\n"
msg += f"✅ Bot schlägt Hold:  {schlaegt}/{len(ergebnisse)}\n"
msg += f"🔄 Trades gesamt:     {total_trades}\n\n"

msg += "── Top 5 Assets ──\n"
for e in ergebnisse[:5]:
    icon = "✅" if e["schlaegt"] else "⚠️"
    msg += f"{icon} {e['name']}: Bot {e['bot_return']:+.1f}% vs Hold {e['hold_return']:+.1f}% ({e['win_rate']}% WR)\n"

msg += "\n── Schlechteste ──\n"
for e in ergebnisse[-3:]:
    icon = "✅" if e["schlaegt"] else "❌"
    msg += f"{icon} {e['name']}: Bot {e['bot_return']:+.1f}% vs Hold {e['hold_return']:+.1f}%\n"

send_text(msg)
print("=== Backtest fertig ===")
print(msg)
```

if **name** == “**main**”:
main()
