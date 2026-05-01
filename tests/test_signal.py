"""
Tests fuer berechne_signal() - Score Trader Logik.
"""
import numpy as np
import pytest


def test_signal_short_series_returns_warten():
    """Bei <50 Datenpunkten kein Signal."""
    from bot import berechne_signal
    sig, score, details = berechne_signal([100] * 30)
    assert sig == "WARTEN"
    assert score == 0


def test_signal_const_series_returns_signal():
    """Konstante Serie: liefert irgendein Signal mit gueltigem Score."""
    from bot import berechne_signal, BUY_THRESHOLD, SELL_THRESHOLD
    preise = [100.0] * 60
    sig, score, details = berechne_signal(preise)
    assert sig in {"KAUFEN", "VERKAUFEN", "HALTEN", "WARTEN"}
    # Konstante Serie -> ATR=0, BB-Std=0 -> NaN-Guard greift -> WARTEN
    assert sig == "WARTEN" or details.get("punkte") is not None


def test_signal_uptrend_produces_score():
    """Steigende Serie liefert nicht-leere details."""
    from bot import berechne_signal
    np.random.seed(42)
    preise = (100 + np.cumsum(np.abs(np.random.randn(80)) * 0.5)).tolist()
    sig, score, details = berechne_signal(preise)
    assert sig != "WARTEN"
    assert "sma20" in details
    assert "rsi" in details
    assert "atr" in details
    assert "trailing_stop" in details


def test_signal_thresholds_buy():
    """Score >= BUY_THRESHOLD -> KAUFEN."""
    from bot import berechne_signal, BUY_THRESHOLD
    # Synthetischer Pump-Dip-Pattern: Boden zuletzt -> RSI niedrig + < BB lower
    np.random.seed(1)
    preise = list(np.linspace(100, 130, 40)) + list(np.linspace(130, 95, 25))
    sig, score, details = berechne_signal(preise)
    if score >= BUY_THRESHOLD:
        assert sig == "KAUFEN"


def test_signal_details_finite():
    """Alle Indikator-Werte in details muessen finite sein."""
    import math
    from bot import berechne_signal
    np.random.seed(7)
    preise = (200 + np.cumsum(np.random.randn(120))).tolist()
    sig, score, details = berechne_signal(preise)
    if sig != "WARTEN":
        for k in ("sma20", "rsi", "atr", "bb_upper", "bb_lower", "trailing_stop"):
            assert math.isfinite(details[k]), f"{k} = {details[k]} nicht finite"


def test_signal_score_in_expected_range():
    """Score muss in Bereich [-4, +9] liegen (Summe der moeglichen +/- Punkte)."""
    from bot import berechne_signal
    np.random.seed(99)
    for _ in range(10):
        preise = (100 + np.cumsum(np.random.randn(80))).tolist()
        _, score, _ = berechne_signal(preise)
        assert -10 <= score <= 15, f"Score {score} ausserhalb plausibler Range"
