# Trading Bot

Automatisierter Signal-Bot für Aktien, ETFs, FX, Commodities und Crypto.
Bewertet ~88 Underlyings via technischer Analyse (Bollinger Bands, RSI, ATR)
plus News-Sentiment und sendet Buy/Sell-Signale via Telegram.

## Module

| Datei | Zweck |
|---|---|
| `bot.py` | Live-Signal-Bot mit Score-Modell, Half-Kelly Sizing, Sektor-Cap |
| `universe.py` | Asset-Universum (88 Underlyings) + SECTORS Single-Source-of-Truth |
| `arena.py` / `arena_backtest.py` | Strategie-Vergleich (Live + 10y-Backtest) |
| `backtest.py` / `backtest_os.py` | Backtests für Aktien und Optionsscheine |
| `paper_trading.py` / `paper_trading_os.py` | Paper Trading mit Portfolio-Tracking |
| `alerts.py`, `pnl_tracker.py`, `os_*.py` | Hilfsmodule |

## Strategie (Score Trader)

- Score = Σ Signale aus BB(20), RSI(14), ATR-Trailing-Stop (3×ATR), VADER Sentiment
- Buy: Score ≥ 8 · Sell: Score ≤ 3
- Risk: Half Kelly 6.94 % pro Position · Max-Exposure 80 % · max. 4 Positionen/Sektor
- Macro-Filter: VIX > 30 → Bot pausiert · SMA200-Regime-Filter (default off, optional)
- Trading-212 Cost-Modell: 0.30 % all-in (Fee + Spread + Slippage)

## Backtest-Performance (10 Jahre, Stand 2026-04-27)

| Strategie | Return % | MaxDD % | Sharpe |
|---|---:|---:|---:|
| 🥇 Score Trader | 2806 | −6.5 | 2.80 |
| 🥈 Adaptiv | 2088 | −20.8 | 1.37 |
| 🥉 Crash Guard | 460 | −10.1 | 1.24 |
| Buy & Hold | 510 | −32.3 | 0.87 |

## Setup

```powershell
git clone https://github.com/QuestNomad/trading--bot.git
cd trading--bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Secrets als Environment Variables setzen:
$env:TELEGRAM_TOKEN = "..."
$env:TELEGRAM_CHAT_ID = "..."
$env:DRY_RUN = "true"

python bot.py
```

## Workflows (GitHub Actions)

| Workflow | Schedule | Zweck |
|---|---|---|
| `bot.yml` | Mo-Fr 22:00 Wien | Live Trading Signals |
| `paper-trading.yml` | parallel | Paper Trading |
| `arena-backtest.yml` | manuell | Strategie-Vergleich |
| `backtest.yml` | manuell | Einzel-Backtest |
| `dry-run.yml` | manuell | Test ohne Telegram |

GitHub Secrets: `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `TRADING212_API_KEY`,
`BITPANDA_API_KEY`, `SHEETS_URL`, `ANTHROPIC_API_KEY`, `GMAIL_APP_PASSWORD`.

## Dashboard (lokal)

```powershell
pip install streamlit pandas requests
streamlit run scripts/dashboard.py
```

→ http://localhost:8501 mit Live-Status, Strategie-Ranking, Equity-Curve, STOP-Button.

## Lizenz

Privat, alle Rechte vorbehalten.
