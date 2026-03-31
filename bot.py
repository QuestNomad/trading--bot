import os
import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import io
import yfinance as yf
import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# === KONFIGURATION ===
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
T212_API_KEY = os.environ.get("TRADING212_API_KEY")
PRACTICE_MODE = True  # Kein echtes Geld!
KAPITAL = 10000       # Virtuelles Startkapital
MAX_RISIKO_PRO_TRADE = 0.01  # 1% Regel
MIN_RISK_REWARD = 2.0        # 2:1 Minimum

# === NEWS QUELLEN ===
NEWS_FEEDS = {
    "welt": [
        "https://feeds.reuters.com/reuters/businessNews",
        "http://feeds.bbci.co.uk/news/business/rss.xml",
    ],
    "europa": [
        "https://www.derstandard.at/rss/wirtschaft",
        "https://www.euronews.com/rss?format=mrss&level=theme&name=business",
    ]
}

# === ASSETS (Top Universe) ===
CRYPTO_ASSETS = [
    {"name": "Bitcoin",  "id": "bitcoin",  "symbol": "₿ BTC"},
    {"name": "Ethereum", "id": "ethereum", "symbol": "Ξ ETH"},
]

STOCK_ASSETS = [
    # USA
    {"name": "S&P 500 ETF", "id": "SPY",     "symbol": "🇺🇸 SPY"},
    {"name": "Apple",       "id": "AAPL",    "symbol": "🍎 AAPL"},
    {"name": "Nvidia",      "id": "NVDA",    "symbol": "🟢 NVDA"},
    {"name": "Tesla",       "id": "TSLA",    "symbol": "🚗 TSLA"},
    {"name": "Microsoft",   "id": "MSFT",    "symbol": "🪟 MSFT"},
    # Deutschland
    {"name": "DAX ETF",     "id": "EXS1.DE", "symbol": "🇩🇪 DAX"},
    {"name": "SAP",         "id": "SAP.DE",  "symbol": "🇩🇪 SAP"},
    {"name": "Siemens",     "id": "SIE.DE",  "symbol": "🇩🇪 SIE"},
    # Japan
    {"name": "Nikkei ETF",  "id": "EWJ",     "symbol": "🇯🇵 EWJ"},
    # Emerging Markets
    {"name": "EM ETF",      "id": "VWO",     "symbol": "🌍 VWO"},
    # Rohstoffe & Edelmetalle
    {"name": "Gold",        "id": "GC=F",    "symbol": "🥇 Gold"},
    {"name": "Silber",      "id": "SI=F",    "symbol": "🥈 Silber"},
    {"name": "Öl Brent",    "id": "BZ=F",    "symbol": "🛢️ Öl"},
    {"name": "Kupfer",      "id": "HG=F",    "symbol": "🔧 Kupfer"},
    {"name": "Weizen",      "id": "ZW=F",    "symbol": "🌾 Weizen"},
]

analyzer = SentimentIntensityAnalyzer()

# === TELEGRAM ===
def send_text(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"})

def send_photo(img, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption}, files={"photo": img})

# === SENTIMENT ===
def get_sentiment(kategorie="welt"):
    scores = []
    for feed_url in NEWS_FEEDS.get(kategorie, []):
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:10]:
                text = entry.get("title", "") + " " + entry.get("summary", "")
                score = analyzer.polarity_scores(text)["compound"]
                scores.append(score)
        except:
            pass
    return round(sum(scores) / len(scores), 3) if scores else 0.0

def sentiment_emoji(score):
    if score > 0.2:   return "😊 Positiv"
    if score < -0.2:  return "😟 Negativ"
    return "😐 Neutral"

# === KURSDATEN ===
def get_crypto(coin_id):
    try:
        r = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
            params={"vs_currency": "eur", "days": "300", "interval": "daily"},
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

def get_aktie(ticker):
    try:
        df = yf.download(ticker, period="300d", interval="1d",
                        progress=False, auto_adjust=True)
        if df.empty or len(df) < 50:
            return None, None
        preise = [float(x) for x in df["Close"].values]
        daten = [x.to_pydatetime() for x in df.index]
        return preise, daten
    except Exception as e:
        print(f"Fehler {ticker}: {e}")
        return None, None

# === INDIKATOREN ===
def sma(preise, periode):
    s = pd.Series(preise)
    return s.rolling(periode).mean()

def ema(preise, periode):
    s = pd.Series(preise)
    return s.ewm(span=periode, adjust=False).mean()

def rsi(preise, periode=14):
    s = pd.Series(preise)
    delta = s.diff()
    gain = delta.where(delta > 0, 0).rolling(periode).mean()
    loss = -delta.where(delta < 0, 0).rolling(periode).mean()
    rs = gain / loss
    return (100 - (100 / (1 + rs))).iloc[-1]

