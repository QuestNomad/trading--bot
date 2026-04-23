"""
universe.py - Erweitertes Underlying-Universum (v2.1)

Stand: 2026-04-24
Anzahl: ~88 Underlyings
Auswahl-Kriterien: hohe Liquiditaet, OS-Verfuegbarkeit, geringer Spread.

Aenderungen v2.1 (2026-04-24):
- Union mit bot.py SECTORS (SMCI, COIN, MARA, SOFI, LLY, NVO, MRNA, COST,
  XOM, MELI, ASML, SHOP, SE, NU, FSLR, UBSG.SW, DHER.DE, AAXJ, EWT, VWO,
  URA, ZW=F, XSPS.L, DXSN.DE, QQQS.L, BITI) hinzugefuegt
- SECTORS-Dict als Single Source of Truth (fuer bot.py import)
- COINGECKO_IDS-Map fuer Crypto Cross-Reference (bot.py nutzt coingecko)
- Helper: get_sector(), symbols_in_sector(), build_sectors_from_assets()
"""

from collections import defaultdict

# (id, name, typ, sektor)
ASSETS = [
    # US Tech (14)
    ("AAPL",   "Apple",          "aktie", "Tech"),
    ("MSFT",   "Microsoft",      "aktie", "Tech"),
    ("NVDA",   "Nvidia",         "aktie", "Tech"),
    ("META",   "Meta",           "aktie", "Tech"),
    ("AMZN",   "Amazon",         "aktie", "Tech"),
    ("GOOGL",  "Google",         "aktie", "Tech"),
    ("TSLA",   "Tesla",          "aktie", "Tech"),
    ("AMD",    "AMD",            "aktie", "Tech"),
    ("AVGO",   "Broadcom",       "aktie", "Tech"),
    ("PLTR",   "Palantir",       "aktie", "Tech"),
    ("ARM",    "ARM",            "aktie", "Tech"),
    ("MSTR",   "MicroStrategy",  "aktie", "Tech"),
    ("SMCI",   "Super Micro",    "aktie", "Tech"),
    ("SHOP",   "Shopify",        "aktie", "Tech"),

    # US Consumer / Services (3)
    ("COST",   "Costco",         "aktie", "Consumer"),
    ("MELI",   "MercadoLibre",   "aktie", "Consumer"),
    ("SE",     "Sea Ltd",        "aktie", "Internet"),

    # US Finance (5)
    ("JPM",    "JPMorgan",       "aktie", "Finance"),
    ("BRK-B",  "Berkshire B",    "aktie", "Finance"),
    ("COIN",   "Coinbase",       "aktie", "Finance"),
    ("SOFI",   "SoFi",           "aktie", "Finance"),
    ("NU",     "Nu Holdings",    "aktie", "Finance"),

    # US Health / Pharma (3)
    ("LLY",    "Eli Lilly",      "aktie", "Health"),
    ("NVO",    "Novo Nordisk",   "aktie", "Health"),
    ("MRNA",   "Moderna",        "aktie", "Health"),

    # US Energy / Misc (3)
    ("XOM",    "ExxonMobil",     "aktie", "Energy"),
    ("FSLR",   "First Solar",    "aktie", "Energy"),
    ("MARA",   "Marathon Digi",  "aktie", "Tech"),

    # US Other (2)
    ("NFLX",   "Netflix",        "aktie", "Media"),
    ("ORCL",   "Oracle",         "aktie", "Tech"),

    # US Indizes (3)
    ("SPY",    "S&P 500",        "etf", "US-Index"),
    ("QQQ",    "Nasdaq 100",     "etf", "US-Index"),
    ("IWM",    "Russell 2000",   "etf", "US-Index"),

    # DAX/MDAX (13)
    ("SAP.DE", "SAP",            "aktie", "EU-Tech"),
    ("SIE.DE", "Siemens",        "aktie", "EU-Indust"),
    ("ALV.DE", "Allianz",        "aktie", "EU-Finance"),
    ("MBG.DE", "Mercedes",       "aktie", "EU-Auto"),
    ("BMW.DE", "BMW",            "aktie", "EU-Auto"),
    ("P911.DE","Porsche AG",     "aktie", "EU-Auto"),
    ("VOW3.DE","Volkswagen",     "aktie", "EU-Auto"),
    ("IFX.DE", "Infineon",       "aktie", "EU-Tech"),
    ("RHM.DE", "Rheinmetall",    "aktie", "Defense"),
    ("AIR.DE", "Airbus",         "aktie", "Aerospace"),
    ("DBK.DE", "Deutsche Bank",  "aktie", "EU-Finance"),
    ("ZAL.DE", "Zalando",        "aktie", "Ecommerce"),
    ("DHER.DE","Delivery Hero",  "aktie", "Delivery"),

    # EU Other (6)
    ("ASML.AS","ASML (NL)",      "aktie", "EU-Tech"),
    ("ASML",   "ASML (ADR)",     "aktie", "Semiconductor"),
    ("MC.PA",  "LVMH",           "aktie", "Luxury"),
    ("NOVO-B.CO","Novo Nordisk (DK)","aktie","Pharma"),
    ("BNP.PA", "BNP Paribas",    "aktie", "EU-Finance"),
    ("UBSG.SW","UBS",            "aktie", "Finance"),

    # EU Indizes (3)
    ("EXS1.DE","DAX 40",         "etf", "EU-Index"),
    ("^STOXX50E","EuroStoxx 50", "etf", "EU-Index"),
    ("EXS3.DE","MDAX",           "etf", "EU-Index"),

    # Asia (5)
    ("7203.T", "Toyota",         "aktie", "Asia"),
    ("6758.T", "Sony",           "aktie", "Asia"),
    ("0700.HK","Tencent",        "aktie", "Asia"),
    ("9988.HK","Alibaba",        "aktie", "Asia"),
    ("TSM",    "TSMC",           "aktie", "Semiconductor"),

    # Asia/EM ETF (7)
    ("EWJ",    "Nikkei ETF",     "etf", "Asia"),
    ("FXI",    "China ETF",      "etf", "Asia"),
    ("EWT",    "Taiwan ETF",     "etf", "Asia"),
    ("AAXJ",   "Asia ex-Japan",  "etf", "Asia"),
    ("INDA",   "Indien ETF",     "etf", "EM"),
    ("EWZ",    "Brasilien ETF",  "etf", "EM"),
    ("VWO",    "EM ETF",         "etf", "EM"),

    # FX (4)
    ("EURUSD=X","EUR/USD",       "fx", "FX"),
    ("GBPUSD=X","GBP/USD",       "fx", "FX"),
    ("USDJPY=X","USD/JPY",       "fx", "FX"),
    ("EURCHF=X","EUR/CHF",       "fx", "FX"),

    # Commodities (9)
    ("GC=F",   "Gold",           "commodity", "Metal"),
    ("SI=F",   "Silber",         "commodity", "Metal"),
    ("PL=F",   "Platin",         "commodity", "Metal"),
    ("PA=F",   "Palladium",      "commodity", "Metal"),
    ("HG=F",   "Kupfer",         "commodity", "Metal"),
    ("BZ=F",   "Brent Oil",      "commodity", "Energy"),
    ("NG=F",   "Erdgas",         "commodity", "Energy"),
    ("ZW=F",   "Weizen",         "commodity", "Agri"),
    ("URA",    "Uran ETF",       "etf", "Commodity"),

    # Crypto (4, yfinance-Format)
    ("BTC-USD","Bitcoin",        "crypto", "Crypto"),
    ("ETH-USD","Ethereum",       "crypto", "Crypto"),
    ("SOL-USD","Solana",         "crypto", "Crypto"),
    ("XRP-USD","XRP",            "crypto", "Crypto"),

    # Short / Inverse ETFs (4)
    ("XSPS.L", "Short S&P 500",  "etf", "Short"),
    ("DXSN.DE","Short DAX",      "etf", "Short"),
    ("QQQS.L", "Short Nasdaq",   "etf", "Short"),
    ("BITI",   "Short Krypto",   "etf", "Short"),
]


