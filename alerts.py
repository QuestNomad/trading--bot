#!/usr/bin/env python3
"""
Telegram Alerting Module for Trading Bot.

Provides notification functions for:
- Trade execution alerts (buy/sell signals)
- Daily portfolio summaries
- Significant drawdown warnings (>5%)

Uses python-telegram-bot library.
Can be imported by both bot.py and paper_trading.py.
"""

import os
import logging
from datetime import datetime

import requests

# ââ Configuration ââââââââââââââââââââââââââââââââââââââââââââââ
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_TOKEN", ""))
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

DRAWDOWN_THRESHOLD = 0.05  # 5% drawdown triggers alert

logging.basicConfig(level=logging.INFO, format="%(asctime)s [alerts] %(message)s")
log = logging.getLogger(__name__)


# ââ Internal: send message via Telegram HTTP API âââââââââââââââ
def _send_telegram(text: str, parse_mode: str = "HTML") -> bool:
    """Send a message via Telegram Bot API. Returns True on success."""
    if DRY_RUN:
        log.info(f"[DRY-RUN] Telegram: {text[:150]}...")
        return True

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set â skipping alert.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
    }
    try:
        resp = requests.post(url, data=payload, timeout=15)
        if resp.status_code == 200:
            log.info("Telegram message sent successfully.")
            return True
        else:
            log.error(f"Telegram API error {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as exc:
        log.error(f"Telegram send failed: {exc}")
        return False


# ââ Public API âââââââââââââââââââââââââââââââââââââââââââââââââ

def send_trade_alert(
    asset_name: str,
    signal: str,
    price: float,
    score: int,
    stop_loss: float,
    take_profit: float,
    rsi: float = 0.0,
    atr: float = 0.0,
    position_size: float = 0.0,
    is_paper: bool = True,
) -> bool:

    mode_tag = "PAPER" if is_paper else "LIVE"
    signal_emoji = "KAUF" if "KAUFEN" in signal else "VERK"

    text = (
        f"{signal_emoji} <b>{signal}</b> - {asset_name}\n"
        f"Mode: {mode_tag}\n\n"
        f"Price: {price:,.2f}\n"
        f"Score: {score}/12\n"
        f"RSI: {rsi:.1f}\n"
        f"ATR: {atr:.2f}\n"
        f"Stop Loss: {stop_loss:,.2f}\n"
        f"Take Profit: {take_profit:,.2f}\n"
    )
    if position_size > 0:
        text += f"Position Size: {position_size:.4f}\n"

    text += f"\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
    return _send_telegram(text)


def send_daily_summary(
    portfolio_value: float,
    starting_capital: float,
    daily_pnl: float,
    total_pnl_pct: float,
    open_positions: int,
    trades_today: int,
    winners_today: int = 0,
    losers_today: int = 0,
    top_positions: list = None,
    is_paper: bool = True,
) -> bool:

    mode_tag = "PAPER TRADING" if is_paper else "LIVE TRADING"
    pnl_emoji = "UP" if daily_pnl >= 0 else "DOWN"
    total_emoji = "OK" if total_pnl_pct >= 0 else "BAD"

    text = (
        f"<b>Daily Summary - {mode_tag}</b>\n"
        f"{datetime.now().strftime('%Y-%m-%d')}\n\n"
        f"Portfolio: ${portfolio_value:,.2f}\n"
        f"Starting Capital: ${starting_capital:,.2f}\n"
        f"{pnl_emoji} Daily P&amp;L: ${daily_pnl:+,.2f}\n"
        f"{total_emoji} Total P&amp;L: {total_pnl_pct:+.2f}%\n\n"
        f"Open Positions: {open_positions}\n"
        f"Trades Today: {trades_today}\n"
    )

    if trades_today > 0:
        text += f"  Winners: {winners_today} | Losers: {losers_today}\n"

    if top_positions:
        text += "\n<b>Top Positions:</b>\n"
        for pos in top_positions[:5]:
            text += f"  {pos['asset']}: {pos.get('pnl_pct', 0):+.2f}%\n"

    return _send_telegram(text)


def send_drawdown_alert(
    current_value: float,
    peak_value: float,
    drawdown_pct: float,
    is_paper: bool = True,
) -> bool:

    mode_tag = "PAPER" if is_paper else "LIVE"

    text = (
        f"<b>DRAWDOWN ALERT - {mode_tag}</b>\n\n"
        f"Portfolio drawdown: <b>-{drawdown_pct:.2f}%</b>\n\n"
        f"Current Value: ${current_value:,.2f}\n"
        f"Peak Value: ${peak_value:,.2f}\n"
        f"Loss from Peak: ${peak_value - current_value:,.2f}\n\n"
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
        f"Consider reviewing open positions and risk exposure."
    )
    return _send_telegram(text)


def send_custom_alert(message: str) -> bool:
    """Send a free-form alert message."""
    return _send_telegram(message)


# ââ Self-test ââââââââââââââââââââââââââââââââââââââââââââââââââ
if __name__ == "__main__":
    print("=== Alerts Module Self-Test ===")
    print(f"TELEGRAM_BOT_TOKEN set: {bool(TELEGRAM_BOT_TOKEN)}")
    print(f"TELEGRAM_CHAT_ID set:   {bool(TELEGRAM_CHAT_ID)}")
    print(f"DRY_RUN:                {DRY_RUN}")

    send_trade_alert(
        asset_name="Apple", signal="KAUFEN", price=185.50,
        score=9, stop_loss=178.20, take_profit=205.00,
        rsi=42.5, atr=3.12, position_size=0.54, is_paper=True,
    )

    send_daily_summary(
        portfolio_value=10250.00, starting_capital=10000.00,
        daily_pnl=125.00, total_pnl_pct=2.50,
        open_positions=3, trades_today=2,
        winners_today=1, losers_today=1,
        top_positions=[{"asset": "Apple", "pnl_pct": 3.2}],
        is_paper=True,
    )

    send_drawdown_alert(
        current_value=9200.00, peak_value=10000.00,
        drawdown_pct=8.0, is_paper=True,
    )

    print("=== Self-Test Complete ===")
