import os
import requests
import pandas as pd

# === KONFIGURATION ===
API_KEY = os.environ.get("BITPANDA_API_KEY")
BASE_URL = "https://api.bitpanda.com/v1"

# Welche Assets gehandelt werden sollen
ASSETS = [
    {"symbol": "BTC", "id": "1"},      # Bitcoin
    {"symbol": "ETH", "id": "5"},      # Ethereum  
    {"symbol": "AMZN", "id": "101"},   # Amazon Aktie
]

MIN_TRADE_EUR = 10  # Mindestbetrag pro Trade in Euro

def get_headers():
    return {"X-API-KEY": API_KEY}

def get_ticker(asset_id):
    url = f"https://api.bitpanda.com/v3/ticker"
    r = requests.get(url)
    data = r.json()
    return data

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

def get_wallet_balance():
    r = requests.get(f"{BASE_URL}/wallets", headers=get_headers())
    return r.json()

def trade_signal(preise):
    if len(preise) < 50:
        return "HALTEN"
    ema20 = berechne_ema(preise, 20)
    ema50 = berechne_ema(preise, 50)
    rsi = berechne_rsi(preise)
    
    if ema20 > ema50 and rsi < 70:
        return "KAUFEN"
    elif ema20 < ema50 and rsi > 30:
        return "VERKAUFEN"
    return "HALTEN"

def run_bot():
    print("=== Trading Bot gestartet ===")
    if not API_KEY:
        print("FEHLER: Kein API Key gefunden!")
        return
    
    # Kursdaten holen (Beispiel mit CoinGecko für BTC)
    r = requests.get(
        "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
        params={"vs_currency": "eur", "days": "60", "interval": "daily"}
    )
    btc_data = r.json()
    btc_preise = [p[1] for p in btc_data["prices"]]
    
    signal = trade_signal(btc_preise)
    print(f"BTC Signal: {signal}")
    print(f"EMA20: {berechne_ema(btc_preise, 20):.2f} EUR")
    print(f"EMA50: {berechne_ema(btc_preise, 50):.2f} EUR")
    print(f"RSI: {berechne_rsi(btc_preise):.1f}")
    print("=== Bot fertig ===")

if __name__ == "__main__":
    run_bot()
