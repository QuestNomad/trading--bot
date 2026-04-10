import os
import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import io
import time
import json
import threading
import math
import yfinance as yf
import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

# ── Konfiguration ─────────────────────────────────────────────
TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
KAPITAL    = 10000
MAX_RISIKO = 0.01
VIX_LIMIT  = 30
MAX_RETRIES = 3
RETRY_DELAY = 5

analyzer = SentimentIntensityAnalyzer()
_yf_lock = threading.Lock()

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

# ── Journal-Header (erweitert für P&L) ──────────────────────────
JOURNAL_HEADER = [
    "Datum", "Asset", "Signal", "Kurs", "SMA200", "RSI", "Score",
    "Stop Loss", "Take Profit", "Sentiment Welt", "Sentiment EU",
    "Status", "Ergebnis", "Geschlossen_am", "Kommentar"
]

# ── 38 eindeutige Assets ────────────────────────────────────────
ASSETS = [
    {"name": "Bitcoin",        "typ": "crypto", "id": "bitcoin",   "symbol": "₿ BTC"},
    {"name": "Ethereum",       "typ": "crypto", "id": "ethereum",  "symbol": "Ξ ETH"},
    {"name": "S&P 500",        "typ": "aktie",  "id": "SPY",       "symbol": "🇺🇸 SPY"},
    {"name": "Apple",          "typ": "aktie",  "id": "AAPL",      "symbol": "🍎 AAPL"},
    {"name": "Nvidia",         "typ": "aktie",  "id": "NVDA",      "symbol": "🟢 NVDA"},
    {"name": "Tesla",          "typ": "aktie",  "id": "TSLA",      "symbol": "🚗 TSLA"},
    {"name": "Microsoft",      "typ": "aktie",  "id": "MSFT",      "symbol": "🪟 MSFT"},
    {"name": "Amazon",         "typ": "aktie",  "id": "AMZN",      "symbol": "📦 AMZN"},
    {"name": "Meta",           "typ": "aktie",  "id": "META",      "symbol": "👓 META"},
    {"name": "Google",         "typ": "aktie",  "id": "GOOGL",     "symbol": "🔍 GOOGL"},
    {"name": "DAX ETF",        "typ": "aktie",  "id": "EXS1.DE",   "symbol": "🇩🇪 DAX"},
    {"name": "SAP",            "typ": "aktie",  "id": "SAP.DE",    "symbol": "🇩🇪 SAP"},
    {"name": "Rheinmetall",    "typ": "aktie",  "id": "RHM.DE",    "symbol": "🛡️ RHM"},
    {"name": "Airbus",         "typ": "aktie",  "id": "AIR.DE",    "symbol": "✈️ AIR"},
    {"name": "Zalando",        "typ": "aktie",  "id": "ZAL.DE",    "symbol": "👟 ZAL"},
    {"name": "Delivery Hero",  "typ": "aktie",  "id": "DHER.DE",   "symbol": "🍔 DHER"},
    {"name": "Deutsche Bank",  "typ": "aktie",  "id": "DBK.DE",    "symbol": "🏦 DBK"},
    {"name": "BNP Paribas",    "typ": "aktie",  "id": "BNP.PA",    "symbol": "🏦 BNP"},
    {"name": "UBS",            "typ": "aktie",  "id": "UBSG.SW",   "symbol": "🏦 UBS"},
    {"name": "Nikkei ETF",     "typ": "aktie",  "id": "EWJ",       "symbol": "🇯🇵 EWJ"},
    {"name": "Toyota",         "typ": "aktie",  "id": "7203.T",    "symbol": "🚗 Toyota"},
    {"name": "Sony",           "typ": "aktie",  "id": "6758.T",    "symbol": "🎮 Sony"},
    {"name": "China ETF",      "typ": "aktie",  "id": "FXI",       "symbol": "🇨🇳 FXI"},
    {"name": "Alibaba HK",     "typ": "aktie",  "id": "9988.HK",   "symbol": "🛒 Alibaba"},
    {"name": "Tencent",        "typ": "aktie",  "id": "0700.HK",   "symbol": "🎯 Tencent"},
    {"name": "Indien ETF",     "typ": "aktie",  "id": "INDA",      "symbol": "🇮🇳 INDA"},
    {"name": "Brasilien ETF",  "typ": "aktie",  "id": "EWZ",       "symbol": "🇧🇷 EWZ"},
    {"name": "EM ETF",         "typ": "aktie",  "id": "VWO",       "symbol": "🌍 VWO"},
    {"name": "Russell 2000",   "typ": "aktie",  "id": "IWM",       "symbol": "🇺🇸 IWM"},
    {"name": "Gold",           "typ": "aktie",  "id": "GC=F",      "symbol": "🥇 Gold"},
    {"name": "Silber",         "typ": "aktie",  "id": "SI=F",      "symbol": "🥈 Silber"},
    {"name": "Öl",             "typ": "aktie",  "id": "BZ=F",      "symbol": "🛢️ Öl"},
    {"name": "Kupfer",         "typ": "aktie",  "id": "HG=F",      "symbol": "🔧 Kupfer"},
    {"name": "Weizen",         "typ": "aktie",  "id": "ZW=F",      "symbol": "🌾 Weizen"},
    {"name": "Short S&P 500",  "typ": "aktie",  "id": "XSPS.L",   "symbol": "📉 XSPS",          "short": True},
    {"name": "Short DAX",      "typ": "aktie",  "id": "DXSN.DE",   "symbol": "📉 DXSN",          "short": True},
    {"name": "Short Nasdaq",   "typ": "aktie",  "id": "QQQS.L",   "symbol": "📉 QQQS",          "short": True},
    {"name": "Short Krypto",   "typ": "aktie",  "id": "BITI",      "symbol": "📉 Krypto Short",  "short": True},
]

