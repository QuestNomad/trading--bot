# Score Trader — Projektdokumentation

**Autor:** Dr. Klaus Karrer
**Repository:** QuestNomad/trading--bot
**Stand:** 12. April 2026
**Status:** Paper Trading Phase (Start 13. April 2026)

---

## 1. Projektuebersicht

Score Trader ist ein automatisierter Trading-Bot mit Bollinger Bands, RSI, SMA20 und Trailing Stop-Loss (3x ATR) fuer 38 ETFs/Aktien via Trading 212.

## 2. Strategie-Vergleich (10J, 0.30% Gebuehren)

| Strategie | Return | Sharpe | Max DD | Trades | Win Rate |
|-----------|--------|--------|--------|--------|----------|
| Buy & Hold | 245% | 0.62 | -27.7% | 0 | - |
| Crash Guard | 434% | 1.20 | -10.1% | 50 | - |
| Momentum | 76% | 0.18 | -34.0% | 3730 | - |
| Adaptiv | 386% | 0.85 | -19.0% | 2940 | - |
| Ensemble | 103% | 0.25 | -37.5% | 322 | 45.4% |
| **Score Trader** | **4723%** | **2.54** | **-9.89%** | **4363** | **58.8%** |

## 3. Robustheitstests

### Out-of-Sample: Training 1135%/Sharpe 2.40 vs Blindtest 274%/Sharpe 2.77 - BESTANDEN
### Walk-Forward: 6/6 Fenster profitabel, Avg 64% p.a., Sharpe 2.71 - BESTANDEN
### Parameter-Sensitivitaet: 27/27 Kombis profitabel (2229%-8464%) - BESTANDEN
### Monte Carlo: Worst Case DD -16.8%, P(DD>30%)=0% - BESTANDEN
### Kelly: Half Kelly 6.94%/Trade empfohlen

## 4. Aenderungsprotokoll

| Datum | Aenderung |
|-------|-----------|
| 2026-03 | Projekt gestartet |
| 2026-04-08 | Bot Arena: 6 Strategien, 34 Assets |
| 2026-04-10 | Trading 212 Gebuehren + Ensemble Bug Fix |
| 2026-04-11 | Trailing Stop-Loss + 10J Backtest + 38 Assets |
| 2026-04-12 | Robustheitstests v1: Slippage, OOS, Param-Sens |
| 2026-04-12 | Robustheitstests v2: Walk-Forward, MC, Kelly |
| 2026-04-12 | Paper Trading + Telegram Alerts |
| 2026-04-12 | Telegram Bot @scoretrader_alert_bot eingerichtet |
| 2026-04-12 | Projektdokumentation erstellt |
