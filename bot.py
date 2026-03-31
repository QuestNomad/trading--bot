import os
import requests
import pandas as pd

API_KEY = os.environ.get("BITPANDA_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"})
    print(f"Telegram Status: {r.status_code}")
    print(f"Telegram Antwort: {r.text}")

def berechne_ema(preise, periode):
    s = pd.Series(preise)
    return s.ewm(span=periode, adjust=False).mean().iloc[-1]

def berechne_rsi(preise, periode=14):
    s = pd.Series(preise)
    delta = s.diff()
    gain = delta.where(delta > 0, 0).rolling(periode).mean()
    loss = -delta.where(delta < 0, 0).rolling(periode).mean()
    rs = gain / loss
    return (100 - (100 / (1 + rs))).iloc[-1]

def trade_signal(preise):
    if len(preise) < 50:
        return "⏳ WARTEN"
    ema20 = berechne_ema(preise, 20)
    ema50 = berechne_ema(preise, 50)
    rsi = berechne_rsi(preise)
    if ema20 > ema50 and rsi < 70:
        return "🟢 KAUFEN"
    elif ema20 < ema50 and rsi > 30:
        return "🔴 VERKAUFEN"
    return "🟡 HALTEN"

def run_bot():
    print("=== Trading Bot gestartet ===")
    r = requests.get(
        "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
        params={"vs_currency": "eur", "days": "60", "interval": "daily"}
    )
    btc_preise = [p[1] for p in r.json()["prices"]]
    signal = trade_signal(btc_preise)
    ema20 = berechne_ema(btc_preise, 20)
    ema50 = berechne_ema(btc_preise, 50)
    rsi = berechne_rsi(btc_preise)
    aktuell = btc_preise[-1]

    nachricht = f"""📊 <b>Trading Bot Report</b>

₿ <b>BITCOIN</b>
💶 Kurs: {aktuell:,.0f} €
Signal: {signal}
EMA20: {ema20:,.0f} €
EMA50: {ema50:,.0f} €
RSI: {rsi:.1f}

⚠️ Nur zur Information"""

    print(nachricht)
    send_telegram(nachricht)
    print("=== Bot fertig ===")

if __name__ == "__main__":
    run_bot()