def macd(preise):
    s = pd.Series(preise)
    macd_line = s.ewm(span=12).mean() - s.ewm(span=26).mean()
    signal = macd_line.ewm(span=9).mean()
    return macd_line.iloc[-1], signal.iloc[-1]

def atr(preise, periode=14):
    s = pd.Series(preise)
    high = s.rolling(2).max()
    low = s.rolling(2).min()
    tr = high - low
    return tr.rolling(periode).mean().iloc[-1]

def bollinger(preise, periode=20):
    s = pd.Series(preise)
    mitte = s.rolling(periode).mean()
    std = s.rolling(periode).std()
    return mitte.iloc[-1], mitte.iloc[-1] + 2*std.iloc[-1], mitte.iloc[-1] - 2*std.iloc[-1]

# === SIGNAL BERECHNUNG ===
def berechne_signal(preise, sentiment_welt, sentiment_eu):
    if len(preise) < 200:
        return "⏳ WARTEN", 0, {}

    aktuell = preise[-1]
    sma200 = sma(preise, 200).iloc[-1]
    sma50 = sma(preise, 50).iloc[-1]
    rsi_val = rsi(preise)
    macd_val, macd_sig = macd(preise)
    atr_val = atr(preise)
    bb_mitte, bb_oben, bb_unten = bollinger(preise)

    # Sentiment Gesamtscore
    sentiment_gesamt = (sentiment_welt * 0.3) + (sentiment_eu * 0.2)

    # Punkte-System (wie Profi-Bots)
    punkte = 0
    if aktuell > sma200:         punkte += 3  # Haupttrend
    if aktuell > sma50:          punkte += 2  # Kurztrend
    if macd_val > macd_sig:      punkte += 2  # Momentum
    if rsi_val < 70:             punkte += 1  # Nicht überkauft
    if rsi_val > 30:             punkte += 1  # Nicht überverkauft
    if sentiment_gesamt > 0.1:   punkte += 2  # Positive Stimmung
    if aktuell < bb_oben:        punkte += 1  # Nicht überdehnt

    # Risk-Reward Berechnung
    stop_loss = aktuell - (atr_val * 2)
    take_profit = aktuell + (atr_val * 4)  # 2:1 Ratio
    risiko_eur = KAPITAL * MAX_RISIKO_PRO_TRADE
    position_size = risiko_eur / (aktuell - stop_loss) if aktuell > stop_loss else 0

    details = {
        "sma200": sma200,
        "sma50": sma50,
        "rsi": rsi_val,
        "macd": macd_val,
        "atr": atr_val,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "position_size": position_size,
        "punkte": punkte
    }

    if punkte >= 8:    return "🟢 KAUFEN",    punkte, details
    if punkte <= 3:    return "🔴 VERKAUFEN", punkte, details
    return "🟡 HALTEN", punkte, details

# === CHART ===
def erstelle_chart(preise, daten, name, signal, details):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [3, 1]})
    fig.patch.set_facecolor('#1e1e2e')

    # Hauptchart
    ax1.set_facecolor('#1e1e2e')
    ax1.plot(daten[-100:], preise[-100:], color='#89b4fa', linewidth=2, label='Kurs')
    ax1.plot(daten[-100:], sma(preise, 200).values[-100:], color='#f9e2af', linewidth=2, linestyle='--', label='SMA200')
    ax1.plot(daten[-100:], sma(preise, 50).values[-100:], color='#a6e3a1', linewidth=1.5, linestyle='--', label='SMA50')

    # Bollinger Bands
    s = pd.Series(preise)
    bb_m = s.rolling(20).mean()
    bb_s = s.rolling(20).std()
    ax1.fill_between(daten[-100:], (bb_m + 2*bb_s).values[-100:],
                     (bb_m - 2*bb_s).values[-100:], alpha=0.1, color='#cba6f7')

    # Stop Loss & Take Profit
    ax1.axhline(y=details["stop_loss"], color='#f38ba8', linestyle=':', linewidth=1.5, label=f'Stop: {details["stop_loss"]:.0f}')
    ax1.axhline(y=details["take_profit"], color='#a6e3a1', linestyle=':', linewidth=1.5, label=f'TP: {details["take_profit"]:.0f}')

    farbe = '#a6e3a1' if 'KAUFEN' in signal else '#f38ba8' if 'VERKAUFEN' in signal else '#f9e2af'
    ax1.set_title(f"{name} – {signal} (Score: {details['punkte']}/12)", color=farbe, fontsize=14, fontweight='bold')
    ax1.tick_params(colors='white')
    ax1.legend(facecolor='#313244', labelcolor='white', fontsize=8)
    ax1.grid(color='#313244', linewidth=0.5)
    for spine in ax1.spines.values():
        spine.set_edgecolor('#313244')

    # RSI Chart
    ax2.set_facecolor('#1e1e2e')
    rsi_series = pd.Series(preise)
    delta = rsi_series.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss
    rsi_vals = (100 - (100 / (1 + rs))).values[-100:]
    ax2.plot(daten[-100:], rsi_vals, color='#cba6f7', linewidth=1.5)
    ax2.axhline(y=70, color='#f38ba8', linestyle='--', linewidth=1)
    ax2.axhline(y=30, color='#a6e3a1', linestyle='--', linewidth=1)
    ax2.set_ylim(0, 100)
    ax2.set_ylabel('RSI', color='white')
    ax2.tick_params(colors='white')
    ax2.grid(color='#313244', linewidth=0.5)
    ax2.set_facecolor('#1e1e2e')
    for spine in ax2.spines.values():
        spine.set_edgecolor('#313244')

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150)
    buf.seek(0)
    plt.close()
    return buf

