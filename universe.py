"""
universe.py - Erweitertes Underlying-Universum (v2.0)

Stand: 2026-04-14
Anzahl: ~70 Underlyings
Auswahl-Kriterien: hohe Liquiditaet, OS-Verfuegbarkeit, geringer Spread.
"""

# (id, name, typ, sektor)
ASSETS = [
    # ── US Tech (12) ─────────────────────────────────────────
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

    # ── US Other (4) ────────────────────────────────────────
    ("NFLX",   "Netflix",        "aktie", "Media"),
    ("ORCL",   "Oracle",         "aktie", "Tech"),
    ("JPM",    "JPMorgan",       "aktie", "Finance"),
    ("BRK-B",  "Berkshire B",    "aktie", "Finance"),

    # ── US Indizes (3) ───────────────────────────────────────
    ("SPY",    "S&P 500",        "etf", "US-Index"),
    ("QQQ",    "Nasdaq 100",     "etf", "US-Index"),
    ("IWM",    "Russell 2000",   "etf", "US-Index"),

    # ── DAX/MDAX (12) ────────────────────────────────────────
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

    # ── EU Other (4) ─────────────────────────────────────────
    ("ASML.AS","ASML",           "aktie", "EU-Tech"),
    ("MC.PA",  "LVMH",           "aktie", "Luxury"),
    ("NOVO-B.CO","Novo Nordisk", "aktie", "Pharma"),
    ("BNP.PA", "BNP Paribas",    "aktie", "EU-Finance"),

    # ── EU Indizes (3) ───────────────────────────────────────
    ("EXS1.DE","DAX 40",         "etf", "EU-Index"),
    ("^STOXX50E","EuroStoxx 50", "etf", "EU-Index"),
    ("EXS3.DE","MDAX",           "etf", "EU-Index"),

    # ── Asia (5) ─────────────────────────────────────────────
    ("7203.T", "Toyota",         "aktie", "Asia"),
    ("6758.T", "Sony",           "aktie", "Asia"),
    ("0700.HK","Tencent",        "aktie", "Asia"),
    ("9988.HK","Alibaba",        "aktie", "Asia"),
    ("TSM",    "TSMC",           "aktie", "Asia"),

    # ── Asia/EM ETF (4) ──────────────────────────────────────
    ("EWJ",    "Nikkei ETF",     "etf", "Asia"),
    ("FXI",    "China ETF",      "etf", "Asia"),
    ("INDA",   "Indien ETF",     "etf", "EM"),
    ("EWZ",    "Brasilien ETF",  "etf", "EM"),

    # ── FX (4) ───────────────────────────────────────────────
    ("EURUSD=X","EUR/USD",       "fx", "FX"),
    ("GBPUSD=X","GBP/USD",       "fx", "FX"),
    ("USDJPY=X","USD/JPY",       "fx", "FX"),
    ("EURCHF=X","EUR/CHF",       "fx", "FX"),

    # ── Commodities (7) ──────────────────────────────────────
    ("GC=F",   "Gold",           "commodity", "Metal"),
    ("SI=F",   "Silber",         "commodity", "Metal"),
    ("PL=F",   "Platin",         "commodity", "Metal"),
    ("PA=F",   "Palladium",      "commodity", "Metal"),
    ("BZ=F",   "Brent Oil",      "commodity", "Energy"),
    ("NG=F",   "Erdgas",         "commodity", "Energy"),
    ("HG=F",   "Kupfer",         "commodity", "Metal"),

    # ── Crypto (4) ───────────────────────────────────────────
    ("BTC-USD","Bitcoin",        "crypto", "Crypto"),
    ("ETH-USD","Ethereum",       "crypto", "Crypto"),
    ("SOL-USD","Solana",         "crypto", "Crypto"),
    ("XRP-USD","XRP",            "crypto", "Crypto"),
]


def build_lookup():
    return {a[0]: {"id": a[0], "name": a[1], "typ": a[2], "sektor": a[3]}
            for a in ASSETS}


def all_assets():
    return [{"id": a[0], "name": a[1], "typ": a[2], "sektor": a[3]} for a in ASSETS]


if __name__ == "__main__":
    from collections import Counter
    print(f"Total: {len(ASSETS)} Underlyings")
    print(f"By Typ: {dict(Counter(a[2] for a in ASSETS))}")
    print(f"By Sektor: {dict(Counter(a[3] for a in ASSETS))}")
