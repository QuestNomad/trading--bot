"""
os_quotes.py - Live-Quotes fuer Mini-Futures via Lang & Schwarz Exchange.

LS Exchange ist ein deutscher ausserboerslicher Handelsplatz mit
sehr engen Spreads fuer OS und Zertifikate. Ueber den oeffentlichen
JSON-Endpoint koennen aktuelle Quotes abgefragt werden.

Public API:
  get_quote(wkn, isin=None) -> dict | None
    {wkn, isin, bid, ask, mid, ts}

Fallback: Wenn LS Exchange nicht verfuegbar, Rueckgabe None.
"""
import logging
import time
from typing import Optional

try:
    import requests
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

log = logging.getLogger(__name__)

LS_BASE = "https://www.ls-tc.de"
LS_QUOTE_URL = LS_BASE + "/_rpc/json/instrument/quote/{ident}"
USER_AGENT = "Mozilla/5.0 (compatible; trading-bot/2.0)"
REQ_TIMEOUT = 10
CACHE = {}
CACHE_TTL_SEC = 60


def _cache_get(key):
    entry = CACHE.get(key)
    if not entry: return None
    ts, data = entry
    if time.time() - ts > CACHE_TTL_SEC: return None
    return data


def _cache_put(key, data):
    CACHE[key] = (time.time(), data)


def get_quote(wkn, isin=None):
    if not HAS_DEPS:
        log.warning("os_quotes: requests missing - skip quote")
        return None
    if not wkn: return None
    cache_key = f"{wkn}|{isin or ''}"
    cached = _cache_get(cache_key)
    if cached: return cached
    for ident in [wkn, isin]:
        if not ident: continue
        url = LS_QUOTE_URL.format(ident=ident)
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQ_TIMEOUT)
            if r.status_code != 200: continue
            data = r.json()
        except Exception as exc:
            log.debug(f"LS fetch failed for {ident}: {exc}")
            continue
        bid = _extract_float(data, ["bid", "Bid", "bidPrice"])
        ask = _extract_float(data, ["ask", "Ask", "askPrice"])
        if bid and ask and bid > 0 and ask > 0:
            quote = {"wkn": wkn, "isin": isin or "",
                     "bid": bid, "ask": ask, "mid": (bid + ask) / 2, "ts": time.time()}
            _cache_put(cache_key, quote)
            return quote
    log.info(f"No LS quote for WKN={wkn}")
    return None


def _extract_float(data, keys):
    for k in keys:
        if isinstance(data, dict) and k in data:
            try: return float(data[k])
            except (ValueError, TypeError): continue
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, dict):
                r = _extract_float(v, keys)
                if r is not None: return r
    return None


def get_quote_or_compute(mini, current_spot):
    """
    Versuche 1: LS Exchange Live-Quote (mid).
    Versuche 2: theoretischer Preis aus Spot + Strike + Bezugsverhaeltnis.
    Returns: (price, source) wobei source 'LS' oder 'computed'.
    """
    quote = get_quote(mini.get("wkn"), mini.get("isin"))
    if quote and quote["mid"] > 0:
        return quote["mid"], "LS"
    from os_selector import mini_future_price
    return mini_future_price(mini, current_spot), "computed"
