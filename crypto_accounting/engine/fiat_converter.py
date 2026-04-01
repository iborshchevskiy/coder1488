"""
FiatConverter – fetches and caches fiat-to-fiat exchange rates.

Providers
---------
- ECB (European Central Bank) daily XML feed – free, no key required.
  All rates are vs EUR; we triangulate through EUR for cross-rates.
- ExchangeRate-API – requires a free API key for higher frequency.
- Manual – rates stored in the system Config.

Usage::

    converter = FiatConverter(config)
    rate = converter.get_rate("USD", "EUR")   # USD → EUR
    amount_eur = converter.convert(1000, "USD", "EUR")
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

from ..config import Config

log = logging.getLogger(__name__)

_ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
_ECB_HIST_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
_CACHE_TTL_HOURS = 4

# Fallback hardcoded rates (EUR-based, approximate) used when offline
_FALLBACK_EUR_RATES: Dict[str, float] = {
    "USD": 1.09, "GBP": 0.86, "JPY": 163.5, "CAD": 1.49,
    "AUD": 1.65, "CHF": 0.98, "CNY": 7.88, "SEK": 11.38,
    "NOK": 11.77, "DKK": 7.46, "NZD": 1.78, "SGD": 1.47,
    "HKD": 8.50, "KRW": 1445.0, "BRL": 5.85, "INR": 90.4,
    "MXN": 18.9, "PLN": 4.28, "ZAR": 20.2,
}


class RateCache:
    """Simple JSON file cache for exchange rates."""

    def __init__(self, cache_dir: Path) -> None:
        self._path = cache_dir / "fx_rates.json"
        self._data: dict = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except Exception:
                return {}
        return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))

    def get(self, provider: str, date_key: str) -> Optional[Dict[str, float]]:
        entry = self._data.get(f"{provider}:{date_key}")
        if not entry:
            return None
        cached_at = datetime.fromisoformat(entry["cached_at"])
        if datetime.utcnow() - cached_at > timedelta(hours=_CACHE_TTL_HOURS):
            return None
        return entry["rates"]

    def set(self, provider: str, date_key: str, rates: Dict[str, float]) -> None:
        self._data[f"{provider}:{date_key}"] = {
            "rates": rates,
            "cached_at": datetime.utcnow().isoformat(),
        }
        self._save()


class FiatConverter:
    """
    Converts amounts between fiat currencies.
    All internal rates are stored relative to EUR (ECB convention).
    """

    def __init__(
        self,
        config: Config,
        cache_dir: Optional[Path] = None,
    ) -> None:
        self._config = config
        cache_dir = cache_dir or (Path.home() / ".crypto_accounting")
        self._cache = RateCache(cache_dir)
        # EUR-based rates: {"USD": 1.09, "GBP": 0.86, ...}
        self._eur_rates: Dict[str, float] = {}
        self._loaded = False

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self._load_rates()

    def get_rate(self, from_currency: str, to_currency: str) -> Decimal:
        """Return the exchange rate: 1 unit of from_currency = X units of to_currency."""
        self.ensure_loaded()
        from_c = from_currency.upper()
        to_c = to_currency.upper()
        if from_c == to_c:
            return Decimal("1")

        # Check manual overrides first
        manual_key = f"{from_c}{to_c}"
        if manual_key in self._config.manual_rates:
            return Decimal(str(self._config.manual_rates[manual_key]))

        # Triangulate through EUR
        from_eur = self._to_eur_rate(from_c)
        to_eur = self._to_eur_rate(to_c)
        if from_eur is None or to_eur is None:
            raise ValueError(f"Exchange rate not available: {from_c} → {to_c}")
        rate = to_eur / from_eur
        return Decimal(str(round(rate, 8)))

    def convert(
        self, amount: Decimal | float, from_currency: str, to_currency: str
    ) -> Decimal:
        """Convert *amount* from one fiat currency to another."""
        rate = self.get_rate(from_currency, to_currency)
        return (Decimal(str(amount)) * rate).quantize(Decimal("0.000001"))

    def convert_to_base(self, amount: Decimal | float, from_currency: str) -> Decimal:
        """Convert *amount* to the configured base currency."""
        return self.convert(amount, from_currency, self._config.base_currency)

    def get_all_rates(self) -> Dict[str, Decimal]:
        """Return rates for all currencies relative to base currency."""
        self.ensure_loaded()
        base = self._config.base_currency
        rates = {}
        for currency in list(self._eur_rates.keys()) + ["EUR"]:
            try:
                rates[currency] = self.get_rate(base, currency)
            except ValueError:
                pass
        return rates

    def set_manual_rate(self, from_currency: str, to_currency: str, rate: float) -> None:
        key = f"{from_currency.upper()}{to_currency.upper()}"
        self._config.manual_rates[key] = rate

    @property
    def last_updated(self) -> Optional[str]:
        return self._eur_rates.get("_date")

    # ------------------------------------------------------------------ #
    # Rate loading
    # ------------------------------------------------------------------ #

    def _load_rates(self) -> None:
        today = date.today().isoformat()

        # 1. Try cache
        cached = self._cache.get(self._config.rate_provider, today)
        if cached:
            self._eur_rates = cached
            self._loaded = True
            return

        # 2. Try live fetch
        rates = None
        if self._config.rate_provider in ("ecb", "auto"):
            rates = self._fetch_ecb()
        elif self._config.rate_provider == "exchangerate-api" and self._config.rate_api_key:
            rates = self._fetch_exchangerate_api()

        if rates:
            rates["_date"] = today
            self._cache.set(self._config.rate_provider, today, rates)
            self._eur_rates = rates
            self._loaded = True
            log.info("Loaded live FX rates for %s", today)
            return

        # 3. Fallback to hardcoded rates (offline mode)
        log.warning("Using fallback FX rates (offline mode)")
        self._eur_rates = dict(_FALLBACK_EUR_RATES)
        self._eur_rates["_date"] = "fallback"
        self._loaded = True

    def _fetch_ecb(self) -> Optional[Dict[str, float]]:
        """Fetch daily rates from the ECB XML feed."""
        try:
            req = Request(_ECB_URL, headers={"User-Agent": "crypto-accounting/1.0"})
            with urlopen(req, timeout=5) as resp:
                xml_data = resp.read()
            return self._parse_ecb_xml(xml_data)
        except (URLError, Exception) as e:
            log.warning("ECB fetch failed: %s", e)
            return None

    def _parse_ecb_xml(self, xml_data: bytes) -> Dict[str, float]:
        """Parse ECB Cube XML into a dict of EUR-based rates."""
        ns = {"ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}
        root = ET.fromstring(xml_data)
        rates: Dict[str, float] = {"EUR": 1.0}
        for cube in root.findall(".//ecb:Cube[@currency]", ns):
            currency = cube.attrib["currency"]
            rate = float(cube.attrib["rate"])
            rates[currency] = rate
        return rates

    def _fetch_exchangerate_api(self) -> Optional[Dict[str, float]]:
        """Fetch from exchangerate-api.com (free tier, EUR base)."""
        url = f"https://v6.exchangerate-api.com/v6/{self._config.rate_api_key}/latest/EUR"
        try:
            req = Request(url, headers={"User-Agent": "crypto-accounting/1.0"})
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            if data.get("result") == "success":
                return {k: float(v) for k, v in data["conversion_rates"].items()}
        except (URLError, Exception) as e:
            log.warning("ExchangeRate-API fetch failed: %s", e)
        return None

    def _to_eur_rate(self, currency: str) -> Optional[float]:
        """How many units of *currency* equal 1 EUR."""
        if currency == "EUR":
            return 1.0
        rate = self._eur_rates.get(currency)
        if rate is None:
            return None
        return float(rate)