# ── Retry-Wrapper ─────────────────────────────────────────────
def mit_retry(func, *args, retries=MAX_RETRIES, delay=RETRY_DELAY):
    """Führt eine Funktion mit Retry-Logik aus."""
    for versuch in range(retries):
        try:
            return func(*args)
        except Exception as e:
            print(f"  Retry {versuch+1}/{retries} für {func.__name__}: {e}")
            if versuch < retries - 1:
                time.sleep(delay)
    return None

# ── Telegram (mit try/except) ─────────────────────────────────
def send_text(msg):
    if DRY_RUN:
        print(f"[DRY-RUN] Telegram: {msg[:120]}...")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "HTML"
        }, timeout=15)
        if r.status_code != 200:
            print(f"Telegram Fehler: {r.status_code} – {r.text[:200]}")
    except Exception as e:
        print(f"Telegram send_text Fehler: {e}")

def send_photo(img, caption):
    if DRY_RUN:
        print(f"[DRY-RUN] Telegram Foto: {caption[:80]}...")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        r = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption
        }, files={"photo": img}, timeout=30)
        if r.status_code != 200:
            print(f"Telegram Foto Fehler: {r.status_code}")
    except Exception as e:
        print(f"Telegram send_photo Fehler: {e}")

# ── Journal ───────────────────────────────────────────────────
def schreibe_journal(asset_name, signal, kurs, details, sw, seu):
    try:
        import csv
        from pathlib import Path

        journal_file = "journal.csv"
        file_exists = Path(journal_file).exists()

        with open(journal_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(JOURNAL_HEADER)

            writer.writerow([
                datetime.now().strftime("%d.%m.%Y %H:%M"),
                asset_name,
                signal,
                round(kurs, 2),
                round(details.get("sma200", 0), 2),
                round(details.get("rsi", 0), 1),
                details.get("punkte", 0),
                round(details.get("stop_loss", 0), 2),
                round(details.get("take_profit", 0), 2),
                sw,
                seu,
                "offen",        # Status
                "",             # Ergebnis
                "",             # Geschlossen_am
                "Paper Trading"
            ])
        print(f"  Journal CSV: {asset_name} gespeichert")
    except Exception as e:
        print(f"  Journal CSV Fehler: {e}")

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
                "status": "offen",
                "ergebnis": "",
                "kommentar": "Paper Trading"
            }
            r = requests.post(sheets_url, data=json.dumps(payload),
                            headers={"Content-Type": "application/json"}, timeout=10)
            print(f"  Journal Sheets: {asset_name} – {r.status_code}")
    except Exception as e:
        print(f"  Journal Sheets Fehler: {e}")

