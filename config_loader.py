"""
config_loader.py - Liest config/bot.json (vom Dashboard geschrieben)

Verwendung in bot.py (Anfang, NACH den hardcoded Konstanten):

    from config_loader import apply_overrides
    apply_overrides(globals())

Damit werden alle in config/bot.json gesetzten Werte als Modul-Konstanten
ueberschrieben. Falls die Datei fehlt oder Felder fehlen: Defaults bleiben.

Alle Werte sind optional. Schluessel siehe DEFAULTS in scripts/dashboard.py.
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config" / "bot.json"

# Mapping config-key (lowercase) -> Modul-Konstantenname (UPPERCASE)
_MAPPING = {
    "kapital":                 "KAPITAL",
    "max_risiko":              "MAX_RISIKO",
    "kelly_fraction":          "KELLY_FRACTION",
    "max_exposure":            "MAX_EXPOSURE",
    "vix_limit":               "VIX_LIMIT",
    "buy_threshold":           "BUY_THRESHOLD",
    "sell_threshold":          "SELL_THRESHOLD",
    "atr_sl_multiplier":       "ATR_SL_MULTIPLIER",
    "max_positions_per_sector": "MAX_POSITIONS_PER_SECTOR",
    "enable_sma200_filter":    "ENABLE_SMA200_FILTER",
}


def load() -> dict:
    """Liest config/bot.json. Gibt leeres dict zurueck wenn nicht vorhanden."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] config_loader: {CONFIG_FILE.name} unlesbar: {e}")
        return {}


def apply_overrides(target_globals: dict) -> list[str]:
    """Ueberschreibt Modul-Konstanten in target_globals mit Werten aus bot.json.

    Returns: Liste der ueberschriebenen Konstantennamen.
    """
    cfg = load()
    if not cfg:
        return []
    overridden = []
    for key, const_name in _MAPPING.items():
        if key in cfg and const_name in target_globals:
            old = target_globals[const_name]
            new = cfg[key]
            # Typ-Erhaltung: cast new auf Typ von old
            try:
                if isinstance(old, bool):
                    new = bool(new)
                elif isinstance(old, int) and not isinstance(old, bool):
                    new = int(new)
                elif isinstance(old, float):
                    new = float(new)
            except (TypeError, ValueError):
                continue
            if old != new:
                target_globals[const_name] = new
                overridden.append(f"{const_name}: {old} -> {new}")
    if overridden:
        print(f"[config_loader] Overrides aus {CONFIG_FILE.name}:")
        for entry in overridden:
            print(f"  {entry}")
    return overridden


if __name__ == "__main__":
    cfg = load()
    print(f"Config-Datei: {CONFIG_FILE}")
    print(f"Existiert:    {CONFIG_FILE.exists()}")
    print(f"Inhalt:       {cfg}")
