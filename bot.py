import os
import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import io
import yfinance as yf
import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
KAPITAL = 10000
MAX_RISIKO = 0.01
analyzer = SentimentIntensityAnalyzer()

NEWS_FEEDS = {
    "welt": [
        "https://feeds.reuters.com/reuters/businessNews",
        "http://feeds.bbci.co.uk/news/business/rss.xml",
    ],
    "europa": [
        "https://www.derstandard.at/rss/wirtschaft",
        "https://euronews.com/rss?format=mrss&level=theme&name=business",
    ]
}

ASSETS = [
    {"name": "Bitcoin",     "typ": "crypto", "id": "bitcoin",    "symbol": "₿ BTC"},
    {"name": "Ethereum",    "typ": "crypto", "id": "ethereum",   "symbol": "Ξ ETH"},
    {"name": "S&P 500",     "typ": "aktie",  "id": "SPY",        "symbol": "🇺🇸 SPY"},
    {"name": "Apple",       "typ": "aktie",  "id": "AAPL",       "symbol": "🍎 AAPL"},
    {"name": "Nvidia",      "typ": "aktie",  "id": "NVDA",       "symbol": "🟢 NVDA"},
    {"name": "Tesla",       "typ": "aktie",  "id": "TSLA",       "symbol": "🚗 TSLA"},
    {"name": "Microsoft",   "typ": "aktie",  "id": "MSFT",       "symbol": "🪟 MSFT"},
    {"name": "DAX ETF",     "typ": "aktie",  "id": "EXS1.DE",    "symbol": "🇩🇪 DAX"},
    {"name": "SAP",         "typ": "aktie",  "id": "SAP.DE",     "symbol": "🇩🇪 SAP"},
    {"name": "Nikkei ETF",  "typ": "aktie",  "id": "EWJ",        "symbol": "🇯🇵 EWJ"},
    {"name": "EM ETF",      "typ": "aktie",  "id": "VWO",        "symbol": "🌍 VWO"},
    {"name": "Gold",        "typ": "aktie",  "id": "GC=F",       "symbol": "🥇 Gold"},
    {"name": "Silber",      "typ": "aktie",  "id": "SI=F",       "symbol": "🥈 Silber"},
    {"name": "Öl",          "typ": "aktie",  "id": "BZ=F",       "symbol": "🛢️ Öl"},
    {"name": "Kupfer",      "typ": "aktie",  "id": "HG=F",       "symbol": "🔧 Kupfer"},
    {"name": "Weizen",      "typ": "aktie",  "id": "ZW=F",       "symbol": "🌾 Weizen"},
]

def send_text(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"})

def send_photo(img, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption}, files={"photo": img})

def schreibe_journal(asset_name, signal, kurs, details, sw, seu):
    try:
        import csv
        from pathlib import Path
        journal_file = "journal.csv"
        file_exists = Path(journal_file).exists()
        with open(journal_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["Datum","Asset","Signal","Kurs","SMA200","RSI","Score","Stop Loss","Take Profit","Sentiment Welt","Sentiment EU","Kommentar"])
            writer.writerow([
                datetime.now().strftime("%d.%m.%Y %H:%M"),
                asset_name, signal,
                round(kurs, 2),
                round(details.get("sma200", 0), 2),
                round(details.get("rsi", 0), 1),
                details.get("punkte", 0),
                round(details.get("stop_loss", 0), 2),
                round(details.get("take_profit", 0), 2),
                sw, seu, "Paper Trading"
            ])
        print(f"Journal CSV: {asset_name} gespeichert")
    except Exception as e:
        print(f"Journal CSV Fehler: {e}")
    try:
        sheets_url = os.environ.get("SHEETS_URL")
        if sheets_url:
            payload = {
                "datum": datetime.now().strftime("%d.%m.%Y %H:%M"),
                "asset": asset_name,
                "signal": signal,
                "kurs": round(kurs, 2),
                "sma200": round(details.get("sma200", 0), 2),
                "rsi": round(details.get("rsi", 0), 1),
                "score": details.get("punkte", 0),
                "stop_loss": round(details.get("stop_loss", 0), 2),
                "take_profit": round(details.get("take_profit", 0), 2),
                "sentiment_welt": sw,
                "sentiment_eu": seu,
                "ergebnis": "",
                "kommentar": "Paper Trading"
            }
            import json
            r = requests.post(sheets_url, data=json.dumps(payload),
                            headers={"Content-Type": "application/json"}, timeout=10)
            print(f"Journal Sheets: {asset_name} – {r.status_code}")
    except Exception as e:
        print(f"Journal Sheets Fehler: {e}")

def get_sentiment(kat="welt"):
    scores = []
    for url in NEWS_FEEDS.get(kat, []):
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:10]:
                text = e.get("title","") + " " + e.get("summary","")
                scores.append(analyzer.polarity_scores(text)["compound"])
        except:
            pass
    return round(sum(scores)/len(scores), 3) if scores else 0.0

