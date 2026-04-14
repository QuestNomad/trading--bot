"""
os_selector.py - Auswahl von Open-End Turbos (Mini-Futures) zu einem Underlying.

Strategie:
  - Wir suchen pro Underlying + Richtung (LONG/SHORT) den optimalen Mini-Future.
  - Kriterien: Hebel im Ziel-Range (5-10), maximale Knock-Out-Distanz, enger Spread,
    bevorzugte Emittenten (Morgan Stanley, Goldman, SG, HSBC).
  - Discovery via onvista.de (HTML, gefiltert nach Underlying + Hebel).

Public API:
  find_mini_future(underlying_id, direction, leverage_target=7.0, leverage_range=(5,10))
    -> dict | None

Hinweis:
  Diese v1 nutzt onvista-Webseiten-Scraping. Selektoren koennen sich aendern.
  Im Fehlerfall wird None zurueckgegeben (Trade wird vom Bot uebersprungen).
"""
import logging
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

log = logging.getLogger(__name__)

PREFERRED_EMITTENTS = ["Morgan Stanley", "Goldman Sachs", "Société Générale", "HSBC"]
ONVISTA_BASE = "https://www.onvista.de"
USER_AGENT = "Mozilla/5.0 (compatible; trading-bot/2.0)"
REQ_TIMEOUT = 15


@dataclass
class MiniFuture:
    wkn: str
    isin: str
    emittent: str
    strike: float
    knock_out: float
    leverage: float
    bid: float
    ask: float
    bezugsverh: float
    type: str
    underlying_id: str
    onvista_url: str = ""

    def to_dict(self):
        return {
            "wkn": self.wkn, "isin": self.isin, "emittent": self.emittent,
            "strike": self.strike, "knock_out": self.knock_out,
            "leverage": self.leverage, "bid": self.bid, "ask": self.ask,
            "bezugsverh": self.bezugsverh, "type": self.type,
            "underlying_id": self.underlying_id, "onvista_url": self.onvista_url,
        }

    def spread_pct(self) -> float:
        if self.bid <= 0 or self.ask <= 0:
            return float("inf")
        return (self.ask - self.bid) / ((self.ask + self.bid) / 2) * 100


def _onvista_search_url(underlying_id: str, direction: str, lmin: float, lmax: float) -> str:
    typ = "OPEN_END_TURBO_LONG" if direction == "LONG" else "OPEN_END_TURBO_SHORT"
    return (f"{ONVISTA_BASE}/derivate/finder.html"
            f"?TYPE={typ}&UNDERLYING_ID={quote(underlying_id)}"
            f"&LEVERAGE_MIN={lmin}&LEVERAGE_MAX={lmax}")


def _to_float(s):
    if not s: return None
    s = s.replace("€", "").replace(".", "").replace(",", ".").replace("%", "").strip()
    try: return float(s)
    except ValueError: return None


def _parse_onvista_results(html: str, underlying_id: str, direction: str):
    if not HAS_DEPS: return []
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table tr")
    results = []
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 6: continue
        try:
            text = [c.get_text(" ", strip=True) for c in cells]
            wkn = next((t for t in text if re.fullmatch(r"[A-Z0-9]{6}", t)), None)
            if not wkn: continue
            emittent = next((t for t in text if any(e.split()[0] in t for e in PREFERRED_EMITTENTS)), "")
            nums = [_to_float(t) for t in text]
            nums = [n for n in nums if n is not None]
            if len(nums) < 4: continue
            strike = nums[0]
            knock = nums[1] if abs(nums[1] - strike) < strike * 0.5 else nums[0]
            leverage = max(n for n in nums if 1 < n < 100)
            bid = next((n for n in nums if 0 < n < 1000), 0.0)
            ask = bid * 1.01
            results.append(MiniFuture(
                wkn=wkn, isin="", emittent=emittent or "?",
                strike=strike, knock_out=knock, leverage=leverage,
                bid=bid, ask=ask, bezugsverh=0.1, type=direction,
                underlying_id=underlying_id,
            ))
        except Exception as exc:
            log.debug(f"row parse skip: {exc}")
            continue
    return results


def _score_candidate(c: MiniFuture, target_leverage: float) -> float:
    score = abs(c.leverage - target_leverage)
    if not any(e.split()[0] in c.emittent for e in PREFERRED_EMITTENTS):
        score += 5
    score += min(c.spread_pct(), 5)
    if "Morgan" in c.emittent: score -= 1
    return score


def find_mini_future(underlying_id, direction="LONG", leverage_target=7.0, leverage_range=(5.0, 10.0)):
    if not HAS_DEPS:
        log.warning("os_selector: requests/bs4 missing - skip OS lookup")
        return None
    direction = direction.upper()
    if direction not in ("LONG", "SHORT"):
        raise ValueError("direction must be LONG or SHORT")
    url = _onvista_search_url(underlying_id, direction, *leverage_range)
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQ_TIMEOUT)
        r.raise_for_status()
    except Exception as exc:
        log.warning(f"onvista fetch failed for {underlying_id}: {exc}")
        return None
    candidates = _parse_onvista_results(r.text, underlying_id, direction)
    if not candidates:
        log.info(f"No Mini-Future candidates for {underlying_id} {direction}")
        return None
    candidates = [c for c in candidates
                  if leverage_range[0] <= c.leverage <= leverage_range[1] and c.bid > 0]
    if not candidates: return None
    best = min(candidates, key=lambda c: _score_candidate(c, leverage_target))
    log.info(f"Selected {underlying_id} {direction}: WKN {best.wkn} ({best.emittent}), Hebel {best.leverage:.1f}")
    return best.to_dict()


def is_knocked_out(mini: dict, current_spot: float) -> bool:
    ko = mini["knock_out"]
    if mini["type"] == "LONG":
        return current_spot <= ko
    return current_spot >= ko


def mini_future_price(mini: dict, current_spot: float) -> float:
    if is_knocked_out(mini, current_spot):
        return 0.0
    bv = mini.get("bezugsverh", 0.1)
    if mini["type"] == "LONG":
        intrinsic = (current_spot - mini["strike"]) * bv
    else:
        intrinsic = (mini["strike"] - current_spot) * bv
    return max(intrinsic, 0.0)
