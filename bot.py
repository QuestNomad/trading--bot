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

# ââ Konfiguration âââââââââââââââââââââââââââââââââââââââââââââ
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
KAPITAL = 10000
MAX_RISIKO = 0.01
VIX_LIMIT = 30
MAX_RETRIES = 3
RETRY_DELAY = 5

# ââ Risk Management (sync mit arena_backtest.py) ââââââââââââââ
KELLY_FRACTION = 0.0694  # Half Kelly = 6.94% pro Position
MAX_EXPOSURE = 0.80      # Max 80% Gesamtexposure
MAX_POSITIONS_PER_SECTOR = 4

# ââ Bollinger/RSI/ATR Parameter (sync mit arena_backtest.py) ââ
BB_PERIOD = 20
RSI_PERIOD = 14
ATR_SL_MULTIPLIER = 3.0  # Trailing Stop = 3x ATR
BUY_THRESHOLD = 8
SELL_THRESHOLD = 3

# ââ Trading 212 GebÃ¼hren ââââââââââââââââââââââââââââââââââââââ
TRADING_FEE = 0.0015    # 0.15% FX-Fee
SPREAD_COST = 0.0005    # 0.05% Spread
SLIPPAGE_COST = 0.001   # 0.10% Slippage
TOTAL_COST = TRADING_FEE + SPREAD_COST + SLIPPAGE_COST  # 0.30%

# ââ Sektor-Zuordnung (sync mit arena_backtest.py) âââââââââââââ
SECTORS = {
    "Tech": ["AAPL", "MSFT", "GOOGL", "NVDA", "META"],
    "Consumer": ["AMZN", "TSLA"],
    "Finance": ["DBK.DE", "BNP.PA", "UBSG.SW"],
    "Auto": ["7203.T"],
    "Entertainment": ["6758.T"],
    "Defense": ["RHM.DE"],
    "Aerospace": ["AIR.DE"],
    "Ecommerce": ["ZAL.DE", "9988.HK"],
    "Delivery": ["DHER.DE"],
    "Internet": ["0700.HK"],
    "Index_EU": ["EXS1.DE", "SAP.DE"],
    "Index_US": ["SPY", "IWM"],
    "Index_Asia": ["EWJ", "FXI"],
    "EM": ["INDA", "EWZ", "VWO"],
    "Commodities": ["GC=F", "SI=F", "HG=F", "BZ=F", "ZW=F"],
    "Crypto": ["bitcoin", "ethereum"],
    "Short": ["XSPS.L", "DXSN.DE", "QQQS.L", "BITI"],
}

ASSET_TO_SECTOR = {}
for sector, assets in SECTORS.items():
    for asset_id in assets:
        ASSET_TO_SECTOR[asset_id] = sector

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

# ââ Journal-Header (erweitert fÃ¼r Trailing Stop) ââââââââââââââ
JOURNAL_HEADER = [
    "Datum", "Asset", "Signal", "Kurs", "SMA20", "RSI", "Score",
    "Stop Loss", "Trailing_Stop", "Sentiment Welt", "Sentiment EU",
    "Status", "Ergebnis", "Geschlossen_am", "Kommentar"
]

