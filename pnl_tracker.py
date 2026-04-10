"""
P&L Tracker für den Trading Bot
Prüft offene Positionen in journal.csv gegen aktuelle Kurse
"""
import pandas as pd
import yfinance as yf
import logging
from datetime import datetime


def lade_journal(pfad="journal.csv"):
    """Lädt die journal.csv und fügt fehlende Spalten hinzu"""
    try:
        df = pd.read_csv(pfad)
    except FileNotFoundError:
        logging.warning(f"Journal {pfad} nicht gefunden")
        return None

    # Neue Spalten hinzufügen falls nicht vorhanden
    if "Status" not in df.columns:
        df["Status"] = "offen"
    if "Ergebnis_Pct" not in df.columns:
        df["Ergebnis_Pct"] = None
    if "Geschlossen_am" not in df.columns:
        df["Geschlossen_am"] = None

    return df


def hole_aktuellen_kurs(symbol):
    """Holt den aktuellen Kurs für ein Symbol"""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d")
        if not hist.empty:
            return hist["Close"].iloc[-1]
    except Exception as e:
        logging.error(f"Kurs für {symbol} nicht abrufbar: {e}")
    return None


def pruefe_offene_positionen(journal_pfad="journal.csv", send_text=None, chat_id=None, bot_token=None):
    """
    Prüft alle offenen Positionen gegen Stop-Loss und Take-Profit.
    Aktualisiert journal.csv und sendet Telegram-Nachricht.
    """
    df = lade_journal(journal_pfad)
    if df is None or df.empty:
        return []

    geschlossene = []

    for idx, row in df.iterrows():
        if row.get("Status", "offen") != "offen":
            continue
        if row.get("Signal") not in ["KAUFEN", "VERKAUFEN"]:
            continue

        symbol = row.get("Symbol", row.get("Asset", ""))
        if not symbol:
            continue

        kurs_aktuell = hole_aktuellen_kurs(symbol)
        if kurs_aktuell is None:
            continue

        einstieg = float(row["Kurs"])
        stop_loss = float(row["Stop_Loss"]) if pd.notna(row.get("Stop_Loss")) else None
        take_profit = float(row["Take_Profit"]) if pd.notna(row.get("Take_Profit")) else None
        signal = row["Signal"]
        ist_short = row.get("Short", False)

        # P&L berechnen
        if signal == "KAUFEN" and not ist_short:
            pnl_pct = ((kurs_aktuell - einstieg) / einstieg) * 100
        elif signal == "VERKAUFEN" or ist_short:
            pnl_pct = ((einstieg - kurs_aktuell) / einstieg) * 100
        else:
            continue

        # Prüfe ob SL oder TP erreicht
        geschlossen = False
        grund = ""

        if stop_loss and kurs_aktuell <= stop_loss and signal == "KAUFEN" and not ist_short:
            geschlossen = True
            grund = "Stop-Loss"
        elif stop_loss and kurs_aktuell >= stop_loss and (signal == "VERKAUFEN" or ist_short):
            geschlossen = True
            grund = "Stop-Loss"
        elif take_profit and kurs_aktuell >= take_profit and signal == "KAUFEN" and not ist_short:
            geschlossen = True
            grund = "Take-Profit"
        elif take_profit and kurs_aktuell <= take_profit and (signal == "VERKAUFEN" or ist_short):
            geschlossen = True
            grund = "Take-Profit"

        if geschlossen:
            df.at[idx, "Status"] = "geschlossen"
            df.at[idx, "Ergebnis_Pct"] = round(pnl_pct, 2)
            df.at[idx, "Geschlossen_am"] = datetime.now().strftime("%Y-%m-%d")
            geschlossene.append({
                "asset": symbol,
                "signal": signal,
                "einstieg": einstieg,
                "aktuell": kurs_aktuell,
                "pnl_pct": round(pnl_pct, 2),
                "grund": grund
            })

    # Journal speichern
    if geschlossene:
        df.to_csv(journal_pfad, index=False)
        logging.info(f"{len(geschlossene)} Position(en) geschlossen")

    # Telegram P&L Zusammenfassung
    if send_text and chat_id and bot_token:
        sende_pnl_zusammenfassung(df, geschlossene, send_text, chat_id, bot_token)

    return geschlossene


def sende_pnl_zusammenfassung(df, geschlossene, send_text, chat_id, bot_token):
    """Sendet P&L-Zusammenfassung per Telegram"""
    offene = df[df["Status"] == "offen"]
    alle_geschlossen = df[df["Status"] == "geschlossen"]

    msg = "📊 *P&L Tracker*\n\n"

    if geschlossene:
        msg += "🔔 *Heute geschlossen:*\n"
        for p in geschlossene:
            emoji = "✅" if p["pnl_pct"] > 0 else "❌"
            msg += f"{emoji} {p['asset']}: {p['pnl_pct']:+.2f}% ({p['grund']})\n"
        msg += "\n"

    if not alle_geschlossen.empty and "Ergebnis_Pct" in alle_geschlossen.columns:
        gesamt_pnl = alle_geschlossen["Ergebnis_Pct"].dropna().sum()
        gewinner = (alle_geschlossen["Ergebnis_Pct"].dropna() > 0).sum()
        gesamt = len(alle_geschlossen["Ergebnis_Pct"].dropna())
        winrate = (gewinner / gesamt * 100) if gesamt > 0 else 0
        msg += f"📈 Gesamt P&L: {gesamt_pnl:+.2f}%\n"
        msg += f"🎯 Win-Rate: {winrate:.0f}% ({gewinner}/{gesamt})\n"

    msg += f"📋 Offene Positionen: {len(offene)}"

    try:
        send_text(msg, chat_id, bot_token)
    except Exception as e:
        logging.error(f"P&L Telegram-Nachricht fehlgeschlagen: {e}")
