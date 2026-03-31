import os
import requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import io

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

ASSETS = [
    {"name": "Bitcoin",       "id": "bitcoin",       "symbol": "₿ BTC"},
    {"name": "Ethereum",      "id": "ethereum",      "symbol": "Ξ ETH"},
    {"name": "Apple",         "id": "apple",         "symbol": "🍎 AAPL"},
    {"name": "Nvidia",        "id": "nvidia-corp",   "symbol": "🟢 NVDA"},
    {"name": "Gold",          "id": "gold",          "symbol": "🥇 Gold"},
    {"name": "Tesla",         "id": "tesla",         "symbol": "🚗 TSLA"},
    {"name": "BNP Paribas",   "id": "bnp-paribas",   "symbol": "🏦 BNP"},
    {"name": "Deutsche Bank", "id": "deutsche-bank", "symbol": "🏦 DBK"},
]

def send_telegram_text(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"})

def send_telegram_photo(img_bytes, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption}, files={"photo": img_bytes})

def get_preise(coin_id):
    try:
        r = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
            params={"vs_currency": "eur", "days": "60", "interval": "daily"},
            timeout=10
        )
        data = r.json()
        if "prices" not in data:
            return None, None
        preise = [p[1] for p in data["prices"]]
        daten = [datetime.fromtimestamp(p[0]/1000) for p in data["prices"]]
        return preise, daten
    except:
        return None, None

def berechne_ema(preise, periode):
    s = pd.Series(preise)
    return s.ewm(span=periode, adjust=False).mean()

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
    ema20 = berechne_ema(preise, 20).iloc[-1]
    ema50 = berechne_ema(preise, 50).iloc[-1]
    rsi = berechne_rsi(preise)
    if ema20 > ema50 and rsi < 70:
        return "🟢 KAUFEN"
    elif ema20 < ema50 and rsi > 30:
        return "🔴 VERKAUFEN"
    return "🟡 HALTEN"

def erstelle_chart(preise, daten, name, signal):
    ema20 = berechne_ema(preise, 20)
    ema50 = berechne_ema(preise, 50)
    
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor('#1e1e2e')
    ax.set_facecolor('#1e1e2e')
    
    ax.plot(daten, preise, color='#89b4fa', linewidth=2, label='Kurs')
    ax.plot(daten, ema20, color='#a6e3a1', linewidth=1.5, linestyle='--', label='EMA20')
    ax.plot(daten, ema50, color='#f38ba8', linewidth=1.5, linestyle='--', label='EMA50')
    
    signal_farbe = '#a6e3a1' if 'KAUFEN' in signal else '#f38ba8' if 'VERKAUFEN' in signal else '#f9e2af'
    ax.set_title(f"{name} – Signal: {signal}", color=signal_farbe, fontsize=14, fontweight='bold')
    ax.tick_params(colors='white')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    plt.xticks(rotation=45, color='white')
    plt.yticks(color='white')
    ax.legend(facecolor='#313244', labelcolor='white')
    ax.grid(color='#313244', linewidth=0.5)
    for spine in ax.spines.values():
        spine.set_edgecolor('#313244')
    
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150)
    buf.seek(0)
    plt.close()
    return buf

def run_bot():
    print("=== Trading Bot gestartet ===")
    heute = datetime.now().strftime("%d.%m.%Y")
    send_telegram_text(f"📊 <b>Trading Bot Report – {heute}</b>\n\nAnalyse läuft...")
    
    for asset in ASSETS:
        print(f"Analysiere {asset['name']}...")
        preise, daten = get_preise(asset["id"])
        
        if preise is None:
            send_telegram_text(f"{asset['symbol']} <b>{asset['name']}</b>\n❌ Keine Daten verfügbar")
            continue
        
        signal = trade_signal(preise)
        ema20 = berechne_ema(preise, 20).iloc[-1]
        ema50 = berechne_ema(preise, 50).iloc[-1]
        rsi = berechne_rsi(preise)
        aktuell = preise[-1]
        
        nachricht = (
            f"{asset['symbol']} <b>{asset['name']}</b>\n"
            f"💶 Kurs: {aktuell:,.2f} €\n"
            f"Signal: {signal}\n"
            f"EMA20: {ema20:,.2f} €\n"
            f"EMA50: {ema50:,.2f} €\n"
            f"RSI: {rsi:.1f}"
        )
        
        chart = erstelle_chart(preise, daten, asset['name'], signal)
        send_telegram_photo(chart, nachricht)
        print(f"{asset['name']}: {signal}")
    
    send_telegram_text("✅ Analyse abgeschlossen!\n⚠️ Nur zur Information – kein automatischer Handel.")
    print("=== Bot fertig ===")

if __name__ == "__main__":
    run_bot()