# ── Sentiment (mit Caching) ───────────────────────────────────
_sentiment_cache = {}

def get_sentiment(kat="welt"):
    if kat in _sentiment_cache:
        return _sentiment_cache[kat]
    scores = []
    for url in NEWS_FEEDS.get(kat, []):
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:10]:
                text = e.get("title", "") + " " + e.get("summary", "")
                scores.append(analyzer.polarity_scores(text)["compound"])
        except Exception:
            pass
    result = round(sum(scores) / len(scores), 3) if scores else 0.0
    _sentiment_cache[kat] = result
    return result

def sentiment_emoji(s):
    if s > 0.2:  return "😊 Positiv"
    if s < -0.2: return "😟 Negativ"
    return "😐 Neutral"

# ── Daten-Laden (mit Retry) ───────────────────────────────────
def _get_crypto_inner(coin_id):
    r = requests.get(
        f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
        params={"vs_currency": "eur", "days": "300", "interval": "daily"},
        timeout=15)
    r.raise_for_status()
    data = r.json()
    if "prices" not in data:
        return None, None
    return (
        [p[1] for p in data["prices"]],
        [datetime.fromtimestamp(p[0] / 1000) for p in data["prices"]]
    )

def get_crypto(coin_id):
    result = mit_retry(_get_crypto_inner, coin_id)
    return result if result else (None, None)

def _get_aktie_inner(ticker):
    with _yf_lock:
        df = yf.download(ticker, period="300d", interval="1d", progress=False, auto_adjust=True)
    if df.empty or len(df) < 50:
        return None, None
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    preise = [float(x) for x in close.values]
    daten  = [x.to_pydatetime() for x in df.index]
    return preise, daten

def get_aktie(ticker):
    result = mit_retry(_get_aktie_inner, ticker)
    return result if result else (None, None)

# ── Technische Indikatoren ────────────────────────────────────
def sma(p, n):
    return pd.Series(p).rolling(n).mean()

def rsi_val(p, n=14):
    s = pd.Series(p)
    d = s.diff()
    g = d.where(d > 0, 0).rolling(n).mean()
    l = -d.where(d < 0, 0).rolling(n).mean()
    avg_loss = float(l.iloc[-1])
    if avg_loss == 0:
        return 100.0
    return float((100 - (100 / (1 + (g / l)))).iloc[-1])

def macd_val(p):
    s = pd.Series(p)
    m = s.ewm(span=12).mean() - s.ewm(span=26).mean()
    return float(m.iloc[-1]), float(m.ewm(span=9).mean().iloc[-1])

def atr_val(p, n=14):
    """ATR mit echtem True Range (Close-to-Close Proxy)."""
    s = pd.Series(p)
    tr = s.diff().abs()
    tr.iloc[0] = 0
    return float(tr.rolling(n).mean().iloc[-1])

# ── Signal-Berechnung (synchron mit backtest.py) ──────────────
def berechne_signal(preise, sw=0.0, seu=0.0, kauf_schwelle=8, verk_schwelle=3):
    """
    Einheitliche Signalberechnung für Bot und Backtest.
    Gibt (signal, punkte, details) zurück.
    """
    if len(preise) < 200:
        return "WARTEN", 0, {}

    aktuell = float(preise[-1])
    s200 = float(sma(preise, 200).iloc[-1])
    s50  = float(sma(preise, 50).iloc[-1])
    r    = rsi_val(preise)
    m, ms = macd_val(preise)
    a    = atr_val(preise)
    sentiment = (sw * 0.3) + (seu * 0.2)

    punkte = 0
    if aktuell > s200: punkte += 3
    if aktuell > s50:  punkte += 2
    if m > ms:         punkte += 2
    if r < 70:         punkte += 1
    if r > 30:         punkte += 1
    if sentiment > 0.1: punkte += 2

    bb_m = float(pd.Series(preise).rolling(20).mean().iloc[-1])
    bb_s = float(pd.Series(preise).rolling(20).std().iloc[-1])
    if aktuell < (bb_m + 2 * bb_s):
        punkte += 1

    sl = aktuell - (a * 3)
    tp = aktuell + (a * 8)
    ps = (KAPITAL * MAX_RISIKO) / (aktuell - sl) if aktuell > sl else 0

    details = {
        "sma200": s200, "sma50": s50, "rsi": r,
        "macd": m, "atr": a,
        "stop_loss": sl, "take_profit": tp,
        "position_size": ps, "punkte": punkte
    }

    if punkte >= kauf_schwelle:
        return "KAUFEN", punkte, details
    if punkte <= verk_schwelle:
        return "VERKAUFEN", punkte, details
    return "HALTEN", punkte, details