# ââ 38 eindeutige Assets ââââââââââââââââââââââââââââââââââââââââ
ASSETS = [
    {"name": "Bitcoin",       "typ": "crypto", "id": "bitcoin",    "symbol": "BTC"},
    {"name": "Ethereum",      "typ": "crypto", "id": "ethereum",   "symbol": "ETH"},
    {"name": "S&P 500",       "typ": "aktie",  "id": "SPY",        "symbol": "SPY"},
    {"name": "Apple",         "typ": "aktie",  "id": "AAPL",       "symbol": "AAPL"},
    {"name": "Nvidia",        "typ": "aktie",  "id": "NVDA",       "symbol": "NVDA"},
    {"name": "Tesla",         "typ": "aktie",  "id": "TSLA",       "symbol": "TSLA"},
    {"name": "Microsoft",     "typ": "aktie",  "id": "MSFT",       "symbol": "MSFT"},
    {"name": "Amazon",        "typ": "aktie",  "id": "AMZN",       "symbol": "AMZN"},
    {"name": "Meta",          "typ": "aktie",  "id": "META",       "symbol": "META"},
    {"name": "Google",        "typ": "aktie",  "id": "GOOGL",      "symbol": "GOOGL"},
    {"name": "DAX ETF",       "typ": "aktie",  "id": "EXS1.DE",    "symbol": "DAX"},
    {"name": "SAP",           "typ": "aktie",  "id": "SAP.DE",     "symbol": "SAP"},
    {"name": "Rheinmetall",   "typ": "aktie",  "id": "RHM.DE",     "symbol": "RHM"},
    {"name": "Airbus",        "typ": "aktie",  "id": "AIR.DE",     "symbol": "AIR"},
    {"name": "Zalando",       "typ": "aktie",  "id": "ZAL.DE",     "symbol": "ZAL"},
    {"name": "Delivery Hero", "typ": "aktie",  "id": "DHER.DE",    "symbol": "DHER"},
    {"name": "Deutsche Bank", "typ": "aktie",  "id": "DBK.DE",     "symbol": "DBK"},
    {"name": "BNP Paribas",   "typ": "aktie",  "id": "BNP.PA",     "symbol": "BNP"},
    {"name": "UBS",           "typ": "aktie",  "id": "UBSG.SW",    "symbol": "UBS"},
    {"name": "Nikkei ETF",    "typ": "aktie",  "id": "EWJ",        "symbol": "EWJ"},
    {"name": "Toyota",        "typ": "aktie",  "id": "7203.T",     "symbol": "Toyota"},
    {"name": "Sony",          "typ": "aktie",  "id": "6758.T",     "symbol": "Sony"},
    {"name": "China ETF",     "typ": "aktie",  "id": "FXI",        "symbol": "FXI"},
    {"name": "Alibaba HK",    "typ": "aktie",  "id": "9988.HK",    "symbol": "Alibaba"},
    {"name": "Tencent",       "typ": "aktie",  "id": "0700.HK",    "symbol": "Tencent"},
    {"name": "Indien ETF",    "typ": "aktie",  "id": "INDA",       "symbol": "INDA"},
    {"name": "Brasilien ETF", "typ": "aktie",  "id": "EWZ",        "symbol": "EWZ"},
    {"name": "EM ETF",        "typ": "aktie",  "id": "VWO",        "symbol": "VWO"},
    {"name": "Russell 2000",  "typ": "aktie",  "id": "IWM",        "symbol": "IWM"},
    {"name": "Gold",          "typ": "aktie",  "id": "GC=F",       "symbol": "Gold"},
    {"name": "Silber",        "typ": "aktie",  "id": "SI=F",       "symbol": "Silber"},
    {"name": "Oel",           "typ": "aktie",  "id": "BZ=F",       "symbol": "Oel"},
    {"name": "Kupfer",        "typ": "aktie",  "id": "HG=F",       "symbol": "Kupfer"},
    {"name": "Weizen",        "typ": "aktie",  "id": "ZW=F",       "symbol": "Weizen"},
    {"name": "Short S&P 500", "typ": "aktie",  "id": "XSPS.L",    "symbol": "XSPS", "short": True},
    {"name": "Short DAX",     "typ": "aktie",  "id": "DXSN.DE",   "symbol": "DXSN", "short": True},
    {"name": "Short Nasdaq",  "typ": "aktie",  "id": "QQQS.L",    "symbol": "QQQS", "short": True},
    {"name": "Short Krypto",  "typ": "aktie",  "id": "BITI",       "symbol": "Krypto Short", "short": True},
]

# ââ Retry-Wrapper âââââââââââââââââââââââââââââââââââââââââââââ
def mit_retry(func, *args, retries=MAX_RETRIES, delay=RETRY_DELAY):
    for versuch in range(retries):
        try:
            return func(*args)
        except Exception as e:
            print(f"  Retry {versuch+1}/{retries} fuer {func.__name__}: {e}")
            if versuch < retries - 1:
                time.sleep(delay)
    return None

# ââ Telegram ââââââââââââââââââââââââââââââââââââââââââââââââââ
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
            print(f"Telegram Fehler: {r.status_code} - {r.text[:200]}")
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