# === HAUPTPROGRAMM ===
def run_bot():
    print("=== Profi Trading Bot gestartet ===")
    heute = datetime.now().strftime("%d.%m.%Y %H:%M")

    # Sentiment holen
    print("Sentiment wird analysiert...")
    sentiment_welt = get_sentiment("welt")
    sentiment_eu = get_sentiment("europa")

    send_text(
        f"📊 <b>Profi Trading Bot – {heute}</b>\n\n"
        f"🌍 Weltstimmung: {sentiment_emoji(sentiment_welt)} ({sentiment_welt})\n"
        f"🇪🇺 EU-Stimmung: {sentiment_emoji(sentiment_eu)} ({sentiment_eu})\n\n"
        f"🔍 Scanne {len(CRYPTO_ASSETS) + len(STOCK_ASSETS)} Assets..."
    )

    ergebnisse = []

    # Alle Assets analysieren
    alle_assets = [(a, "crypto") for a in CRYPTO_ASSETS] + [(a, "aktie") for a in STOCK_ASSETS]

    for asset, typ in alle_assets:
        print(f"Analysiere {asset['name']}...")
        if typ == "crypto":
            preise, daten = get_crypto(asset["id"])
        else:
            preise, daten = get_aktie(asset["id"])

        if preise is None or len(preise) < 50:
            continue

        signal, punkte, details = berechne_signal(preise, sentiment_welt, sentiment_eu)

        ergebnisse.append({
            "asset": asset,
            "preise": preise,
            "daten": daten,
            "signal": signal,
            "punkte": punkte,
            "details": details
        })

    # Nach Score sortieren → Top 5 KAUFEN + Top 3 VERKAUFEN
    kaufen = sorted([e for e in ergebnisse if "KAUFEN" in e["signal"]], key=lambda x: -x["punkte"])[:5]
    verkaufen = sorted([e for e in ergebnisse if "VERKAUFEN" in e["signal"]], key=lambda x: x["punkte"])[:3]
    top = kaufen + verkaufen

    if not top:
        send_text("🟡 Heute keine klaren Signale – Markt abwarten.")
        return

    send_text(f"🏆 <b>Top {len(top)} Signale heute:</b>")

    for e in top:
        asset = e["asset"]
        details = e["details"]
        aktuell = e["preise"][-1]

        nachricht = (
            f"{asset['symbol']} <b>{asset['name']}</b>\n"
            f"💶 Kurs: {aktuell:,.2f}\n"
            f"Signal: {e['signal']} (Score: {e['punkte']}/12)\n"
            f"SMA200: {details['sma200']:,.2f}\n"
            f"RSI: {details['rsi']:.1f}\n"
            f"🛑 Stop Loss: {details['stop_loss']:,.2f}\n"
            f"🎯 Take Profit: {details['take_profit']:,.2f}\n"
            f"📦 Position: {details['position_size']:.4f} Einheiten\n"
            f"⚠️ Paper Trading"
        )

        chart = erstelle_chart(e["preise"], e["daten"], asset["name"], e["signal"], details)
        send_photo(chart, nachricht)

    send_text(
        f"✅ <b>Analyse abgeschlossen!</b>\n"
        f"📊 {len(ergebnisse)} Assets analysiert\n"
        f"🟢 {len(kaufen)} Kaufsignale\n"
        f"🔴 {len(verkaufen)} Verkaufssignale\n"
        f"⚠️ Nur Paper Trading – kein echtes Geld!"
    )
    print("=== Bot fertig ===")

if __name__ == "__main__":
    run_bot()
