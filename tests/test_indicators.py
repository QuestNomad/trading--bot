"""
Tests fuer technische Indikatoren in bot.py: SMA, RSI, ATR.
Daten synthetisch -> deterministisch, kein Network noetig.
"""
import math
import numpy as np
import pytest


def test_sma_basic():
    from bot import sma
    preise = list(range(1, 21))  # [1..20]
    result = sma(preise, 5)
    # Letzter Wert: mean(16,17,18,19,20) = 18.0
    assert math.isclose(float(result.iloc[-1]), 18.0)


def test_sma_with_const_series():
    from bot import sma
    preise = [100.0] * 50
    result = sma(preise, 20)
    # Konstante Serie -> SMA = Konstante
    assert math.isclose(float(result.iloc[-1]), 100.0)


def test_rsi_oversold_signal():
    """Fallender Trend -> RSI < 50 (typisch < 30)."""
    from bot import rsi_val
    preise = [100 - i * 0.5 for i in range(60)]  # monotoner Abfall
    rsi = rsi_val(preise)
    assert rsi < 30, f"Fallender Trend sollte RSI<30 liefern, war {rsi}"


def test_rsi_overbought_signal():
    """Steigender Trend -> RSI > 70."""
    from bot import rsi_val
    preise = [100 + i * 0.5 for i in range(60)]  # monotoner Anstieg
    rsi = rsi_val(preise)
    assert rsi > 70, f"Steigender Trend sollte RSI>70 liefern, war {rsi}"


def test_rsi_no_loss_returns_100():
    """Wenn nur Anstieg ohne Loss -> RSI = 100."""
    from bot import rsi_val
    preise = [100 + i for i in range(30)]
    rsi = rsi_val(preise)
    assert rsi == 100.0


def test_rsi_range_bounds():
    """RSI muss in [0, 100] liegen."""
    from bot import rsi_val
    np.random.seed(42)
    preise = (100 + np.cumsum(np.random.randn(100))).tolist()
    rsi = rsi_val(preise)
    assert 0 <= rsi <= 100


def test_atr_finite():
    """ATR auf zufaelligen Preisen ist endlich und positiv."""
    from bot import atr_val
    np.random.seed(42)
    preise = (100 + np.cumsum(np.random.randn(50))).tolist()
    atr = atr_val(preise)
    assert math.isfinite(atr)
    assert atr > 0


def test_atr_const_series_zero():
    """Konstante Preise -> ATR = 0."""
    from bot import atr_val
    preise = [100.0] * 30
    atr = atr_val(preise)
    assert math.isclose(atr, 0.0)