# ââ Journal âââââââââââââââââââââââââââââââââââââââââââââââââââ
def schreibe_journal(asset_name, signal, kurs, details, sw, seu):
    if kurs is None or not math.isfinite(kurs) or kurs <= 0:
        print(f"  Journal SKIP: {asset_name} ungueltiger Kurs {kurs}")
        return
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
                round(details.get("sma20", 0), 2),
                round(details.get("rsi", 0), 1),
                details.get("punkte", 0),
                round(details.get("stop_loss", 0), 2),
                round(details.get("trailing_stop", details.get("stop_loss", 0)), 2),
                sw,
                seu,
                "offen",
                "",
                "",
                "Paper Trading - Arena Sync"
            ])
        print(f"  Journal CSV: {asset_name} gespeichert")
    except Exception as e:
        print(f"  Journal CSV Fehler: {e}")

# ââ Sentiment âââââââââââââââââââââââââââââââââââââââââââââââââ
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
    if s > 0.2: return "Positiv"
    if s < -0.2: return "Negativ"
    return "Neutral"

# ââ Daten-Laden âââââââââââââââââââââââââââââââââââââââââââââââ
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
    close = close.dropna()
    if len(close) < 50:
        print(f"  WARN: {ticker} nach NaN-Filter nur {len(close)} Werte -> skip")
        return None, None
    preise = [float(x) for x in close.values]
    daten = [x.to_pydatetime() for x in df.index]
    if not math.isfinite(preise[-1]) or preise[-1] <= 0:
        print(f"  WARN: {ticker} ungueltiger letzter Kurs {preise[-1]}")
        return None, None
    return preise, daten

def get_aktie(ticker):
    result = mit_retry(_get_aktie_inner, ticker)
    return result if result else (None, None)

# ââ Technische Indikatoren ââââââââââââââââââââââââââââââââââââ
def sma(p, n):
    return pd.Series(p).rolling(n).mean()

def rsi_val(p, n=RSI_PERIOD):
    s = pd.Series(p)
    d = s.diff()
    g = d.where(d > 0, 0).rolling(n).mean()
    l = -d.where(d < 0, 0).rolling(n).mean()
    avg_loss = float(l.iloc[-1])
    if avg_loss == 0:
        return 100.0
    return float((100 - (100 / (1 + (g / l)))).iloc[-1])

def atr_val(p, n=14):
    s = pd.Series(p)
    tr = s.diff().abs()
    tr.iloc[0] = 0
    return float(tr.rolling(n).mean().iloc[-1])

# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
# Score Trader Signal (SYNC MIT arena_backtest.py)
# Scoring: Bollinger Bands + RSI + SMA20
# Exit: Trailing Stop-Loss (3x ATR)
# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
def berechne_signal(preise, sw=0.0, seu=0.0, kauf_schwelle=BUY_THRESHOLD, verk_schwelle=SELL_THRESHOLD, is_short=False):
    """
    Score Trader Signalberechnung - IDENTISCH mit arena_backtest.py
    Scoring basiert auf Bollinger Bands, RSI und SMA20.
    """
    if len(preise) < 50:
        return "WARTEN", 0, {}

    aktuell = float(preise[-1])
    s = pd.Series(preise)

    # Bollinger Bands (Period 20)
    bb_mean = float(s.rolling(BB_PERIOD).mean().iloc[-1])
    bb_std = float(s.rolling(BB_PERIOD).std().iloc[-1])
    bb_upper = bb_mean + 2 * bb_std
    bb_lower = bb_mean - 2 * bb_std

    # RSI
    r = rsi_val(preise, RSI_PERIOD)

    # SMA20
    sma20 = float(sma(preise, 20).iloc[-1])

    # ATR fuer Trailing Stop
    a = atr_val(preise)

    # ââ Score Berechnung (SYNC mit arena_backtest.py) âââââ
    punkte = 0

    # SMA20: Preis ueber SMA20 = bullish (+3), darunter = bearish (-2)
    if aktuell > sma20:
        punkte += 3
    else:
        punkte -= 2

    # RSI: Ueberverkauft = Kaufgelegenheit (+3), Ueberkauft = Verkauf (-2)
    if r < 30:
        punkte += 3   # Stark ueberverkauft
    elif r > 70:
        punkte -= 2   # Stark ueberkauft
    elif r <= 50:
        punkte += 1   # Leicht bullish

    # Bollinger Bands: Unter unterem Band = Kaufgelegenheit (+3)
    if aktuell < bb_lower:
        punkte += 3   # Unter unterem Band = ueberverkauft
    elif aktuell > bb_upper:
        punkte -= 2   # Ueber oberem Band = ueberkauft

    # Trailing Stop-Loss (3x ATR — Richtung abhaengig von Long/Short)
    if is_short:
        trailing_stop = aktuell + (a * ATR_SL_MULTIPLIER)
    else:
        trailing_stop = aktuell - (a * ATR_SL_MULTIPLIER)

    # Position Sizing: Kelly Fraction
    position_size_pct = KELLY_FRACTION
    position_size_eur = KAPITAL * position_size_pct

    details = {
        "sma20": sma20, "rsi": r,
        "bb_mean": bb_mean, "bb_upper": bb_upper, "bb_lower": bb_lower,
        "atr": a,
        "stop_loss": trailing_stop,
        "trailing_stop": trailing_stop,
        "position_size_pct": position_size_pct,
        "position_size_eur": position_size_eur,
        "punkte": punkte,
        "kosten_pct": TOTAL_COST * 100,
    }

    if punkte >= kauf_schwelle:
        return "KAUFEN", punkte, details
    if punkte <= verk_schwelle:
        return "VERKAUFEN", punkte, details
    return "HALTEN", punkte, details

