"""
Bot Arena - 7 Trading-Strategien im direkten Vergleich
Laeuft taeglich via GitHub Actions (Mo-Fr nach Marktschluss)

Bots:
  1. Momentum     - Top-10 nach 63-Tage-Rendite, woechentlich rebalanced
  2. Crash Guard  - Buy & Hold SPY mit SMA200-Schutz
  3. Kronos      - SMA20/BB/RSI/ATR Score-System (kauf_schwelle=8, original)
    4. Athena      - Erweitertes 6-Komponenten Score-System (V2, kauf_schwelle=8)
  4. Buy & Hold   - Gleichgewichtet alle 66 Assets
  5. Adaptiv      - Wechselt zwischen Momentum, Crash Guard und Cash je nach VIX
"""

import yfinance as yf
import pandas as pd
import numpy as np
import json
import os
import logging
import requests
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("arena")

# ── 66 US-Assets: Index, Sektor, Einzelaktien, Rohstoff-ETFs, Crypto-ETFs ──
ASSETS = [
    # --- US Index ETFs ---
    "SPY", "QQQ", "IWM", "DIA", "VTI",
    # --- International / EM ETFs ---
    "EFA", "EEM", "VGK", "EWJ", "FXI", "EWT", "AAXJ", "EWZ", "INDA",
    # --- Sektor ETFs ---
    "XLE", "XLF", "XLV", "XLK", "XLI", "XLU", "XLP", "XLY", "XLRE", "XLC",
    "VNQ", "XBI", "ARKK",
    # --- Rohstoff ETFs ---
    "GLD", "SLV", "UNG", "USO", "DBA", "URA",
    # --- Bond ETFs ---
    "TLT", "HYG", "LQD", "BND",
    # --- Crypto ETFs ---
    "IBIT", "BITO", "MSTR", "COIN", "MARA",
    # --- US Tech / Mega Cap ---
    "AAPL", "NVDA", "MSFT", "TSLA", "AMZN", "META", "GOOGL",
    # --- Halbleiter / Tech Growth ---
    "AMD", "AVGO", "PLTR", "SMCI", "SHOP", "TSM", "ASML",
    # --- Volatile / High-Beta ---
    "SOFI", "MRNA", "FSLR", "SE", "NU", "MELI",
    # --- Health / Pharma ---
    "LLY", "NVO",
    # --- Konsum / Energie ---
    "COST", "XOM",
]