def sentiment_emoji(s):
    if s > 0.2:  return "😊 Positiv"
    if s < -0.2: return "😟 Negativ"
    return "😐 Neutral"

def get_crypto(coin_id):
    try:
        r = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
            params={"vs_currency": "eur", "days": "300", "interval": "daily"},
            timeout=10)
        data = r.json()
        if "prices" not in data: return None, None
        return [p[1] for p in data["prices"]], [datetime.fromtimestamp(p[0]/1000) for p in data["prices"]]
    except:
        return None, None

def get_aktie(ticker):
    try:
        df = yf.download(ticker, period="300d", interval="1d", progress=False, auto_adjust=True)
        if df.empty or len(df) < 50: return None, None
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        preise = [float(x) for x in close.values]
        daten = [x.to_pydatetime() for x in df.index]
        return preise, daten
    except Exception as e:
        print(f"Fehler {ticker}: {e}")
        return None, None

def sma(p, n): return pd.Series(p).rolling(n).mean()

def rsi_val(p, n=14):
    s = pd.Series(p)
    d = s.diff()
    g = d.where(d>0,0).rolling(n).mean()
    l = -d.where(d<0,0).rolling(n).mean()
    return float((100-(100/(1+(g/l)))).iloc[-1])

def macd_val(p):
    s = pd.Series(p)
    m = s.ewm(span=12).mean()-s.ewm(span=26).mean()
    return float(m.iloc[-1]), float(m.ewm(span=9).mean().iloc[-1])

def atr_val(p, n=14):
    s = pd.Series(p)
    return float((s.rolling(2).max()-s.rolling(2).min()).rolling(n).mean().iloc[-1])

def berechne_signal(preise, sw, seu):
    if len(preise) < 200: return "WARTEN", 0, {}
    aktuell = float(preise[-1])
    s200 = float(sma(preise, 200).iloc[-1])
    s50 = float(sma(preise, 50).iloc[-1])
    r = rsi_val(preise)
    m, ms = macd_val(preise)
    a = atr_val(preise)
    sentiment = (sw*0.3)+(seu*0.2)
    punkte = 0
    if aktuell > s200:   punkte += 3
    if aktuell > s50:    punkte += 2
    if m > ms:           punkte += 2
    if r < 70:           punkte += 1
    if r > 30:           punkte += 1
    if sentiment > 0.1:  punkte += 2
    bb_m = float(pd.Series(preise).rolling(20).mean().iloc[-1])
    bb_s = float(pd.Series(preise).rolling(20).std().iloc[-1])
    if aktuell < (bb_m + 2*bb_s): punkte += 1
    sl = aktuell-(a*2)
    tp = aktuell+(a*4)
    ps = (KAPITAL*MAX_RISIKO)/(aktuell-sl) if aktuell > sl else 0
    details = {"sma200":s200,"sma50":s50,"rsi":r,"macd":m,"atr":a,"stop_loss":sl,"take_profit":tp,"position_size":ps,"punkte":punkte}
    if punkte >= 8:  return "KAUFEN", punkte, details
    if punkte <= 3:  return "VERKAUFEN", punkte, details
    return "HALTEN", punkte, details

def erstelle_chart(preise, daten, name, signal, details):
    fig, (ax1, ax2) = plt.subplots(2,1,figsize=(12,8),gridspec_kw={'height_ratios':[3,1]})
    fig.patch.set_facecolor('#1e1e2e')
    ax1.set_facecolor('#1e1e2e')
    ax1.plot(daten[-100:], preise[-100:], color='#89b4fa', linewidth=2, label='Kurs')
    ax1.plot(daten[-100:], sma(preise,200).values[-100:], color='#f9e2af', linewidth=2, linestyle='--', label='SMA200')
    ax1.plot(daten[-100:], sma(preise,50).values[-100:], color='#a6e3a1', linewidth=1.5, linestyle='--', label='SMA50')
    s = pd.Series(preise)
    bb_m = s.rolling(20).mean()
    bb_s = s.rolling(20).std()
    ax1.fill_between(daten[-100:], (bb_m+2*bb_s).values[-100:], (bb_m-2*bb_s).values[-100:], alpha=0.1, color='#cba6f7')
    ax1.axhline(y=details["stop_loss"], color='#f38ba8', linestyle=':', linewidth=1.5, label=f'SL: {details["stop_loss"]:.0f}')
    ax1.axhline(y=details["take_profit"], color='#a6e3a1', linestyle=':', linewidth=1.5, label=f'TP: {details["take_profit"]:.0f}')
    farbe = '#a6e3a1' if signal=="KAUFEN" else '#f38ba8' if signal=="VERKAUFEN" else '#f9e2af'
    ax1.set_title(f"{name} – {signal} (Score: {details['punkte']}/12)", color=farbe, fontsize=14, fontweight='bold')
    ax1.tick_params(colors='white')
    ax1.legend(facecolor='#313244', labelcolor='white', fontsize=8)
    ax1.grid(color='#313244', linewidth=0.5)
    for spine in ax1.spines.values(): spine.set_edgecolor('#313244')
    ax2.set_facecolor('#1e1e2e')
    s2 = pd.Series(preise)
    d2 = s2.diff()
    g2 = d2.where(d2>0,0).rolling(14).mean()
    l2 = -d2.where(d2<0,0).rolling(14).mean()
    rsi_v = (100-(100/(1+(g2/l2)))).values[-100:]
    ax2.plot(daten[-100:], rsi_v, color='#cba6f7', linewidth=1.5)
    ax2.axhline(y=70, color='#f38ba8', linestyle='--', linewidth=1)
    ax2.axhline(y=30, color='#a6e3a1', linestyle='--', linewidth=1)
    ax2.set_ylim(0,100)
    ax2.set_ylabel('RSI', color='white')
    ax2.tick_params(colors='white')
    ax2.grid(color='#313244', linewidth=0.5)
    for spine in ax2.spines.values(): spine.set_edgecolor('#313244')
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    buf.seek(0)
    plt.close()
    return buf