# ââ Chart âââââââââââââââââââââââââââââââââââââââââââââââââââââ
def erstelle_chart(preise, daten, name, signal, details):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8),
                                    gridspec_kw={'height_ratios': [3, 1]})
    fig.patch.set_facecolor('#1e1e2e')
    ax1.set_facecolor('#1e1e2e')

    ax1.plot(daten[-100:], preise[-100:], color='#89b4fa', linewidth=2, label='Kurs')
    ax1.plot(daten[-100:], sma(preise, 20).values[-100:],
             color='#f9e2af', linewidth=2, linestyle='--', label='SMA20')

    s = pd.Series(preise)
    bb_m = s.rolling(BB_PERIOD).mean()
    bb_s = s.rolling(BB_PERIOD).std()
    ax1.fill_between(daten[-100:],
                     (bb_m + 2 * bb_s).values[-100:],
                     (bb_m - 2 * bb_s).values[-100:],
                     alpha=0.15, color='#cba6f7', label='Bollinger Bands')

    ax1.axhline(y=details["trailing_stop"], color='#f38ba8', linestyle=':',
                linewidth=1.5, label=f'Trailing SL: {details["trailing_stop"]:.0f}')

    farbe = '#a6e3a1' if signal == "KAUFEN" else \
            '#f38ba8' if signal == "VERKAUFEN" else '#f9e2af'
    ax1.set_title(
        f"{name} - {signal} (Score: {details['punkte']}) | Kelly: {details['position_size_pct']*100:.1f}%",
        color=farbe, fontsize=14, fontweight='bold')
    ax1.tick_params(colors='white')
    ax1.legend(facecolor='#313244', labelcolor='white', fontsize=8)
    ax1.grid(color='#313244', linewidth=0.5)
    for spine in ax1.spines.values():
        spine.set_edgecolor('#313244')

    ax2.set_facecolor('#1e1e2e')
    s2 = pd.Series(preise)
    d2 = s2.diff()
    g2 = d2.where(d2 > 0, 0).rolling(RSI_PERIOD).mean()
    l2 = -d2.where(d2 < 0, 0).rolling(RSI_PERIOD).mean()
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

# ââ Health-Check ââââââââââââââââââââââââââââââââââââââââââââââ
def health_check():
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