# ── Chart ─────────────────────────────────────────────────────
def erstelle_chart(preise, daten, name, signal, details):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8),
                                    gridspec_kw={'height_ratios': [3, 1]})
    fig.patch.set_facecolor('#1e1e2e')
    ax1.set_facecolor('#1e1e2e')

    ax1.plot(daten[-100:], preise[-100:], color='#89b4fa', linewidth=2, label='Kurs')
    ax1.plot(daten[-100:], sma(preise, 200).values[-100:],
             color='#f9e2af', linewidth=2, linestyle='--', label='SMA200')
    ax1.plot(daten[-100:], sma(preise, 50).values[-100:],
             color='#a6e3a1', linewidth=1.5, linestyle='--', label='SMA50')

    s = pd.Series(preise)
    bb_m = s.rolling(20).mean()
    bb_s = s.rolling(20).std()
    ax1.fill_between(daten[-100:],
                     (bb_m + 2 * bb_s).values[-100:],
                     (bb_m - 2 * bb_s).values[-100:],
                     alpha=0.1, color='#cba6f7')

    ax1.axhline(y=details["stop_loss"], color='#f38ba8', linestyle=':',
                linewidth=1.5, label=f'SL: {details["stop_loss"]:.0f}')
    ax1.axhline(y=details["take_profit"], color='#a6e3a1', linestyle=':',
                linewidth=1.5, label=f'TP: {details["take_profit"]:.0f}')

    farbe = '#a6e3a1' if signal == "KAUFEN" else \
            '#f38ba8' if signal == "VERKAUFEN" else '#f9e2af'
    ax1.set_title(
        f"{name} – {signal} (Score: {details['punkte']}/12)",
        color=farbe, fontsize=14, fontweight='bold')
    ax1.tick_params(colors='white')
    ax1.legend(facecolor='#313244', labelcolor='white', fontsize=8)
    ax1.grid(color='#313244', linewidth=0.5)
    for spine in ax1.spines.values():
        spine.set_edgecolor('#313244')

    ax2.set_facecolor('#1e1e2e')
    s2 = pd.Series(preise)
    d2 = s2.diff()
    g2 = d2.where(d2 > 0, 0).rolling(14).mean()
    l2 = -d2.where(d2 < 0, 0).rolling(14).mean()
    rsi_v = (100 - (100 / (1 + (g2 / l2)))).values[-100:]
    ax2.plot(daten[-100:], rsi_v, color='#cba6f7', linewidth=1.5)
    ax2.axhline(y=70, color='#f38ba8', linestyle='--', linewidth=1)
    ax2.axhline(y=30, color='#a6e3a1', linestyle='--', linewidth=1)
    ax2.set_ylim(0, 100)
    ax2.set_ylabel('RSI', color='white')
    ax2.tick_params(colors='white')
    ax2.grid(color='#313244', linewidth=0.5)
    for spine in ax2.spines.values():
        spine.set_edgecolor('#313244')

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    buf.seek(0)
    plt.close()
    return buf

# ── Health-Check ──────────────────────────────────────────────
def health_check():
    """Prüft alle Voraussetzungen vor dem Start."""
    fehler = []
    if not TELEGRAM_TOKEN and not DRY_RUN:
        fehler.append("TELEGRAM_TOKEN fehlt")
    if not TELEGRAM_CHAT_ID and not DRY_RUN:
        fehler.append("TELEGRAM_CHAT_ID fehlt")
    try:
        test = yf.download("SPY", period="1d", progress=False, auto_adjust=True)
        if test.empty:
            fehler.append("yfinance liefert keine Daten")
    except Exception as e:
        fehler.append(f"yfinance Fehler: {e}")

    if fehler:
        print(f"Health-Check FEHLGESCHLAGEN: {fehler}")
        return False
    print("Health-Check OK")
    return True

