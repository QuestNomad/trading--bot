#!/usr/bin/env python3
"""
journal_cleanup.py — Bereinigt journal.csv
Nutzung: python journal_cleanup.py [--dry-run]

Aktionen:
  1. Exakte Duplikate entfernen
  2. Bei offenen Positionen mit identischem (Asset, Signal, Kurs): nur ersten behalten
  3. Alte offene Positionen (> N Tage) als "archiviert" markieren
  4. Header normalisieren (SMA200->SMA20, Take Profit->Trailing_Stop)
"""

import csv
import sys
import shutil
from datetime import datetime, timedelta
from pathlib import Path

JOURNAL = Path("journal.csv")
ARCHIVE_DAYS = 14  # Positionen aelter als N Tage archivieren

HEADER_FIXES = {
    "SMA200": "SMA20",
    "Take Profit": "Trailing_Stop",
    "Take_Profit": "Trailing_Stop",
}

EXPECTED_HEADER = [
    "Datum", "Asset", "Signal", "Kurs", "SMA20", "RSI", "Score",
    "Stop Loss", "Trailing_Stop", "Sentiment Welt", "Sentiment EU",
    "Status", "Ergebnis", "Geschlossen_am", "Kommentar"
]


def main():
    dry_run = "--dry-run" in sys.argv

    if not JOURNAL.exists():
        print("journal.csv nicht gefunden.")
        sys.exit(1)

    with open(JOURNAL, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    original_count = len(rows)
    print(f"Geladen: {original_count} Zeilen")

    # --- 1. Header normalisieren ---
    fixed_header = []
    for col in header:
        col_stripped = col.strip()
        fixed_header.append(HEADER_FIXES.get(col_stripped, col_stripped))
    if fixed_header != header:
        print(f"Header korrigiert: {[h for h, o in zip(fixed_header, header) if h != o]}")
    header = fixed_header

    # --- 2. Exakte Duplikate entfernen ---
    seen = set()
    unique_rows = []
    dupes = 0
    for row in rows:
        key = tuple(row)
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        unique_rows.append(row)
    if dupes:
        print(f"Duplikate entfernt: {dupes}")
    rows = unique_rows

    # --- 3. Offene Doppelte: nur ersten behalten ---
    open_seen = set()
    deduped = []
    open_dupes = 0
    for row in rows:
        status_idx = header.index("Status") if "Status" in header else -1
        if status_idx >= 0 and len(row) > status_idx and row[status_idx].strip().lower() == "offen":
            asset_idx = header.index("Asset") if "Asset" in header else 1
            signal_idx = header.index("Signal") if "Signal" in header else 2
            kurs_idx = header.index("Kurs") if "Kurs" in header else 3
            key = (
                row[asset_idx].strip() if len(row) > asset_idx else "",
                row[signal_idx].strip() if len(row) > signal_idx else "",
                row[kurs_idx].strip() if len(row) > kurs_idx else "",
            )
            if key in open_seen:
                open_dupes += 1
                continue
            open_seen.add(key)
        deduped.append(row)
    if open_dupes:
        print(f"Offene Duplikate entfernt: {open_dupes}")
    rows = deduped

    # --- 4. Alte offene Positionen archivieren ---
    cutoff = (datetime.now() - timedelta(days=ARCHIVE_DAYS)).strftime("%Y-%m-%d")
    archived = 0
    datum_idx = header.index("Datum") if "Datum" in header else 0
    status_idx = header.index("Status") if "Status" in header else -1
    kommentar_idx = header.index("Kommentar") if "Kommentar" in header else -1

    for row in rows:
        if status_idx < 0 or len(row) <= status_idx:
            continue
        if row[status_idx].strip().lower() == "offen":
            datum = row[datum_idx].strip() if len(row) > datum_idx else ""
            if datum and datum < cutoff:
                row[status_idx] = "archiviert"
                if kommentar_idx >= 0 and len(row) > kommentar_idx:
                    row[kommentar_idx] = f"auto-archiviert (>{ARCHIVE_DAYS}d)"
                archived += 1
    if archived:
        print(f"Archiviert (>{ARCHIVE_DAYS} Tage alt): {archived}")

    final_count = len(rows)
    print(f"Ergebnis: {original_count} -> {final_count} Zeilen")

    if dry_run:
        print("[DRY RUN] Keine Aenderungen geschrieben.")
        return

    # Backup
    backup = JOURNAL.with_name(f"journal_backup_{datetime.now():%Y%m%d_%H%M%S}.csv")
    shutil.copy2(JOURNAL, backup)
    print(f"Backup: {backup.name}")

    with open(JOURNAL, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

    print("journal.csv geschrieben.")


if __name__ == "__main__":
    main()