def run_bot():
    print("=== Profi Trading Bot gestartet ===")
    try:
        vix_df = yf.download("^VIX", period="1d", interval="1d", progress=False, auto_adjust=True)
        vix_close = vix_df["Close"]
        if isinstance(vix_close, pd.DataFrame):
            vix_close = vix_close.iloc[:, 0]
        vix_wert = float(vix_close.iloc[-1])
        print(f"VIX aktuell: {vix_wert:.1f}")
        if vix_wert > 30:
            send_text(f"🚨 <b>NOTBREMSE!</b>\n\nVIX Angst-Index: {vix_wert:.1f} (über 30)\n⛔ Kein Handel heute!\n\n📊 Bot wird beendet.")
            return
        else:
            send_text(f"✅ VIX: {vix_wert:.1f} – Markt stabil, Analyse startet...")
    except Exception as e:
        print(f"VIX Fehler: {e}")
    heute = datetime.now().strftime("%d.%m.%Y %H:%M")
    sw = get_sentiment("welt")
    seu = get_sentiment("europa")
    send_text(f"📊 <b>Trading Bot – {heute}</b>\n\n🌍 Weltstimmung: {sentiment_emoji(sw)} ({sw})\n🇪🇺 EU-Stimmung: {sentiment_emoji(seu)} ({seu})\n\n🔍 Scanne {len(ASSETS)} Assets...")
    ergebnisse = []
    for asset in ASSETS:
        print(f"Analysiere {asset['name']}...")
        if asset["typ"] == "crypto":
            preise, daten = get_crypto(asset["id"])
        else:
            preise, daten = get_aktie(asset["id"])
        if preise is None or len(preise) < 50:
            continue
        signal, punkte, details = berechne_signal(preise, sw, seu)
        if signal == "WARTEN":
            continue
        ergebnisse.append({
            "asset": asset,
            "preise": preise,
            "daten": daten,
            "signal": signal,
            "punkte": punkte,
            "details": details
        })
    kaufen = sorted([e for e in ergebnisse if e["signal"] == "KAUFEN"], key=lambda x: -x["punkte"])[:5]
    verkaufen = sorted([e for e in ergebnisse if e["signal"] == "VERKAUFEN"], key=lambda x: x["punkte"])[:3]
    top = kaufen + verkaufen
    if not top:
        send_text("🟡 Heute keine klaren Signale – Markt abwarten.")
        return
    send_text(f"🏆 <b>Top {len(top)} Signale heute:</b>")
    for e in top:
        asset = e["asset"]
        details = e["details"]
        aktuell = e["preise"][-1]
        signal_text = "🟢 KAUFEN" if e["signal"] == "KAUFEN" else "🔴 VERKAUFEN"
        nachricht = (
            f"{asset['symbol']} <b>{asset['name']}</b>\n"
            f"💶 Kurs: {aktuell:,.2f}\n"
            f"Signal: {signal_text} (Score: {e['punkte']}/12)\n"
            f"SMA200: {details['sma200']:,.2f}\n"
            f"RSI: {details['rsi']:.1f}\n"
            f"🛑 Stop Loss: {details['stop_loss']:,.2f}\n"
            f"🎯 Take Profit: {details['take_profit']:,.2f}\n"
            f"⚠️ Paper Trading"
        )
        chart = erstelle_chart(e["preise"], e["daten"], asset["name"], e["signal"], details)
        send_photo(chart, nachricht)
        schreibe_journal(asset["name"], signal_text, aktuell, details, sw, seu)
    send_text(f"✅ <b>Analyse abgeschlossen!</b>\n📊 {len(ergebnisse)} Assets analysiert\n🟢 {len(kaufen)} Kaufsignale\n🔴 {len(verkaufen)} Verkaufssignale\n⚠️ Nur Paper Trading!")
    print("=== Bot fertig ===")

if __name__ == "__main__":
    run_bot()