# ── Parallelisierte Asset-Analyse ─────────────────────────────
def analysiere_asset(asset, sw, seu):
    """Analysiert ein einzelnes Asset (für ThreadPoolExecutor)."""
    try:
        print(f"  Analysiere {asset['name']}...")
        if asset["typ"] == "crypto":
            preise, daten = get_crypto(asset["id"])
        else:
            preise, daten = get_aktie(asset["id"])

        if preise is None or len(preise) < 50:
            return None

        signal, punkte, details = berechne_signal(preise, sw, seu)
        if signal == "WARTEN":
            return None

        # ── FIX: Invertierte Logik für Short-ETFs ────────────
        if asset.get("short"):
            if signal == "KAUFEN":
                signal = "VERKAUFEN"
            elif signal == "VERKAUFEN":
                signal = "KAUFEN"
            # Stop-Loss und Take-Profit tauschen (Short-Logik)
            aktuell = float(preise[-1])
            atr = details["atr"]
            details["stop_loss"]   = aktuell + (atr * 3)
            details["take_profit"] = aktuell - (atr * 8)

        return {
            "asset": asset,
            "preise": preise,
            "daten": daten,
            "signal": signal,
            "punkte": punkte,
            "details": details,
        }
    except Exception as e:
        print(f"  Fehler bei {asset['name']}: {e}")
        return None

# ── Datenfehler-Check ─────────────────────────────────────────
def pruefe_datenfehler(ergebnisse):
    """Prüft ob verschiedene Assets identische Kursdaten bekommen haben."""
    warnungen = []
    preis_fingerprints = {}
    for e in ergebnisse:
        if e is None or e["preise"] is None or len(e["preise"]) < 5:
            continue
        fp = tuple(round(p, 4) for p in e["preise"][-5:])
        name = e["asset"]["name"]
        if fp in preis_fingerprints:
            anderer = preis_fingerprints[fp]
            warnung = f"⚠️ DATENFEHLER: {name} hat identische Kurse wie {anderer}!"
            warnungen.append(warnung)
            print(warnung)
        else:
            preis_fingerprints[fp] = name
    return warnungen

# ══════════════════════════════════════════════════════════════
# P&L-Tracking: Automatische Gewinn/Verlust-Berechnung
# ══════════════════════════════════════════════════════════════

def _asset_lookup():
    """Erstellt ein Mapping von Asset-Name zu Asset-Dict."""
    return {a["name"]: a for a in ASSETS}

def hole_aktuellen_kurs(asset_name):
    """Holt den aktuellen Kurs für ein Asset anhand des Namens."""
    lookup = _asset_lookup()
    asset = lookup.get(asset_name)
    if not asset:
        print(f"  P&L: Asset '{asset_name}' nicht in ASSETS gefunden")
        return None
    try:
        if asset["typ"] == "crypto":
            preise, _ = get_crypto(asset["id"])
        else:
            preise, _ = get_aktie(asset["id"])
        if preise and len(preise) > 0:
            return float(preise[-1])
    except Exception as e:
        print(f"  P&L: Kursfehler für {asset_name}: {e}")
    return None