# Cross-Reference: yfinance-Symbol -> coingecko-ID
# bot.py nutzt coingecko API fuer Crypto; diese Map erlaubt
# Lookup vom kanonischen yfinance-Symbol (in ASSETS) zur coingecko-ID.
COINGECKO_IDS = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "SOL-USD": "solana",
    "XRP-USD": "ripple",
}


# SECTORS als Single Source of Truth (fuer bot.py + arena*.py)
# Manuell gepflegt, damit Arena-Strategien reproduzierbar bleiben.
SECTORS = {
    "Tech":          ["AAPL", "MSFT", "GOOGL", "NVDA", "META", "AMD", "AVGO",
                      "SHOP", "PLTR", "SMCI", "MARA", "ARM", "MSTR", "ORCL"],
    "Consumer":      ["AMZN", "TSLA", "COST", "MELI"],
    "Finance":       ["DBK.DE", "BNP.PA", "UBSG.SW", "COIN", "SOFI", "NU",
                      "JPM", "BRK-B", "ALV.DE"],
    "Health":        ["LLY", "NVO", "MRNA", "NOVO-B.CO"],
    "Auto":          ["7203.T", "MBG.DE", "BMW.DE", "P911.DE", "VOW3.DE"],
    "Entertainment": ["6758.T", "NFLX"],
    "Defense":       ["RHM.DE"],
    "Aerospace":     ["AIR.DE"],
    "Ecommerce":     ["ZAL.DE", "9988.HK"],
    "Delivery":      ["DHER.DE"],
    "Internet":      ["0700.HK", "SE"],
    "Index_EU":      ["EXS1.DE", "EXS3.DE", "^STOXX50E",
                      "SAP.DE", "SIE.DE", "IFX.DE"],
    "Index_US":      ["SPY", "IWM", "QQQ"],
    "Index_Asia":    ["EWJ", "FXI", "EWT"],
    "EM":            ["INDA", "EWZ", "VWO", "AAXJ"],
    "Commodities":   ["GC=F", "SI=F", "HG=F", "BZ=F", "ZW=F", "URA",
                      "NG=F", "PL=F", "PA=F"],
    "Crypto":        ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD"],
    "Short":         ["XSPS.L", "DXSN.DE", "QQQS.L", "BITI"],
    "Energy":        ["XOM", "FSLR"],
    "Semiconductor": ["TSM", "ASML", "ASML.AS"],
    "FX":            ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "EURCHF=X"],
    "Luxury":        ["MC.PA"],
}