# ââ Trailing Stop Management ââââââââââââââââââââââââââââââââââ
def aktualisiere_trailing_stops():
    """
    Prueft offene Positionen und aktualisiert Trailing Stop-Loss.
    Der Stop wird nur NACH OBEN bewegt (nie zurueck).
    Schliesst Position wenn Kurs unter Trailing Stop faellt.
    """
    import csv
    from pathlib import Path

    journal_file = "journal.csv"
    if not Path(journal_file).exists():
        return []

    with open(journal_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        zeilen = list(reader)

    if not zeilen:
        return []

    geschlossene = []
    geaendert = False
    kurs_cache = {}

    MAX_CLOSES_PRO_RUN = 3
    closes_this_run = 0

    for zeile in zeilen:
        status = zeile.get("Status", "offen").strip()
        if status != "offen":
            continue

        asset_name = zeile.get("Asset", "").strip()
        signal = zeile.get("Signal", "").strip()

        try:
            einstieg = float(zeile.get("Kurs", "0"))
            alter_trailing = float(zeile.get("Trailing_Stop", zeile.get("Stop Loss", "0")))
        except (ValueError, TypeError):
            continue

        if einstieg == 0 or math.isnan(einstieg):
            continue

        # Aktuellen Kurs holen
        if asset_name not in kurs_cache:
            kurs_cache[asset_name] = hole_aktuellen_kurs(asset_name)
        aktuell = kurs_cache.get(asset_name)
        if aktuell is None:
            continue

        # ATR neu berechnen fuer aktuellen Trailing Stop
        lookup = _asset_lookup()
        asset_info = lookup.get(asset_name)
        if not asset_info:
            continue

        try:
            if asset_info["typ"] == "crypto":
                preise, _ = get_crypto(asset_info["id"])
            else:
                preise, _ = get_aktie(asset_info["id"])
            if not preise or len(preise) < 20:
                continue
            current_atr = atr_val(preise)
        except Exception:
            continue

        ist_kauf = "KAUFEN" in signal
        if not ist_kauf:
            continue
        neuer_stop = aktuell - (current_atr * ATR_SL_MULTIPLIER)
        if neuer_stop > alter_trailing:
            zeile["Trailing_Stop"] = str(round(neuer_stop, 2))
            geaendert = True
        effektiver_stop = max(neuer_stop, alter_trailing)
        if aktuell <= effektiver_stop:
            if closes_this_run >= MAX_CLOSES_PRO_RUN:
                print(f"  WARN: Close-Limit erreicht, {asset_name} uebersprungen")
                continue
            closes_this_run += 1
            ergebnis_pct = ((aktuell - einstieg) / einstieg) * 100 - TOTAL_COST * 100
            zeile["Status"] = "geschlossen"
            zeile["Ergebnis"] = f"{ergebnis_pct:+.2f}%"
            zeile["Geschlossen_am"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            zeile["Kommentar"] = "Trailing Stop erreicht"
            geaendert = True
            geschlossene.append({
                "asset": asset_name,
                "signal": signal,
                "einstieg": einstieg,
                "aktuell": aktuell,
                "ergebnis": ergebnis_pct,
                "grund": "Trailing Stop",
                "datum": zeile.get("Datum", "")
            })
    if geaendert:
        with open(journal_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=JOURNAL_HEADER, extrasaction='ignore')
            writer.writeheader()
            for zeile in zeilen:
                writer.writerow(zeile)

    return geschlossene

# ââ Portfolio State âââââââââââââââââââââââââââââââââââââââââââ
def lade_offene_positionen():
    """Laedt offene Positionen aus journal.csv fuer Exposure/Sektor-Check."""
    import csv
    from pathlib import Path
    journal_file = "journal.csv"
    if not Path(journal_file).exists():
        return []
    positionen = []
    try:
        with open(journal_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for z in reader:
                if z.get("Status", "offen").strip() == "offen":
                    positionen.append(z)
    except Exception:
        pass
    return positionen

def pruefe_exposure_und_sektor(asset_id):
    """
    Prueft ob ein neuer Trade erlaubt ist basierend auf:
    1. Max Exposure (80%)
    2. Max Positionen pro Sektor (4)
    Gibt (erlaubt, grund) zurueck.
    """
    offene = lade_offene_positionen()
    n_offen = len(offene)

    # Exposure Check
    aktuelle_exposure = n_offen * KELLY_FRACTION
    if aktuelle_exposure + KELLY_FRACTION > MAX_EXPOSURE:
        return False, f"Exposure Cap: {aktuelle_exposure*100:.1f}% + {KELLY_FRACTION*100:.1f}% > {MAX_EXPOSURE*100:.0f}%"

    # Sektor Check
    sektor = ASSET_TO_SECTOR.get(asset_id, "Other")
    sektor_count = 0
    lookup = _asset_lookup()
    for pos in offene:
        pos_name = pos.get("Asset", "")
        pos_asset = lookup.get(pos_name, {})
        pos_id = pos_asset.get("id", "")
        pos_sektor = ASSET_TO_SECTOR.get(pos_id, "Other")
        if pos_sektor == sektor:
            sektor_count += 1

    if sektor_count >= MAX_POSITIONS_PER_SECTOR:
        return False, f"Sektor '{sektor}' voll: {sektor_count}/{MAX_POSITIONS_PER_SECTOR}"

    return True, "OK"

# ââ Hilfsfunktionen âââââââââââââââââââââââââââââââââââââââââââ
def _asset_lookup():
    return {a["name"]: a for a in ASSETS}

def hole_aktuellen_kurs(asset_name):
    lookup = _asset_lookup()
    asset = lookup.get(asset_name)
    if not asset:
        return None
    try:
        if asset["typ"] == "crypto":
            preise, _ = get_crypto(asset["id"])
        else:
            preise, _ = get_aktie(asset["id"])
        if preise and len(preise) > 0:
            kurs = float(preise[-1])
            if not math.isfinite(kurs) or kurs <= 0:
                print(f"  WARN: NaN/0 Kurs fuer {asset_name}")
                return None
            return kurs
    except Exception as e:
        print(f"  Kursfehler fuer {asset_name}: {e}")
    return None

def zaehle_offene_positionen():
    import csv
    from pathlib import Path
    journal_file = "journal.csv"
    if not Path(journal_file).exists():
        return 0
    try:
        with open(journal_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return sum(1 for z in reader if z.get("Status", "offen").strip() in ("offen", ""))
    except Exception:
        return 0

def ist_bereits_offen(asset_name, signal):
    offene = lade_offene_positionen()
    for pos in offene:
        if pos.get("Asset", "").strip() == asset_name and \
           pos.get("Signal", "").strip() == signal:
            # TTL: Eintraege aelter als 7 Tage ignorieren
            try:
                datum_str = pos.get("Datum", "").strip()
                datum = datetime.strptime(datum_str, "%d.%m.%Y %H:%M")
                if (datetime.now() - datum).days > 7:
                    continue
            except (ValueError, TypeError):
                pass
            return True
    return False

# ââ Asset Analyse âââââââââââââââââââââââââââââââââââââââââââââ
def analysiere_asset(asset, sw, seu):
    try:
        print(f"  Analysiere {asset['name']}...")
        if asset["typ"] == "crypto":
            preise, daten = get_crypto(asset["id"])
        else:
            preise, daten = get_aktie(asset["id"])

        if preise is None or len(preise) < 50:
            return None

        preise = [p for p in preise if p is not None and math.isfinite(p) and p > 0]
        if len(preise) < 50:
            print(f"  {asset['name']}: zu viele NaN-Kurse, skip")
            return None

        preise = [p for p in preise if not math.isnan(p)]
        if len(preise) < 50:
            print(f"  {asset['name']}: zu viele NaN-Kurse, skip")
            return None
        if not math.isfinite(preise[-1]) or preise[-1] <= 0:
            print(f"  {asset['name']}: letzter Kurs ungueltig ({preise[-1]}), skip")
            return None
        is_short = asset.get("short", False)
        signal, punkte, details = berechne_signal(preise, sw, seu, is_short=is_short)
        if signal == "WARTEN":
            return None

        if asset.get("short"):
            if punkte <= -3:
                signal = "KAUFEN"
            else:
                return None

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

# ââ Datenfehler-Check âââââââââââââââââââââââââââââââââââââââââ
def pruefe_datenfehler(ergebnisse):
    warnungen = []
    preis_fingerprints = {}
    for e in ergebnisse:
        if e is None or e["preise"] is None or len(e["preise"]) < 5:
            continue
        fp = tuple(round(p, 4) for p in e["preise"][-5:])
        name = e["asset"]["name"]
        if fp in preis_fingerprints:
            anderer = preis_fingerprints[fp]
            warnung = f"DATENFEHLER: {name} hat identische Kurse wie {anderer}!"
            warnungen.append(warnung)
        else:
            preis_fingerprints[fp] = name
    return warnungen

# ââ P&L Zusammenfassung ââââââââââââââââââââââââââââââââââââââ
def sende_pnl_zusammenfassung(geschlossene):
    if not geschlossene:
        return
    gesamt_pnl = sum(p["ergebnis"] for p in geschlossene)
    gewinner = [p for p in geschlossene if p["ergebnis"] > 0]
    verlierer = [p for p in geschlossene if p["ergebnis"] <= 0]

    msg = "<b>P&amp;L Update - Geschlossene Positionen</b>\n\n"
    for p in geschlossene:
        emoji = "+" if p["ergebnis"] > 0 else "-"
        msg += (
            f"{emoji} <b>{p['asset']}</b> ({p['signal']})\n"
            f"  Einstieg: {p['einstieg']:,.2f} -> Aktuell: {p['aktuell']:,.2f}\n"
            f"  Ergebnis: {p['ergebnis']:+.2f}% ({p['grund']})\n\n"
        )
    msg += (
        f"<b>Gesamt:</b>\n"
        f"  {len(gewinner)} Gewinner | {len(verlierer)} Verlierer\n"
        f"  Gesamt-P&amp;L: {gesamt_pnl:+.2f}%\n"
    )
    send_text(msg)

# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
# HAUPTFUNKTION
# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
def run_bot():
    start_zeit = time.time()
    journal_geschrieben = set()  # Verhindert Duplikate innerhalb eines Runs
    modus = "[DRY-RUN] " if DRY_RUN else ""
    print(f"=== {modus}Score Trader Bot (Arena Sync) gestartet ===")

    if not health_check():
        print("Bot abgebrochen wegen Health-Check Fehler.")
        return

    # ââ Trailing Stop Update: Offene Positionen pruefen ââââ
    print("=== Trailing Stop Update ===")
    geschlossene_positionen = []
    try:
        geschlossene_positionen = aktualisiere_trailing_stops()
        if geschlossene_positionen:
            sende_pnl_zusammenfassung(geschlossene_positionen)
            print(f"  {len(geschlossene_positionen)} Position(en) durch Trailing Stop geschlossen")
        else:
            n_offen = zaehle_offene_positionen()
            if n_offen > 0:
                aktuelle_exposure = n_offen * KELLY_FRACTION * 100
                send_text(f"<b>Trailing Stop Update:</b> {n_offen} offene Position(en), Exposure: {aktuelle_exposure:.1f}%")
    except Exception as e:
        print(f"  Trailing Stop Fehler: {e}")

    # VIX-Pruefung
    vix_wert = None
    try:
        vix_df = yf.download("^VIX", period="1d", interval="1d", progress=False, auto_adjust=True)
        vix_close = vix_df["Close"]
        if isinstance(vix_close, pd.DataFrame):
            vix_close = vix_close.iloc[:, 0]
        vix_wert = float(vix_close.iloc[-1])
        print(f"VIX aktuell: {vix_wert:.1f}")

        if vix_wert > VIX_LIMIT:
            send_text(
                f"<b>NOTBREMSE!</b>\n\n"
                f"VIX: {vix_wert:.1f} (ueber {VIX_LIMIT})\n"
                f"Kein Handel heute!\n\nBot wird beendet."
            )
            return
        else:
            send_text(f"VIX: {vix_wert:.1f} - Markt stabil, Analyse startet...")
    except Exception as e:
        print(f"VIX Fehler: {e}")

    # Sentiment
    heute = datetime.now().strftime("%d.%m.%Y %H:%M")
    sw = get_sentiment("welt")
    seu = get_sentiment("europa")

    n_offen = zaehle_offene_positionen()
    aktuelle_exposure = n_offen * KELLY_FRACTION * 100

    send_text(
        f"<b>{modus}Score Trader - {heute}</b>\n\n"
        f"Weltstimmung: {sentiment_emoji(sw)} ({sw})\n"
        f"EU-Stimmung: {sentiment_emoji(seu)} ({seu})\n"
        f"Offene Positionen: {n_offen} ({aktuelle_exposure:.1f}% Exposure)\n"
        f"Max Exposure: {MAX_EXPOSURE*100:.0f}% | Kelly: {KELLY_FRACTION*100:.1f}%\n\n"
        f"Scanne {len(ASSETS)} Assets..."
    )

    # Parallele Analyse
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

    # Datenfehler-Check
    datenfehler = pruefe_datenfehler(ergebnisse)
    if datenfehler:
        send_text("<b>Datenfehler erkannt!</b>\n\n" + "\n".join(datenfehler))

    # Sortieren & Top-Signale
    kaufen_raw = sorted(
        [e for e in ergebnisse if e["signal"] == "KAUFEN"],
        key=lambda x: -x["punkte"]
    )

    # ââ Exposure Cap & Sector Filter anwenden âââââââââââââ
    kaufen = []
    exposure_blocked = 0
    sector_blocked = 0

    for e in kaufen_raw:
        asset_id = e["asset"]["id"]
        erlaubt, grund = pruefe_exposure_und_sektor(asset_id)
        if erlaubt:
            kaufen.append(e)
            if len(kaufen) >= 5:
                break
        else:
            if "Exposure" in grund:
                exposure_blocked += 1
            else:
                sector_blocked += 1
            print(f"  Trade geblockt: {e['asset']['name']} - {grund}")

    verkaufen = sorted(
        [e for e in ergebnisse if e["signal"] == "VERKAUFEN"],
        key=lambda x: x["punkte"]
    )[:3]

    # Risk Management Status
    if exposure_blocked > 0 or sector_blocked > 0:
        send_text(
            f"<b>Risk Management:</b>\n"
            f"  Exposure Cap: {exposure_blocked} Trade(s) geblockt\n"
            f"  Sector Filter: {sector_blocked} Trade(s) geblockt"
        )

    top = kaufen + verkaufen
    if not top:
        send_text("Heute keine klaren Signale - Markt abwarten.")
    else:
        send_text(f"<b>Top {len(top)} Signale heute:</b>")
        for e in top:
            asset = e["asset"]
            details = e["details"]
            aktuell = e["preise"][-1]
            signal_text = "KAUFEN" if e["signal"] == "KAUFEN" else "VERKAUFEN"
            short_hinweis = " (Short-ETF)" if asset.get("short") else ""

            nachricht = (
                f"<b>{asset['symbol']} {asset['name']}</b>{short_hinweis}\n"
                f"Kurs: {aktuell:,.2f}\n"
                f"Signal: {signal_text} (Score: {e['punkte']})\n"
                f"SMA20: {details['sma20']:,.2f} | RSI: {details['rsi']:.1f}\n"
                f"BB: [{details['bb_lower']:,.2f} - {details['bb_upper']:,.2f}]\n"
                f"Trailing SL: {details['trailing_stop']:,.2f}\n"
                f"Position: {details['position_size_pct']*100:.1f}% = {details['position_size_eur']:,.0f} EUR\n"
                f"Kosten: {details['kosten_pct']:.2f}% pro Trade\n"
                f"Paper Trading (Arena Sync)"
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

            journal_key = f"{asset['name']}_{signal_text}"
            if journal_key in journal_geschrieben:
                print(f"  Skip Journal: {asset['name']} {signal_text} bereits in diesem Run geschrieben")
            elif ist_bereits_offen(asset["name"], signal_text):
                print(f"  Skip Journal: {asset['name']} {signal_text} bereits offen")
            else:
                schreibe_journal(asset["name"], signal_text, aktuell, details, sw, seu)
                journal_geschrieben.add(journal_key)

    # Zusammenfassung
    laufzeit = round(time.time() - start_zeit, 1)
    n_halten = len([e for e in ergebnisse if e["signal"] == "HALTEN"])
    n_offen_neu = zaehle_offene_positionen()
    exposure_neu = n_offen_neu * KELLY_FRACTION * 100

    zusammenfassung = (
        f"<b>{modus}Analyse abgeschlossen!</b>\n\n"
        f"{len(ergebnisse)} Assets analysiert\n"
        f"{len(kaufen)} Kaufsignale (nach Filter)\n"
        f"{len(verkaufen)} Verkaufssignale\n"
        f"{n_halten} Halten\n"
        f"{n_offen_neu} offene Positionen ({exposure_neu:.1f}% Exposure)\n"
    )
    if geschlossene_positionen:
        zusammenfassung += f"{len(geschlossene_positionen)} durch Trailing Stop geschlossen\n"
    if exposure_blocked > 0:
        zusammenfassung += f"{exposure_blocked} durch Exposure Cap geblockt\n"
    if sector_blocked > 0:
        zusammenfassung += f"{sector_blocked} durch Sector Filter geblockt\n"
    zusammenfassung += f"Laufzeit: {laufzeit}s\n"
    if vix_wert:
        zusammenfassung += f"VIX: {vix_wert:.1f}\n"
    zusammenfassung += "Paper Trading (Arena Sync v2)"

    send_text(zusammenfassung)
    print(f"=== Bot fertig ({laufzeit}s) ===")

if __name__ == "__main__":
    run_bot()
