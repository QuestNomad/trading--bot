"""
Tests fuer ASSETS-Liste in bot.py und Konsistenz mit universe.py.
"""
import pytest


def test_assets_count_88():
    """ASSETS muss exakt 88 Eintraege enthalten (universe.py v2.1)."""
    from bot import ASSETS
    assert len(ASSETS) == 88


def test_assets_no_duplicate_ids():
    from bot import ASSETS
    ids = [a["id"] for a in ASSETS]
    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, f"Duplikate IDs: {duplicates}"


def test_assets_all_have_required_keys():
    from bot import ASSETS
    required = {"name", "typ", "id", "symbol"}
    for a in ASSETS:
        missing = required - set(a.keys())
        assert not missing, f"Asset {a} fehlt {missing}"


def test_assets_typ_is_aktie_or_crypto():
    """In bot.py gibt es nur typ in {aktie, crypto}."""
    from bot import ASSETS
    for a in ASSETS:
        assert a["typ"] in ("aktie", "crypto"), \
            f"{a['name']}: unbekannter typ {a['typ']}"


def test_crypto_assets_use_coingecko_ids():
    """Crypto-Eintraege muessen coingecko-IDs als 'id' haben (kleinbuchstabig)."""
    from bot import ASSETS
    cryptos = [a for a in ASSETS if a["typ"] == "crypto"]
    assert len(cryptos) == 4
    for c in cryptos:
        assert c["id"].islower(), f"{c} id nicht coingecko-Format"
        assert c["id"] in {"bitcoin", "ethereum", "solana", "ripple"}


def test_short_etfs_flagged():
    from bot import ASSETS
    shorts = [a for a in ASSETS if a.get("short")]
    short_ids = {a["id"] for a in shorts}
    assert short_ids == {"XSPS.L", "DXSN.DE", "QQQS.L", "BITI"}


def test_universe_in_sync():
    """bot.ASSETS muss aus universe.ASSETS abgeleitet sein -> Counts stimmen."""
    from bot import ASSETS
    import universe
    # Anzahl gleich (alle Crypto haben coingecko-Mapping)
    assert len(ASSETS) == len(universe.ASSETS)


def test_universe_sectors_consistent():
    """Alle SECTORS-Symbole muessen in universe.ASSETS existieren."""
    import universe
    asset_ids = {a[0] for a in universe.ASSETS}
    missing = []
    for sec, syms in universe.SECTORS.items():
        for s in syms:
            if s not in asset_ids:
                missing.append((sec, s))
    assert not missing, f"SECTORS verweist auf unbekannte Symbole: {missing}"
