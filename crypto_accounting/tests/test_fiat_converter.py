"""Tests for FiatConverter and Config."""

import unittest
from decimal import Decimal
from pathlib import Path
import tempfile, os, json

from ..config import Config, SUPPORTED_FIAT
from ..engine.fiat_converter import FiatConverter


class TestConfig(unittest.TestCase):

    def test_defaults(self):
        cfg = Config()
        self.assertEqual(cfg.base_currency, "USD")
        self.assertEqual(cfg.cost_basis_method, "fifo")
        self.assertTrue(cfg.include_fees_in_basis)

    def test_format_usd(self):
        cfg = Config(base_currency="USD")
        self.assertIn("$", cfg.format_amount(1234.5))

    def test_format_eur(self):
        cfg = Config(base_currency="EUR")
        self.assertIn("€", cfg.format_amount(1234.5))

    def test_save_and_load(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            cfg = Config(base_currency="EUR", cost_basis_method="hifo")
            cfg.save(path)
            loaded = Config.load(path)
            self.assertEqual(loaded.base_currency, "EUR")
            self.assertEqual(loaded.cost_basis_method, "hifo")
        finally:
            os.unlink(path)

    def test_from_dict_round_trip(self):
        cfg = Config(base_currency="GBP", tax_year_start_month=4)
        cfg2 = Config.from_dict(cfg.to_dict())
        self.assertEqual(cfg2.base_currency, "GBP")
        self.assertEqual(cfg2.tax_year_start_month, 4)

    def test_supported_fiat_contains_majors(self):
        for code in ("USD", "EUR", "GBP", "JPY", "CAD"):
            self.assertIn(code, SUPPORTED_FIAT)


class TestFiatConverter(unittest.TestCase):

    def _make_converter(self, rates: dict, base="USD") -> FiatConverter:
        """Helper: create a converter pre-loaded with given EUR-based rates."""
        cfg = Config(base_currency=base)
        conv = FiatConverter(cfg, cache_dir=Path(tempfile.mkdtemp()))
        conv._eur_rates = rates
        conv._loaded = True
        return conv

    def test_same_currency(self):
        conv = self._make_converter({"USD": 1.09, "EUR": 1.0})
        self.assertEqual(conv.get_rate("USD", "USD"), Decimal("1"))

    def test_usd_to_eur(self):
        # EUR rates: USD=1.09, so 1 EUR = 1.09 USD → 1 USD = 1/1.09 EUR ≈ 0.9174
        conv = self._make_converter({"USD": 1.09})
        rate = conv.get_rate("USD", "EUR")
        # 1 USD → EUR: EUR_rate/USD_rate = 1.0/1.09
        expected = Decimal("1") / Decimal("1.09")
        self.assertAlmostEqual(float(rate), float(expected), places=4)

    def test_cross_rate(self):
        conv = self._make_converter({"USD": 1.09, "GBP": 0.86})
        rate = conv.get_rate("USD", "GBP")
        expected = 0.86 / 1.09
        self.assertAlmostEqual(float(rate), expected, places=4)

    def test_convert_to_base(self):
        conv = self._make_converter({"USD": 1.09}, base="EUR")
        result = conv.convert_to_base(Decimal("109"), "USD")
        # 109 USD → EUR: 109 * (1/1.09) ≈ 100
        self.assertAlmostEqual(float(result), 100.0, places=2)

    def test_manual_rate_override(self):
        conv = self._make_converter({"USD": 1.09})
        conv.set_manual_rate("USD", "EUR", 0.90)
        rate = conv.get_rate("USD", "EUR")
        self.assertEqual(rate, Decimal("0.9"))

    def test_missing_currency_raises(self):
        conv = self._make_converter({"USD": 1.09})
        with self.assertRaises(ValueError):
            conv.get_rate("USD", "UNKNOWN")

    def test_get_all_rates_returns_dict(self):
        conv = self._make_converter({"USD": 1.09, "GBP": 0.86, "JPY": 163.5})
        rates = conv.get_all_rates()
        self.assertIsInstance(rates, dict)
        self.assertIn("GBP", rates)

    def test_ecb_xml_parsing(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                         xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
          <Cube>
            <Cube time="2024-01-15">
              <Cube currency="USD" rate="1.0921"/>
              <Cube currency="GBP" rate="0.8601"/>
              <Cube currency="JPY" rate="161.03"/>
            </Cube>
          </Cube>
        </gesmes:Envelope>"""
        conv = self._make_converter({})
        rates = conv._parse_ecb_xml(xml)
        self.assertEqual(rates["USD"], 1.0921)
        self.assertEqual(rates["GBP"], 0.8601)
        self.assertIn("EUR", rates)


class TestWalletImporter(unittest.TestCase):

    def test_generic_csv_import(self):
        import tempfile, os
        csv_content = (
            "Trade Date,Action,Coin,Amount,USD Value\n"
            "2023-01-15,Buy,BTC,0.5,15000\n"
            "2023-06-01,Sell,BTC,0.25,8000\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            path = f.name
        try:
            from ..engine.wallet_importer import WalletImporter
            from ..models.transaction import TransactionType
            txns = WalletImporter().from_generic_csv(
                path,
                column_map={"date": "Trade Date", "type": "Action", "asset": "Coin",
                            "quantity": "Amount", "total_usd": "USD Value"},
                date_format="%Y-%m-%d",
                type_map={"Buy": TransactionType.BUY, "Sell": TransactionType.SELL},
            )
            self.assertEqual(len(txns), 2)
            self.assertEqual(txns[0].type, TransactionType.BUY)
            self.assertEqual(txns[1].type, TransactionType.SELL)
            from decimal import Decimal
            self.assertEqual(txns[0].quantity, Decimal("0.5"))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
