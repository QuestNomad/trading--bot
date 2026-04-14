# Trading-Bot v2.0 — Migration auf Open-End Turbos (Mini-Futures)

**Datum:** 2026-04-14
**Uhrzeit:** 2026-04-14 12:16:55 UTC
**Autor:** Doc Klaus / Claude
**Repo:** QuestNomad/trading--bot

---

## Grund der Änderung

Der bestehende `paper_trading.py` (v1) handelt nur Spot-Underlyings (Aktien, ETFs,
Crypto). Die ursprüngliche Intention des **OptiBots** war jedoch **Hebelprodukte**
(Optionsscheine / Mini-Futures) zu handeln, um bei gleichem Kapitaleinsatz eine
höhere Rendite zu erzielen.

v2.0 setzt diesen ursprünglichen Plan um — und zwar mit **Open-End Turbos
(Mini-Futures)** statt klassischer Optionsscheine. Begründung:

| Eigenschaft | Klass. OS (Call/Put) | **Open-End Turbo** |
|---|---|---|
| Theta-Decay | Ja | Nein |
| IV-Risiko | Hoch | Keins |
| Pricing | Black-Scholes | Linear (Spot − Strike) |
| Backtestbar | Schwer | Trivial |
| Hebel | Variabel | Konstant bis Knock-out |

Mini-Futures sind für algorithmischen Handel deutlich besser geeignet — der Bot
muss keine implizite Volatilität tracken, und die Bewertung ist deterministisch.

---

## Was ist neu

### Neue Dateien (commited ins Repo)

| Datei | Zeilen | Zweck |
|---|---|---|
| `universe.py` | 110 | Erweitertes Underlying-Universum (62 Werte statt 38) |
| `os_selector.py` | 218 | Mini-Future-Auswahl via onvista.de (HTML-Parser) |
| `os_quotes.py` | 124 | Live-Quotes via Lang & Schwarz Exchange JSON-API |
| `paper_trading_os.py` | 463 | Hauptlogik: Score-Trader auf Mini-Futures |
| `.github/workflows/paper-trading-os.yml` | 50 | GitHub Actions Workflow (3×/Tag) |

### Erweitertes Universum (62 Underlyings)

| Bereich | Anzahl | Beispiele |
|---|---|---|
| US-Tech | 12 | AAPL, MSFT, NVDA, AMD, AVGO, PLTR, ARM, MSTR |
| US-Other | 4 | NFLX, ORCL, JPM, BRK-B |
| US-Indizes | 3 | SPY, QQQ, IWM |
| DAX/MDAX | 12 | SAP, SIE, ALV, MBG, BMW, P911, IFX, RHM |
| EU-Other | 4 | ASML, LVMH, Novo Nordisk, BNP |
| EU-Indizes | 3 | DAX 40, EuroStoxx 50, MDAX |
| Asien | 5 | Toyota, Sony, Tencent, Alibaba, TSMC |
| Asia/EM ETF | 4 | Nikkei, China, Indien, Brasilien |
| **FX (neu)** | 4 | EUR/USD, GBP/USD, USD/JPY, EUR/CHF |
| Commodities | 7 | Gold, Silber, Platin, Palladium, Brent, Erdgas, Kupfer |
| Crypto | 4 | BTC, ETH, SOL, XRP |

### Mini-Future-Strategie

- **Hebel-Range:** 5–10× (Target 7×)
- **Knock-Out-Buffer:** Trade wird nur eröffnet, wenn Spot ≥ 2 % vom Knock-Out entfernt
- **Bevorzugte Emittenten:** Morgan Stanley → Goldman Sachs → Société Générale → HSBC
- **SHORT-Trades** werden über SHORT-Mini-Futures realisiert (kein separater Inverse-ETF mehr)
- **Knock-Out-Monitoring** in jedem Run: ist Spot durchgebrochen → automatische Schließung

### Auswahl-Algorithmus (`os_selector.py`)

1. onvista.de durchsuchen mit Filter: Underlying + Hebel-Range + Long/Short
2. Kandidaten parsen (WKN, Strike, Knock-Out, Hebel, Bid/Ask, Emittent)
3. Score = `abs(hebel - target) + emittent_penalty + spread_penalty`
4. Niedrigster Score gewinnt

### Quote-Pipeline (`os_quotes.py`)

1. **LS Exchange Live-Quote** (JSON-API, 60s-Cache)
2. Fallback: **theoretischer Preis** = (Spot − Strike) × Bezugsverhältnis
3. Quelle wird im Trade-Journal mitgeloggt (`exit_source` Spalte)

---

## Was bleibt unverändert

- **Score-Logik** (BB/RSI/SMA, Buy ≥ 5, Sell ≤ -3) — identisch zum v1
- **Risk-Management** (Kelly 6.94 %, max 80 % Exposure, max 4/Sektor)
- **Fee-Modell** (0.30 % all-in)
- **VIX-Cap** (kein Entry bei VIX > 30)
- **NaN-Defenses** aus dem v1-Fix vom 2026-04-14 vormittag

---

## Parallelbetrieb

Der **Spot-Bot bleibt aktiv** (`paper_trading.py` mit `paper_portfolio.json`).
Der **OS-Bot läuft parallel** mit eigenen State-Files:

- `paper_portfolio_os.json` (separates Portfolio mit Mini-Future-Positionen)
- `journal_os.csv` (separates Trade-Journal)
- `paper-trading-os.yml` (separater GitHub-Actions Workflow, 3×/Tag scheduled)

Beide Bots beeinflussen sich nicht. So lässt sich die Performance direkt vergleichen.

---

## Bekannte Limitationen / Risiken

1. **onvista-Scraping ist fragil.** Sollte sich das HTML ändern, bricht die WKN-Suche.
   Im Fehlerfall wird der Trade übersprungen (kein Spot-Fallback).
2. **LS Exchange JSON-API ist inoffiziell.** Endpoint kann sich ändern.
3. **Knock-Out-Risiko.** Bei Hebel 5–10× und 2 % Buffer kann ein Gap-Down zum
   Totalverlust der Position führen — by design.
4. **Bezugsverhältnis-Annahme.** Aktuell wird 0.1 angenommen wenn nicht aus
   onvista parsed. Sollte später aus den Stammdaten gelesen werden.
5. **Keine Backtests.** v2.0 läuft direkt im Paper-Trading. Historische
   Mini-Future-Preise sind nicht trivial zu beschaffen.

---

## Test-Plan

1. **Initial-Run** mit DRY_RUN=true → Verifikation, dass Signal-Logik läuft und
   keine NaN/Crashes auftreten.
2. **24h-Beobachtung** mit DRY_RUN=false → erste echten Trades.
3. **Wöchentliches Review** der `journal_os.csv` → P&L vs. Spot-Bot vergleichen.
4. Falls onvista- oder LS-Endpoints brechen: Issue + Fallback einbauen.

---

## Commit-Plan

| File | Commit-Message |
|---|---|
| `universe.py` | feat(os): erweitertes 62-Underlying-Universum |
| `os_selector.py` | feat(os): Mini-Future-Selector via onvista |
| `os_quotes.py` | feat(os): LS Exchange Live-Quote-Fetcher |
| `paper_trading_os.py` | feat(os): Paper-Trading auf Mini-Futures (v2.0) |
| `.github/workflows/paper-trading-os.yml` | ci(os): scheduled OS-Bot Workflow 3x täglich |
| `CHANGELOG_OS_BOT.md` | docs(os): v2.0 Änderungs-Dokumentation |