ARENA_FILE = "arena_results.json"
STARTKAPITAL = 100_000  # virtuelles Startkapital pro Bot
SPREAD_COST = 0.0005    # 0.05% Spread-Simulation pro Trade

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def sende_telegram(text: str):
    """Sendet eine Nachricht via Telegram Bot API."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram nicht konfiguriert \u2013 Nachricht wird nur geloggt.")
        logger.info(text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=15)
        if resp.status_code != 200:
            logger.error(f"Telegram Fehler: {resp.text}")
    except Exception as e:
        logger.error(f"Telegram Fehler: {e}")


def lade_kurse(tage: int = 252) -> pd.DataFrame:
    """Laedt historische Schlusskurse fuer alle Assets + SPY (fuer SMA200)."""
    ende = datetime.now()
    start = ende - timedelta(days=tage + 100)  # extra Puffer fuer Indikatoren
    logger.info(f"Lade Kursdaten fuer {len(ASSETS)} Assets ({start.date()} bis {ende.date()}) ...")
    data = yf.download(ASSETS, start=start, end=ende, auto_adjust=True, progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"]
    else:
        close = data
    close = close.dropna(how="all")
    logger.info(f"Kursdaten geladen: {close.shape[0]} Tage, {close.shape[1]} Assets")
    return close


def berechne_indikatoren(close: pd.DataFrame) -> dict:
    """Berechnet alle benoetigten technischen Indikatoren."""
    ind = {}

    # SMA
    ind["sma20"] = close.rolling(20).mean()
    ind["sma200_spy"] = close["SPY"].rolling(200).mean() if "SPY" in close.columns else pd.Series(dtype=float)
    ind["sma200"] = close.rolling(200).mean()  # SMA200 fuer alle Assets (Athena)

    # Bollinger Bands (20, 2)
    bb_mid = ind["sma20"]
    bb_std = close.rolling(20).std()
    ind["bb_mid"] = bb_mid
    ind["bb_std"] = bb_std
    ind["bb_upper"] = bb_mid + 2 * bb_std
    ind["bb_lower"] = bb_mid - 2 * bb_std

    # RSI (14)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    ind["rsi"] = 100 - (100 / (1 + rs))

    # ATR (14)
    high = close  # Vereinfachung: Nutze Close als Proxy (kein High/Low via yfinance multi)
    low = close
    tr = high - low  # wird ~0, daher nutzen wir alternative Berechnung
    # Bessere ATR-Naeherung: abs(close - close.shift(1))
    tr = close.diff().abs()
    ind["atr"] = tr.rolling(14).mean()

    # Momentum (63-Tage-Rendite)
    ind["momentum_63"] = close.pct_change(63)

    # VIX (fuer Adaptiv-Bot)
    try:
        vix_data = yf.download("^VIX", period="5d", progress=False)
        if isinstance(vix_data.columns, pd.MultiIndex):
            vix_close = vix_data["Close"]["^VIX"]
        else:
            vix_close = vix_data["Close"]
        ind["vix"] = vix_close.iloc[-1] if len(vix_close) > 0 else 20
    except Exception:
        ind["vix"] = 20  # Fallback

    # Aktuelle Kurse (letzter verfuegbarer Tag)
    ind["aktuell"] = close.iloc[-1].to_dict()

    return ind


def portfolio_wert(bot_state: dict, kurse: dict) -> float:
    """Berechnet den Gesamtwert: Cash + Positionen * aktuelle Kurse."""
    wert = bot_state["kapital"]
    for symbol, menge in bot_state["positionen"].items():
        preis = kurse.get(symbol, 0)
        if preis and not np.isnan(preis):
            wert += menge * preis
    return round(wert, 2)


def kaufe(bot_state: dict, symbol: str, betrag: float, kurs: float) -> bool:
    """Kauft fuer einen bestimmten Betrag. Gibt True zurueck bei Erfolg."""
    if kurs <= 0 or np.isnan(kurs) or betrag <= 0:
        return False
    if bot_state["kapital"] < betrag:
        betrag = bot_state["kapital"]
    if betrag < 1:
        return False
    menge = betrag / kurs
    bot_state["kapital"] -= betrag
    bot_state["positionen"][symbol] = bot_state["positionen"].get(symbol, 0) + menge
    bot_state["trades"] += 1
    return True


def verkaufe(bot_state: dict, symbol: str, kurs: float) -> float:
    """Verkauft die gesamte Position. Gibt den Erloessbetrag zurueck."""
    menge = bot_state["positionen"].get(symbol, 0)
    if menge <= 0 or kurs <= 0 or np.isnan(kurs):
        return 0
    erloes = menge * kurs
    bot_state["kapital"] += erloes
    del bot_state["positionen"][symbol]
    bot_state["trades"] += 1
    return erloes


def verkaufe_alles(bot_state: dict, kurse: dict):
    """Verkauft alle Positionen."""
    for symbol in list(bot_state["positionen"].keys()):
        kurs = kurse.get(symbol, 0)
        if kurs and not np.isnan(kurs):
            verkaufe(bot_state, symbol, kurs)


# ---------------------------------------------------------------------------
# Bot 1: Momentum
# ---------------------------------------------------------------------------

def bot_momentum(state: dict, close: pd.DataFrame, ind: dict, heute: str):
    """
    Top-10 nach 63-Tage-Momentum, gleichgewichtet 10%.
    Woechentliches Rebalancing (Montag).
    Crash-Schutz: Alles verkaufen wenn SPY < SMA200.
    """
    bot = state["bots"]["Momentum"]
    kurse = ind["aktuell"]
    spy_kurs = kurse.get("SPY", 0)
    spy_sma200 = ind["sma200_spy"].iloc[-1] if len(ind["sma200_spy"]) > 0 else 0

    # Crash-Schutz
    if spy_kurs and spy_sma200 and not np.isnan(spy_sma200) and spy_kurs < spy_sma200:
        if bot["positionen"]:
            logger.info("Momentum: CRASH-SCHUTZ \u2013 Verkaufe alles (SPY < SMA200)")
            verkaufe_alles(bot, kurse)
        return

    # Rebalancing nur Montags
    try:
        tag = pd.Timestamp(heute)
        if tag.dayofweek != 0:  # 0 = Montag
            return
    except Exception:
        pass

    # Top-10 nach Momentum
    mom = ind["momentum_63"].iloc[-1].dropna().sort_values(ascending=False)
    top10 = mom.head(10).index.tolist()

    if not top10:
        return

    # Verkaufe alles was nicht mehr in Top-10 ist
    for symbol in list(bot["positionen"].keys()):
        if symbol not in top10:
            verkaufe(bot, symbol, kurse.get(symbol, 0))

    # Berechne Gesamtwert und Zielallokation
    gesamt = portfolio_wert(bot, kurse)
    ziel_pro_asset = gesamt / len(top10)

    # Kaufe / Rebalance
    for symbol in top10:
        kurs = kurse.get(symbol, 0)
        if not kurs or np.isnan(kurs) or kurs <= 0:
            continue
        aktueller_wert = bot["positionen"].get(symbol, 0) * kurs
        diff = ziel_pro_asset - aktueller_wert
        if diff > 100:  # Nur rebalancen wenn Differenz > 100$
            kaufe(bot, symbol, diff, kurs)
        elif diff < -100:
            # Teilverkauf
            ueberschuss_menge = abs(diff) / kurs
            aktuelle_menge = bot["positionen"].get(symbol, 0)
            verkauf_menge = min(ueberschuss_menge, aktuelle_menge)
            if verkauf_menge > 0:
                erloes = verkauf_menge * kurs
                bot["kapital"] += erloes
                bot["positionen"][symbol] = aktuelle_menge - verkauf_menge
                if bot["positionen"][symbol] < 0.0001:
                    del bot["positionen"][symbol]
                bot["trades"] += 1

    logger.info(f"Momentum: Rebalanced auf {len(bot['positionen'])} Positionen")


# ---------------------------------------------------------------------------
# Bot 2: Crash Guard
# ---------------------------------------------------------------------------

def bot_crash_guard(state: dict, close: pd.DataFrame, ind: dict, heute: str):
    """
    Buy & Hold SPY mit SMA200-Schutz.
    Verkaufe wenn SPY < SMA200, kaufe zurueck wenn SPY > SMA200.
    """
    bot = state["bots"]["Crash_Guard"]
    kurse = ind["aktuell"]
    spy_kurs = kurse.get("SPY", 0)
    spy_sma200 = ind["sma200_spy"].iloc[-1] if len(ind["sma200_spy"]) > 0 else 0

    if not spy_kurs or np.isnan(spy_kurs) or spy_kurs <= 0:
        return
    if not spy_sma200 or np.isnan(spy_sma200):
        return

    hat_spy = "SPY" in bot["positionen"] and bot["positionen"]["SPY"] > 0

    if spy_kurs < spy_sma200 and hat_spy:
        # Verkaufe SPY
        verkaufe(bot, "SPY", spy_kurs)
        logger.info("Crash Guard: SPY VERKAUFT (unter SMA200)")
    elif spy_kurs >= spy_sma200 and not hat_spy:
        # Kaufe SPY mit gesamtem Kapital
        kaufe(bot, "SPY", bot["kapital"], spy_kurs)
        logger.info("Crash Guard: SPY GEKAUFT (ueber SMA200)")


# ---------------------------------------------------------------------------
# Bot 3: Kronos (ehemals Score Trader)
# ---------------------------------------------------------------------------

def berechne_score(symbol: str, kurs: float, ind: dict) -> int:
    """
    Score-System wie im Original-Bot:
    - SMA20-Trend: +2 wenn Kurs > SMA20
    - Bollinger: +3 wenn Kurs nahe unterer Band (Kaufgelegenheit)
    - RSI: +2 wenn RSI < 40 (ueberverkauft), +1 wenn RSI 40-50
    - Volumen/Trend: +2 wenn Kurs innerhalb 5% ueber SMA20
    Max Score = ~9-10
    """
    score = 0

    # SMA20
    sma20 = ind["sma20"][symbol].iloc[-1] if symbol in ind["sma20"].columns else np.nan
    if not np.isnan(sma20) and kurs > sma20:
        score += 2
    # Bonus: Kurs nahe SMA20 (innerhalb 5%)
    if not np.isnan(sma20) and sma20 > 0:
        abstand = (kurs - sma20) / sma20
        if 0 <= abstand <= 0.05:
            score += 2

    # Bollinger Bands
    bb_lower = ind["bb_lower"][symbol].iloc[-1] if symbol in ind["bb_lower"].columns else np.nan
    bb_upper = ind["bb_upper"][symbol].iloc[-1] if symbol in ind["bb_upper"].columns else np.nan
    if not np.isnan(bb_lower) and not np.isnan(bb_upper) and bb_upper > bb_lower:
        bb_position = (kurs - bb_lower) / (bb_upper - bb_lower)
        if bb_position < 0.3:
            score += 3
        elif bb_position < 0.5:
            score += 1

    # RSI
    rsi = ind["rsi"][symbol].iloc[-1] if symbol in ind["rsi"].columns else np.nan
    if not np.isnan(rsi):
        if rsi < 40:
            score += 2
        elif rsi < 50:
            score += 1

    return score


def bot_kronos(state: dict, close: pd.DataFrame, ind: dict, heute: str):
    """
    Score-basiertes Trading mit SMA20, BB, RSI, ATR.
    Kaufe wenn Score >= 8. SL 3xATR, Trailing Stop 3xATR.
    """
    bot = state["bots"]["Kronos"]
    kurse = ind["aktuell"]
    kauf_schwelle = 8

    # Pruefe bestehende Positionen auf SL/TP
    if "meta" not in bot:
        bot["meta"] = {}

    for symbol in list(bot["positionen"].keys()):
        kurs = kurse.get(symbol, 0)
        if not kurs or np.isnan(kurs) or kurs <= 0:
            continue

        meta = bot["meta"].get(symbol, {})
        sl = meta.get("sl", 0)
        atr_entry = meta.get("atr", kurs * 0.02)
        high = meta.get("high", kurs)

        # Update trailing stop
        new_high = max(high, kurs)
        trailing_stop = new_high - 3 * atr_entry
        effective_sl = max(sl, trailing_stop)

        if kurs <= effective_sl:
            logger.info(f"Kronos: {symbol} TRAILING-STOP bei {kurs:.2f} (SL={effective_sl:.2f}, High={new_high:.2f})")
            verkaufe(bot, symbol, kurs)
            if symbol in bot["meta"]:
                del bot["meta"][symbol]
        else:
            # Update high watermark
            bot["meta"][symbol]["high"] = round(new_high, 2)

    # Suche neue Kaufgelegenheiten
    for symbol in ASSETS:
        if symbol in bot["positionen"]:
            continue
        kurs = kurse.get(symbol, 0)
        if not kurs or np.isnan(kurs) or kurs <= 0:
            continue

        score = berechne_score(symbol, kurs, ind)

        if score >= kauf_schwelle:
            # ATR fuer SL/TP
            atr = ind["atr"][symbol].iloc[-1] if symbol in ind["atr"].columns else np.nan
            if np.isnan(atr) or atr <= 0:
                atr = kurs * 0.02  # Fallback: 2% des Kurses

            sl = kurs - 3 * atr

            # Investiere max 5% des Portfolios pro Trade
            gesamt = portfolio_wert(bot, kurse)
            betrag = min(gesamt * 0.05, bot["kapital"])

            if betrag > 50:
                if kaufe(bot, symbol, betrag, kurs):
                    bot["meta"][symbol] = {"sl": round(sl, 2), "atr": round(atr, 4), "high": round(kurs, 2), "score": score}
                    logger.info(f"Kronos: KAUF {symbol} Score={score} SL={sl:.2f} ATR={atr:.2f}")


# ---------------------------------------------------------------------------
# Bot 4: Buy & Hold
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Bot 4: Athena (Erweitertes Score-System V2)
# ---------------------------------------------------------------------------

def berechne_score_athena(symbol: str, kurs: float, ind: dict, close: pd.DataFrame) -> int:
    """
    Erweitertes 6-Komponenten Scoring (V2).
    Kern: Backtest-Logik (arena_backtest.py, +863% Return)
    Erweiterung: SMA200, MACD, Momentum-Trend
    Max Score: 14
    """
    score = 0

    # 1. TREND: Kurs ueber SMA20 (+3)
    sma20 = ind["sma20"][symbol].iloc[-1] if symbol in ind["sma20"].columns else np.nan
    if not np.isnan(sma20) and kurs > sma20:
        score += 3

    # 2. PULLBACK: Kurs nahe/unter Mitte des BB (+3)
    bb_mid_val = ind["bb_mid"][symbol].iloc[-1] if symbol in ind["bb_mid"].columns else np.nan
    bb_std_val = ind["bb_std"][symbol].iloc[-1] if symbol in ind["bb_std"].columns else np.nan
    if not np.isnan(bb_mid_val) and not np.isnan(bb_std_val):
        if kurs < bb_mid_val + 0.5 * bb_std_val:
            score += 3

    # 3. RSI: Nicht ueberkauft (+2)
    rsi = ind["rsi"][symbol].iloc[-1] if symbol in ind["rsi"].columns else np.nan
    if not np.isnan(rsi) and rsi < 55:
        score += 2

    # 4. LANGFRIST-TREND: Kurs ueber SMA200 (+2)
    sma200 = ind["sma200"][symbol].iloc[-1] if symbol in ind["sma200"].columns else np.nan
    if not np.isnan(sma200) and kurs > sma200:
        score += 2

    # 5. MOMENTUM: MACD-Histogramm positiv (+2)
    if symbol in close.columns and len(close[symbol].dropna()) >= 35:
        ema12 = close[symbol].ewm(span=12, adjust=False).mean()
        ema26 = close[symbol].ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = (macd_line - signal_line).iloc[-1]
        if not np.isnan(macd_hist) and macd_hist > 0:
            score += 2

    # 6. MOMENTUM-TREND: 63-Tage-Rendite positiv (+2)
    mom = ind["momentum_63"][symbol].iloc[-1] if symbol in ind["momentum_63"].columns else np.nan
    if not np.isnan(mom) and mom > 0.0:
        score += 2

    return score


def bot_athena(state: dict, close: pd.DataFrame, ind: dict, heute: str):
    """
    Athena - Goettin der Strategie.
    Erweitertes 6-Komponenten Scoring (V2).
    Kaufe wenn Score >= 8 (von max 14). SL 3xATR, Trailing Stop.
    """
    bot = state["bots"]["Athena"]
    kurse = ind["aktuell"]
    kauf_schwelle = 8

    # Trailing Stops pruefen
    for symbol in list(bot["positionen"].keys()):
        pos = bot["positionen"][symbol]
        kurs = kurse.get(symbol, 0)
        if not kurs or np.isnan(kurs) or kurs <= 0:
            continue

        atr = ind["atr"][symbol].iloc[-1] if symbol in ind["atr"].columns else 0
        if np.isnan(atr) or atr <= 0:
            continue

        new_high = max(pos.get("high", pos["kauf_kurs"]), kurs)
        pos["high"] = new_high
        effective_sl = new_high - 3 * atr

        if kurs <= effective_sl:
            erloes = pos["stueck"] * kurs * (1 - SPREAD_COST)
            bot["kapital"] += erloes
            bot["trades"] += 1
            logger.info(f"Athena: {symbol} TRAILING-STOP bei {kurs:.2f} (SL={effective_sl:.2f}, High={new_high:.2f})")
            del bot["positionen"][symbol]

    # Kaufsignale pruefen
    for symbol in ASSETS:
        if symbol in bot["positionen"]:
            continue

        kurs = kurse.get(symbol, 0)
        if not kurs or np.isnan(kurs) or kurs <= 0:
            continue

        atr = ind["atr"][symbol].iloc[-1] if symbol in ind["atr"].columns else 0
        if np.isnan(atr) or atr <= 0:
            continue

        score = berechne_score_athena(symbol, kurs, ind, close)

        if score >= kauf_schwelle:
            invest = bot["kapital"] * 0.05
            if invest < kurs:
                continue
            stueck = int(invest / kurs)
            if stueck == 0:
                continue
            kosten = stueck * kurs * (1 + SPREAD_COST)
            if kosten > bot["kapital"]:
                continue

            bot["kapital"] -= kosten
            sl = kurs - 3 * atr
            bot["positionen"][symbol] = {
                "kauf_kurs": round(kurs, 2),
                "stueck": stueck,
                "sl": round(sl, 2),
                "high": round(kurs, 2),
                "datum": heute,
                "score": score,
            }
            bot["trades"] += 1
            if "meta" not in bot:
                bot["meta"] = {}
            bot["meta"][symbol] = {"score": score, "datum": heute}
            logger.info(f"Athena: KAUF {symbol} Score={score} SL={sl:.2f} ATR={atr:.2f}")

def bot_buy_hold(state: dict, close: pd.DataFrame, ind: dict, heute: str):
    """
    Gleichgewichtet alle 66 Assets, monatliches Rebalancing.
    Kein aktives Trading \u2013 reine Benchmark.
    """
    bot = state["bots"]["Buy_Hold"]
    kurse = ind["aktuell"]

    # Erster Kauf oder monatliches Rebalancing (1. des Monats)
    ist_erster_kauf = len(bot["positionen"]) == 0

    try:
        tag = pd.Timestamp(heute)
        ist_monatsanfang = tag.day <= 3 and tag.dayofweek < 5  # Erste 3 Tage des Monats
    except Exception:
        ist_monatsanfang = False

    if not ist_erster_kauf and not ist_monatsanfang:
        return

    # Verkaufe alles fuer Rebalancing
    if not ist_erster_kauf:
        verkaufe_alles(bot, kurse)

    # Gleichgewichtet auf alle verfuegbaren Assets verteilen
    verfuegbare = [s for s in ASSETS if s in kurse and kurse[s] and not np.isnan(kurse.get(s, 0)) and kurse[s] > 0]
    if not verfuegbare:
        return

    gesamt = bot["kapital"]
    anteil = gesamt / len(verfuegbare)

    for symbol in verfuegbare:
        kaufe(bot, symbol, anteil, kurse[symbol])

    logger.info(f"Buy & Hold: Investiert in {len(verfuegbare)} Assets (je {anteil:.0f}$)")


# ---------------------------------------------------------------------------
# Bot 5: Adaptiv
# ---------------------------------------------------------------------------
def bot_adaptiv(state: dict, close: pd.DataFrame, ind: dict, heute: str):
    """
    Adaptiv: Wechselt zwischen Momentum, Crash Guard und Cash je nach VIX.
    - VIX < 20 (ruhig): Momentum-Strategie (Top 10 nach 63-Tage-Rendite)
    - VIX 20-30 (unruhig): Crash Guard (100% SPY, SMA200-Schutz)
    - VIX > 30 (Krise): Komplett Cash
    - Hysterese: Wechsel von unruhig zurueck zu ruhig erst bei VIX < 18
    """
    bot = state["bots"]["Adaptiv"]
    kurse = ind["aktuell"]

    # VIX aus Indikatoren (falls verfuegbar, sonst Fallback 20)
    vix = ind.get("vix", 20)
    if isinstance(vix, pd.Series):
        vix = vix.iloc[-1] if len(vix) > 0 else 20
    if np.isnan(vix):
        vix = 20

    modus_alt = bot.get("modus", "momentum")

    # Modus bestimmen mit Hysterese
    if vix > 30:
        modus = "cash"
    elif vix > 20:
        modus = "crash_guard"
    elif vix < 18 or modus_alt == "momentum":
        modus = "momentum"
    else:
        modus = modus_alt  # Hysterese: bleibe im aktuellen Modus

    bot["modus"] = modus

    if modus == "cash":
        # Alles verkaufen
        if bot["positionen"]:
            logger.info("Adaptiv: KRISE (VIX > 30) - Verkaufe alles, gehe in Cash")
            verkaufe_alles(bot, kurse)

    elif modus == "crash_guard":
        # Nur SPY halten, Rest verkaufen
        for symbol in list(bot["positionen"].keys()):
            if symbol != "SPY":
                verkaufe(bot, symbol, kurse.get(symbol, 0))

        hat_spy = "SPY" in bot["positionen"] and bot["positionen"].get("SPY", 0) > 0
        spy_ueber_sma200 = (spy_kurs and spy_sma200 and not np.isnan(spy_sma200)
                            and spy_kurs >= spy_sma200)

        if hat_spy and not spy_ueber_sma200:
            # SPY unter SMA200 -> verkaufen
            verkaufe(bot, "SPY", spy_kurs)
            logger.info("Adaptiv: Crash Guard - SPY VERKAUFT (unter SMA200)")
        elif not hat_spy and spy_ueber_sma200:
            # SPY kaufen mit gesamtem Kapital
            kaufe(bot, "SPY", bot["kapital"], spy_kurs)
            logger.info("Adaptiv: Crash Guard - SPY GEKAUFT (ueber SMA200)")
        else:
            logger.info(f"Adaptiv: Crash Guard Modus (VIX={vix:.1f})")

    elif modus == "momentum":
        # Top-10 Momentum, gleichgewichtet - analog zu bot_momentum
        # Rebalancing nur Montags
        try:
            tag = pd.Timestamp(heute)
            if tag.dayofweek != 0:  # 0 = Montag
                return
        except Exception:
            pass

        mom = ind["momentum_63"].iloc[-1].dropna().sort_values(ascending=False)
        top10 = mom.head(10).index.tolist()

        if not top10:
            return

        # Verkaufe alles was nicht mehr in Top-10 ist
        for symbol in list(bot["positionen"].keys()):
            if symbol not in top10:
                verkaufe(bot, symbol, kurse.get(symbol, 0))

        # Berechne Gesamtwert und Zielallokation
        gesamt = portfolio_wert(bot, kurse)
        ziel_pro_asset = gesamt / len(top10)

        for symbol in top10:
            kurs = kurse.get(symbol, 0)
            if not kurs or np.isnan(kurs) or kurs <= 0:
                continue

            aktueller_wert = bot["positionen"].get(symbol, 0) * kurs
            diff = ziel_pro_asset - aktueller_wert
            if diff > 100:
                kaufe(bot, symbol, diff, kurs)
            elif diff < -100:
                ueberschuss_menge = abs(diff) / kurs
                aktuelle_menge = bot["positionen"].get(symbol, 0)
                verkauf_menge = min(ueberschuss_menge, aktuelle_menge)
                if verkauf_menge > 0:
                    erloes = verkauf_menge * kurs
                    bot["kapital"] += erloes
                    bot["positionen"][symbol] = aktuelle_menge - verkauf_menge
                    if bot["positionen"][symbol] < 0.0001:
                        del bot["positionen"][symbol]
                    bot["trades"] += 1

        logger.info(f"Adaptiv: Momentum Modus (VIX={vix:.1f}) - {len(bot['positionen'])} Positionen")

    if modus != modus_alt:
        logger.info(f"Adaptiv: Moduswechsel {modus_alt} -> {modus} (VIX={vix:.1f})")

# ---------------------------------------------------------------------------
# Bot 6: Ensemble
# ---------------------------------------------------------------------------
def bot_ensemble(state: dict, close: pd.DataFrame, ind: dict, heute: str):
    """
    Ensemble: Handelt nur wenn ALLE 4 Signale uebereinstimmen.
    Woechentliches Rebalancing (nur Montags), max 5 Positionen,
    4x ATR Stop-Loss, 10x ATR Take-Profit, 10-Tage Cooldown.
    """
    import datetime as dt
    bot = state["bots"]["Ensemble"]
    kurse = ind["aktuell"]
    MAX_POSITIONS = 5
    if "meta" not in bot:
        bot["meta"] = {}
    if "cooldown" not in bot:
        bot["cooldown"] = {}

    # Pruefe bestehende Positionen auf SL/TP TAEGLICH
    for symbol in list(bot["positionen"].keys()):
        kurs = kurse.get(symbol, 0)
        if not kurs or np.isnan(kurs) or kurs <= 0:
            continue
        meta = bot["meta"].get(symbol, {})
        sl = meta.get("sl", 0)
        tp = meta.get("tp", 999999)

        if kurs <= sl or kurs >= tp:
            verkaufe(bot, symbol, kurs)
            if symbol in bot["meta"]:
                del bot["meta"][symbol]
            bot["cooldown"][symbol] = heute
            logger.info(f"Ensemble: {symbol} VERKAUFT (SL/TP) Kurs={kurs:.2f}")

    # Nur Montags neue Kaeufe pruefen
    try:
        heute_date = dt.datetime.strptime(heute, "%Y-%m-%d").date()
        is_monday = heute_date.weekday() == 0
    except:
        is_monday = False

    if not is_monday:
        return

    # Cooldown pruefen (14 Kalendertage ~ 10 Handelstage)
    def is_cooled_down(symbol):
        if symbol not in bot["cooldown"]:
            return True
        try:
            last_sell = dt.datetime.strptime(bot["cooldown"][symbol], "%Y-%m-%d").date()
            return (heute_date - last_sell).days >= 14
        except:
            return True

    if len(bot["positionen"]) >= MAX_POSITIONS:
        return

    # Suche neue Kaufgelegenheiten
    for symbol in ASSETS:
        if symbol in bot["positionen"]:
            continue
        if not is_cooled_down(symbol):
            continue
        if len(bot["positionen"]) >= MAX_POSITIONS:
            break
        kurs = kurse.get(symbol, 0)
        if not kurs or np.isnan(kurs) or kurs <= 0:
            continue

        signals = 0
        total_checks = 0
        # Signal 1: Score-based
        score = berechne_score(symbol, kurs, ind)
        if score >= 6:
            signals += 1
        total_checks += 1
        # Signal 2: Momentum (>5% in 63 days)
        mom = ind["momentum_63"][symbol].iloc[-1] if symbol in ind["momentum_63"].columns else None
        if mom is not None and not np.isnan(mom):
            if mom > 0.05:
                signals += 1
            total_checks += 1
        # Signal 3: SMA200 trend
        sma200_val = ind["sma200"][symbol].iloc[-1] if symbol in ind["sma200"].columns else None
        if sma200_val and not np.isnan(sma200_val):
            if kurs > sma200_val:
                signals += 1
            total_checks += 1
        # Signal 4: RSI sweet spot (30-65)
        rsi = ind["rsi"][symbol].iloc[-1] if symbol in ind["rsi"].columns else None
        if rsi and not np.isnan(rsi):
            if 30 < rsi < 65:
                signals += 1
            total_checks += 1

        # BUY only if ALL 4 signals agree
        if signals >= 4 and total_checks >= 4:
            atr = ind["atr"][symbol].iloc[-1] if symbol in ind["atr"].columns else np.nan
            if np.isnan(atr) or atr <= 0:
                atr = kurs * 0.02
            sl = kurs - 4 * atr
            tp = kurs + 10 * atr
            gesamt = portfolio_wert(bot, kurse)
            betrag = min(gesamt * 0.20, bot["kapital"])  # max 20% per position (5 slots)
            if betrag > 50:
                if kaufe(bot, symbol, betrag, kurs):
                    bot["meta"][symbol] = {"sl": round(sl, 2), "tp": round(tp, 2), "signals": signals}
                    logger.info(f"Ensemble: KAUF {symbol} Signals={signals}/{total_checks} SL={sl:.2f} TP={tp:.2f}")

# Arena State Management
# ---------------------------------------------------------------------------

def lade_arena_state() -> dict:
    """Laedt den aktuellen Arena-Stand oder initialisiert neu."""
    if os.path.exists(ARENA_FILE):
        with open(ARENA_FILE, "r") as f:
            data = json.load(f)
        # Sicherstellen dass meta-Feld existiert
        if "meta" not in data["bots"].get("Kronos", {}):
            data["bots"]["Kronos"]["meta"] = {}
        return data

    logger.info("Kein bestehender State gefunden \u2013 initialisiere neue Arena")
    return {
        "start_datum": datetime.now().strftime("%Y-%m-%d"),
        "letztes_update": "",
        "bots": {
            "Momentum": {"kapital": STARTKAPITAL, "positionen": {}, "trades": 0, "history": []},
            "Crash_Guard": {"kapital": STARTKAPITAL, "positionen": {}, "trades": 0, "history": []},
            "Kronos": {"kapital": STARTKAPITAL, "positionen": {}, "trades": 0, "history": [], "meta": {}},
            "Athena": {"kapital": STARTKAPITAL, "positionen": {}, "trades": 0, "history": [], "meta": {}},
            "Buy_Hold": {"kapital": STARTKAPITAL, "positionen": {}, "trades": 0, "history": []},
            "Adaptiv": {"kapital": STARTKAPITAL, "positionen": {}, "trades": 0, "history": [], "modus": "momentum"},
            "Ensemble": {"kapital": STARTKAPITAL, "positionen": {}, "trades": 0, "history": [], "meta": {}},
        },
    }


def speichere_arena_state(state: dict):
    """Speichert den Arena-Stand als JSON."""
    with open(ARENA_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)
    logger.info(f"Arena State gespeichert in {ARENA_FILE}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    logger.info("=" * 60)
    logger.info("  BOT ARENA \u2013 Tagesupdate")
    logger.info("=" * 60)

    # 1. Lade State
    state = lade_arena_state()

    # 2. Lade Kurse
    close = lade_kurse(tage=252)
    if close.empty:
        logger.error("Keine Kursdaten verfuegbar \u2013 Abbruch")
        return

    # 3. Berechne Indikatoren
    ind = berechne_indikatoren(close)
    kurse = ind["aktuell"]
    heute = close.index[-1].strftime("%Y-%m-%d")

    logger.info(f"Handelstag: {heute}")
    logger.info(f"SPY: {kurse.get('SPY', 'N/A')}")
    logger.info(f"VIX: {ind.get('vix', 'N/A')}")

    # 4. Lasse jeden Bot agieren
    logger.info("-" * 40)
    logger.info("Bot-Entscheidungen:")
    logger.info("-" * 40)

    bot_funktionen = [
        ("Momentum", bot_momentum),
        ("Crash_Guard", bot_crash_guard),
        ("Kronos", bot_kronos),
        ("Athena", bot_athena),
        ("Buy_Hold", bot_buy_hold),
        ("Adaptiv", bot_adaptiv),
        ("Ensemble", bot_ensemble),
    ]

    for name, funk in bot_funktionen:
        try:
            funk(state, close, ind, heute)
        except Exception as e:
            logger.error(f"Fehler bei {name}: {e}")

    # 5. Berechne Portfolio-Werte und History
    logger.info("-" * 40)
    logger.info("Portfolio-Werte:")
    logger.info("-" * 40)

    rangliste = []
    for name in state["bots"]:
        bot = state["bots"][name]
        wert = portfolio_wert(bot, kurse)
        pnl = wert - STARTKAPITAL
        pnl_pct = (pnl / STARTKAPITAL) * 100

        # History-Eintrag
        bot["history"].append({
            "datum": heute,
            "wert": round(wert, 2),
            "cash": round(bot["kapital"], 2),
            "positionen_anzahl": len(bot["positionen"]),
            "trades_gesamt": bot["trades"],
        })

        rangliste.append((name, wert, pnl, pnl_pct, bot["trades"], len(bot["positionen"])))
        logger.info(f"  {name:15s}: {wert:>12,.2f}$ ({pnl:>+10,.2f}$ / {pnl_pct:>+6.2f}%) | Trades: {bot['trades']:3d} | Pos: {len(bot['positionen'])}")

    # Sortiere nach Wert
    rangliste.sort(key=lambda x: x[1], reverse=True)

    # 6. Speichere State
    state["letztes_update"] = heute
    speichere_arena_state(state)

    # 7. Telegram-Nachricht
    msg_lines = [
        f"<b>\ud83c\udfdf\ufe0f Bot Arena \u2013 {heute}</b>",
        f"SPY: ${kurse.get('SPY', 0):,.2f} | VIX: {ind.get('vix', 0):.1f}",
        "",
        "<b>Rangliste:</b>",
    ]
    medaillen = ["\ud83e\udd47", "\ud83e\udd48", "\ud83e\udd49", "4\ufe0f\u20e3", "5\ufe0f\u20e3", "6\ufe0f\u20e3"]
    for i, (name, wert, pnl, pnl_pct, trades, pos) in enumerate(rangliste):
        emoji = medaillen[i] if i < len(medaillen) else "  "
        pfeil = "\ud83d\udcc8" if pnl >= 0 else "\ud83d\udcc9"
        msg_lines.append(
            f"{emoji} <b>{name}</b>: ${wert:,.0f} ({pnl_pct:+.2f}%) {pfeil}"
        )
        msg_lines.append(f"    Trades: {trades} | Positionen: {pos}")

    # Top-Positionen des fuehrenden Bots
    leader_name = rangliste[0][0]
    leader = state["bots"][leader_name]
    if leader["positionen"]:
        top_pos = sorted(leader["positionen"].items(), key=lambda x: x[1] * kurse.get(x[0], 0), reverse=True)[:5]
        msg_lines.append(f"\n<b>Top-Positionen ({leader_name}):</b>")
        for sym, menge in top_pos:
            wert_pos = menge * kurse.get(sym, 0)
            msg_lines.append(f"  {sym}: ${wert_pos:,.0f}")

    msg = "\n".join(msg_lines)
    sende_telegram(msg)

    logger.info("=" * 60)
    logger.info("  Arena Update abgeschlossen!")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