# Abgeleitet: Asset-ID -> Sektor-Name (flacher Lookup)
ASSET_TO_SECTOR = {}
for _sec, _syms in SECTORS.items():
    for _sym in _syms:
        ASSET_TO_SECTOR[_sym] = _sec


# Helper
def build_lookup():
    """Id -> Asset-dict (backward-compat mit v2.0)."""
    return {a[0]: {"id": a[0], "name": a[1], "typ": a[2], "sektor": a[3]}
            for a in ASSETS}


def all_assets():
    """Liste aller Assets als Dicts (backward-compat mit v2.0)."""
    return [{"id": a[0], "name": a[1], "typ": a[2], "sektor": a[3]} for a in ASSETS]


def get_sector(asset_id):
    """Sektor eines Assets; None wenn nicht in SECTORS."""
    return ASSET_TO_SECTOR.get(asset_id)


def symbols_in_sector(sector):
    """Liste aller Symbole eines Sektors (leer wenn unbekannt)."""
    return list(SECTORS.get(sector, []))


def build_sectors_from_assets():
    """Generiert SECTORS dynamisch aus ASSETS (Sanity-Check)."""
    out = defaultdict(list)
    for asset_id, _name, _typ, sektor in ASSETS:
        out[sektor].append(asset_id)
    return dict(out)


def coingecko_id(asset_id):
    """yfinance-Symbol -> coingecko-ID (nur fuer Crypto)."""
    return COINGECKO_IDS.get(asset_id)


if __name__ == "__main__":
    from collections import Counter
    print(f"Total: {len(ASSETS)} Underlyings")
    print(f"By Typ: {dict(Counter(a[2] for a in ASSETS))}")
    print(f"By Sektor (aus ASSETS): {dict(Counter(a[3] for a in ASSETS))}")
    print(f"\nSECTORS dict: {len(SECTORS)} Sektoren, "
          f"{sum(len(v) for v in SECTORS.values())} Zuordnungen")
    asset_ids = {a[0] for a in ASSETS}
    missing = [s for syms in SECTORS.values() for s in syms if s not in asset_ids]
    if missing:
        print(f"WARN: SECTORS enthaelt Symbole ohne ASSETS-Eintrag: {missing}")
    else:
        print("OK: alle SECTORS-Symbole in ASSETS definiert.")