def pruefe_offene_positionen():
    """
    Prüft alle offenen Positionen in journal.csv.
    Holt aktuelle Kurse und prüft ob SL/TP erreicht wurde.
    Gibt Liste der geschlossenen Positionen zurück.
    """
    import csv
    from pathlib import Path

    journal_file = "journal.csv"
    if not Path(journal_file).exists():
        print("  P&L: Keine journal.csv gefunden")
        return []

    # CSV einlesen
    with open(journal_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        zeilen = list(reader)

    if not zeilen:
        print("  P&L: Journal ist leer")
        return []

    # Migration: Fehlende Spalten erkennen
    hat_status = "Status" in (fieldnames or [])

    geschlossene = []
    geaendert = False
    kurs_cache = {}  # Kurse pro Asset cachen

    for zeile in zeilen:
        # Migration: Status-Spalte ergänzen wenn fehlend
        if not hat_status:
            zeile.setdefault("Status", "offen")
            zeile.setdefault("Ergebnis", "")
            zeile.setdefault("Geschlossen_am", "")
            geaendert = True

        status = zeile.get("Status", "offen").strip()
        if not status:
            status = "offen"
            zeile["Status"] = "offen"

        # Nur offene Positionen prüfen
        if status != "offen":
            continue

        asset_name = zeile.get("Asset", "").strip()
        signal = zeile.get("Signal", "").strip()

        # Stop-Loss und Take-Profit parsen
        try:
            sl = float(zeile.get("Stop Loss", "0"))
            tp = float(zeile.get("Take Profit", "0"))
            einstieg = float(zeile.get("Kurs", "0"))
        except (ValueError, TypeError):
            continue

        # NaN oder 0 überspringen
        if sl == 0 or tp == 0 or einstieg == 0:
            continue
        if math.isnan(sl) or math.isnan(tp) or math.isnan(einstieg):
            continue

        # Aktuellen Kurs holen (gecacht)
        if asset_name not in kurs_cache:
            kurs_cache[asset_name] = hole_aktuellen_kurs(asset_name)
        aktuell = kurs_cache.get(asset_name)

        if aktuell is None:
            continue

        # P&L-Logik
        ist_kauf = "KAUFEN" in signal
        ist_verkauf = "VERKAUFEN" in signal

        # Short-ETF erkennen
        lookup = _asset_lookup()
        asset_info = lookup.get(asset_name, {})
        ist_short = asset_info.get("short", False)

        ergebnis_pct = None
        grund = ""

        if ist_kauf:
            if ist_short:
                # Short-ETF KAUFEN: SL über Kurs, TP unter Kurs
                if aktuell >= sl:
                    ergebnis_pct = ((aktuell - einstieg) / einstieg) * 100
                    grund = "Stop-Loss"
                elif aktuell <= tp:
                    ergebnis_pct = ((aktuell - einstieg) / einstieg) * 100
                    grund = "Take-Profit"
            else:
                # Normal KAUFEN: Verlust wenn unter SL, Gewinn wenn über TP
                if aktuell <= sl:
                    ergebnis_pct = ((aktuell - einstieg) / einstieg) * 100
                    grund = "Stop-Loss"
                elif aktuell >= tp:
                    ergebnis_pct = ((aktuell - einstieg) / einstieg) * 100
                    grund = "Take-Profit"

        elif ist_verkauf:
            if ist_short:
                # Short-ETF VERKAUFEN (= long auf Basiswert)
                if aktuell <= sl:
                    ergebnis_pct = ((einstieg - aktuell) / einstieg) * 100
                    grund = "Stop-Loss"
                elif aktuell >= tp:
                    ergebnis_pct = ((einstieg - aktuell) / einstieg) * 100
                    grund = "Take-Profit"
            else:
                # Normal VERKAUFEN: Gewinn wenn Kurs fällt
                if aktuell >= tp:
                    ergebnis_pct = ((einstieg - aktuell) / einstieg) * 100
                    grund = "Take-Profit"
                elif aktuell <= sl:
                    ergebnis_pct = ((einstieg - aktuell) / einstieg) * 100
                    grund = "Stop-Loss"

        if ergebnis_pct is not None:
            zeile["Status"] = "geschlossen"
            zeile["Ergebnis"] = f"{ergebnis_pct:+.2f}%"
            zeile["Geschlossen_am"] = datetime.now().strftime("%d.%m.%Y %H:%M")
            geaendert = True
            geschlossene.append({
                "asset": asset_name,
                "signal": signal,
                "einstieg": einstieg,
                "aktuell": aktuell,
                "ergebnis": ergebnis_pct,
                "grund": grund,
                "datum": zeile.get("Datum", "")
            })
            print(f"  P&L: {asset_name} geschlossen – {ergebnis_pct:+.2f}% ({grund})")

    # Zurückschreiben wenn geändert
    if geaendert:
        with open(journal_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=JOURNAL_HEADER, extrasaction='ignore')
            writer.writeheader()
            for zeile in zeilen:
                writer.writerow(zeile)
        print(f"  P&L: {len(geschlossene)} Position(en) geschlossen, Journal aktualisiert")

    return geschlossene

def sende_pnl_zusammenfassung(geschlossene):
    """Sendet eine Telegram-Nachricht mit den geschlossenen Positionen."""
    if not geschlossene:
        return

    gesamt_pnl = sum(p["ergebnis"] for p in geschlossene)
    gewinner = [p for p in geschlossene if p["ergebnis"] > 0]
    verlierer = [p for p in geschlossene if p["ergebnis"] <= 0]

    msg = "💰 <b>P&amp;L Update – Geschlossene Positionen</b>\n\n"

    for p in geschlossene:
        emoji = "✅" if p["ergebnis"] > 0 else "❌"
        msg += (
            f"{emoji} <b>{p['asset']}</b> ({p['signal']})\n"
            f"   Einstieg: {p['einstieg']:,.2f} → Aktuell: {p['aktuell']:,.2f}\n"
            f"   Ergebnis: {p['ergebnis']:+.2f}% ({p['grund']})\n\n"
        )

    msg += (
        f"📊 <b>Gesamt:</b>\n"
        f"   ✅ {len(gewinner)} Gewinner | ❌ {len(verlierer)} Verlierer\n"
        f"   💰 Gesamt-P&amp;L: {gesamt_pnl:+.2f}%\n"
    )

    send_text(msg)

def zaehle_offene_positionen():
    """Zählt die aktuell offenen Positionen im Journal."""
    import csv
    from pathlib import Path

    journal_file = "journal.csv"
    if not Path(journal_file).exists():
        return 0

    try:
        with open(journal_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return sum(1 for z in reader
                      if z.get("Status", "offen").strip() in ("offen", ""))
    except Exception:
        return 0

# ── Hauptfunktion ─────────────────────────────────────────────
def run_bot():
    start_zeit = time.time()
    modus = "[DRY-RUN] " if DRY_RUN else ""
    print(f"=== {modus}Profi Trading Bot gestartet ===")

    # Health-Check
    if not health_check():
        print("Bot abgebrochen wegen Health-Check Fehler.")
        return

    # ── P&L-Check: Offene Positionen prüfen ──────────────────
    print("=== P&L-Check: Prüfe offene Positionen ===")
    geschlossene_positionen = []
    try:
        geschlossene_positionen = pruefe_offene_positionen()
        if geschlossene_positionen:
            sende_pnl_zusammenfassung(geschlossene_positionen)
        else:
            n_offen = zaehle_offene_positionen()
            if n_offen > 0:
                send_text(f"📋 <b>P&amp;L-Check:</b> {n_offen} offene Position(en) – noch kein SL/TP erreicht.")
            else:
                print("  P&L: Keine offenen Positionen vorhanden")
    except Exception as e:
        print(f"  P&L-Check Fehler: {e}")

    # VIX-Prüfung (mit Stopp bei Überschreitung)
    vix_wert = None
    try:
        vix_df = yf.download("^VIX", period="1d", interval="1d",
                             progress=False, auto_adjust=True)
        vix_close = vix_df["Close"]
        if isinstance(vix_close, pd.DataFrame):
            vix_close = vix_close.iloc[:, 0]
        vix_wert = float(vix_close.iloc[-1])
        print(f"VIX aktuell: {vix_wert:.1f}")
        if vix_wert > VIX_LIMIT:
            send_text(
                f"🚨 <b>NOTBREMSE!</b>\n\n"
                f"VIX Angst-Index: {vix_wert:.1f} (über {VIX_LIMIT})\n"
                f"⛔ Kein Handel heute!\n\n📊 Bot wird beendet."
            )
            return
        else:
            send_text(f"✅ VIX: {vix_wert:.1f} – Markt stabil, Analyse startet...")
    except Exception as e:
        print(f"VIX Fehler: {e}")

    # Sentiment (wird gecacht)
    heute = datetime.now().strftime("%d.%m.%Y %H:%M")
    sw  = get_sentiment("welt")
    seu = get_sentiment("europa")

    send_text(
        f"📊 <b>{modus}Trading Bot – {heute}</b>\n\n"
        f"🌍 Weltstimmung: {sentiment_emoji(sw)} ({sw})\n"
        f"🇪🇺 EU-Stimmung: {sentiment_emoji(seu)} ({seu})\n\n"
        f"🔍 Scanne {len(ASSETS)} Assets (parallel)..."
    )

    # Parallele Analyse mit ThreadPoolExecutor
    ergebnisse = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(analysiere_asset, asset, sw, seu): asset
            for asset in ASSETS
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                ergebnisse.append(result)

    # ── FIX: Datenfehler-Check ───────────────────────────────
    datenfehler = pruefe_datenfehler(ergebnisse)
    if datenfehler:
        send_text(
            "🚨 <b>Datenfehler erkannt!</b>\n\n" +
            "\n".join(datenfehler) +
            "\n\n⚠️ Betroffene Signale mit Vorsicht behandeln!"
        )

    # Sortieren & Top-Signale
    kaufen = sorted(
        [e for e in ergebnisse if e["signal"] == "KAUFEN"],
        key=lambda x: -x["punkte"]
    )[:5]
    verkaufen = sorted(
        [e for e in ergebnisse if e["signal"] == "VERKAUFEN"],
        key=lambda x: x["punkte"]
    )[:3]
    top = kaufen + verkaufen

    if not top:
        send_text("🟡 Heute keine klaren Signale – Markt abwarten.")
    else:
        send_text(f"🏆 <b>Top {len(top)} Signale heute:</b>")
        for e in top:
            asset   = e["asset"]
            details = e["details"]
            aktuell = e["preise"][-1]
            signal_text = "🟢 KAUFEN" if e["signal"] == "KAUFEN" else "🔴 VERKAUFEN"
            short_hinweis = " (Short-ETF)" if asset.get("short") else ""

            nachricht = (
                f"{asset['symbol']} <b>{asset['name']}</b>{short_hinweis}\n"
                f"💶 Kurs: {aktuell:,.2f}\n"
                f"Signal: {signal_text} (Score: {e['punkte']}/12)\n"
                f"SMA200: {details['sma200']:,.2f}\n"
                f"RSI: {details['rsi']:.1f}\n"
                f"🛑 Stop Loss: {details['stop_loss']:,.2f}\n"
                f"🎯 Take Profit: {details['take_profit']:,.2f}\n"
                f"⚠️ Paper Trading"
            )
            try:
                chart = erstelle_chart(
                    e["preise"], e["daten"],
                    asset["name"], e["signal"], details
                )
                send_photo(chart, nachricht)
            except Exception as ex:
                print(f"  Chart-Fehler {asset['name']}: {ex}")
                send_text(nachricht)

            schreibe_journal(
                asset["name"], signal_text, aktuell, details, sw, seu
            )

    # Zusammenfassung
    laufzeit = round(time.time() - start_zeit, 1)
    n_halten = len([e for e in ergebnisse if e["signal"] == "HALTEN"])
    n_offen  = zaehle_offene_positionen()

    zusammenfassung = (
        f"✅ <b>{modus}Analyse abgeschlossen!</b>\n\n"
        f"📊 {len(ergebnisse)} Assets analysiert\n"
        f"🟢 {len(kaufen)} Kaufsignale\n"
        f"🔴 {len(verkaufen)} Verkaufssignale\n"
        f"🟡 {n_halten} Halten\n"
        f"📋 {n_offen} offene Positionen\n"
    )
    if geschlossene_positionen:
        zusammenfassung += f"💰 {len(geschlossene_positionen)} Position(en) heute geschlossen\n"
    zusammenfassung += f"⏱️ Laufzeit: {laufzeit}s\n"
    if vix_wert:
        zusammenfassung += f"📈 VIX: {vix_wert:.1f}\n"
    if datenfehler:
        zusammenfassung += f"⚠️ {len(datenfehler)} Datenfehler erkannt!\n"
    zusammenfassung += "⚠️ Nur Paper Trading!"

    send_text(zusammenfassung)
    print(f"=== Bot fertig ({laufzeit}s) ===")


if __name__ == "__main__":
    run_bot()
