"""
CLI entry point for the Crypto Accounting System.

Usage examples
--------------
    # Show portfolio
    python -m crypto_accounting portfolio --ledger ledger.csv

    # Show capital gains for 2024 using HIFO
    python -m crypto_accounting gains --ledger ledger.csv --year 2024 --method hifo

    # Show income for 2024
    python -m crypto_accounting income --ledger ledger.csv --year 2024

    # Show full transaction ledger
    python -m crypto_accounting ledger --ledger ledger.csv

    # Export gains to CSV
    python -m crypto_accounting export-gains --ledger ledger.csv --out gains_2024.csv

    # Generate sample ledger
    python -m crypto_accounting demo
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from .engine.tax_engine import CostBasisMethod
from .engine.transaction_store import TransactionStore
from .reports.report_generator import ReportGenerator


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crypto_accounting",
        description="Crypto Accounting System – track transactions, compute gains, generate reports.",
    )
    parser.add_argument(
        "--ledger", "-l",
        default="ledger.csv",
        help="Path to the CSV ledger file (default: ledger.csv)",
    )
    parser.add_argument(
        "--method", "-m",
        choices=["fifo", "lifo", "hifo"],
        default="fifo",
        help="Cost-basis method (default: fifo)",
    )

    sub = parser.add_subparsers(dest="command")

    # portfolio
    p_port = sub.add_parser("portfolio", help="Show current portfolio holdings")
    p_port.add_argument(
        "--price", action="append", metavar="ASSET=USD",
        help="Current price for an asset, e.g. --price BTC=65000",
    )

    # gains
    p_gains = sub.add_parser("gains", help="Show realised capital gains/losses")
    p_gains.add_argument("--year", type=int, help="Filter by tax year")

    # income
    p_income = sub.add_parser("income", help="Show income (mining/staking/airdrops)")
    p_income.add_argument("--year", type=int, help="Filter by tax year")

    # ledger
    sub.add_parser("ledger", help="Print full transaction ledger")

    # export-gains
    p_exp = sub.add_parser("export-gains", help="Export capital gains to CSV or JSON")
    p_exp.add_argument("--out", required=True, help="Output file path (.csv or .json)")
    p_exp.add_argument("--year", type=int, help="Filter by tax year")

    # demo
    sub.add_parser("demo", help="Load a demo ledger and print all reports")

    return parser


def _parse_prices(price_args: list[str] | None) -> dict[str, Decimal]:
    if not price_args:
        return {}
    prices = {}
    for item in price_args:
        parts = item.split("=", 1)
        if len(parts) != 2:
            print(f"Warning: ignoring malformed price argument: {item}", file=sys.stderr)
            continue
        symbol, value = parts
        try:
            prices[symbol.upper()] = Decimal(value)
        except Exception:
            print(f"Warning: invalid price value: {item}", file=sys.stderr)
    return prices


def _load_store(ledger_path: str) -> TransactionStore:
    path = Path(ledger_path)
    if not path.exists():
        print(f"Error: ledger file not found: {path}", file=sys.stderr)
        sys.exit(1)
    return TransactionStore.load_csv(path)


def _demo_store() -> TransactionStore:
    """Build a small illustrative transaction store."""
    from datetime import datetime
    from .models.transaction import Transaction, TransactionType

    txns = [
        Transaction(
            type=TransactionType.BUY,
            date=datetime(2021, 1, 15),
            asset="BTC",
            quantity=Decimal("0.5"),
            price_usd=Decimal("35000"),
            fee_usd=Decimal("17.50"),
            wallet="Coinbase",
            notes="First BTC purchase",
        ),
        Transaction(
            type=TransactionType.BUY,
            date=datetime(2021, 6, 10),
            asset="ETH",
            quantity=Decimal("5"),
            price_usd=Decimal("2500"),
            fee_usd=Decimal("12.50"),
            wallet="Coinbase",
        ),
        Transaction(
            type=TransactionType.MINING,
            date=datetime(2021, 9, 1),
            asset="ETH",
            quantity=Decimal("0.25"),
            price_usd=Decimal("3200"),
            wallet="Home Miner",
            notes="Mining reward",
        ),
        Transaction(
            type=TransactionType.BUY,
            date=datetime(2022, 3, 20),
            asset="BTC",
            quantity=Decimal("0.25"),
            price_usd=Decimal("42000"),
            fee_usd=Decimal("10.50"),
            wallet="Kraken",
        ),
        Transaction(
            type=TransactionType.SELL,
            date=datetime(2022, 11, 8),
            asset="BTC",
            quantity=Decimal("0.3"),
            price_usd=Decimal("19500"),
            fee_usd=Decimal("5.85"),
            wallet="Coinbase",
            notes="Partial sell before FTX crash",
        ),
        Transaction(
            type=TransactionType.SELL,
            date=datetime(2023, 7, 14),
            asset="ETH",
            quantity=Decimal("2"),
            price_usd=Decimal("1900"),
            fee_usd=Decimal("3.80"),
            wallet="Coinbase",
        ),
        Transaction(
            type=TransactionType.SWAP,
            date=datetime(2024, 1, 5),
            asset="ETH",
            quantity=Decimal("1"),
            price_usd=Decimal("2300"),
            total_usd=Decimal("2300"),
            swap_asset="SOL",
            swap_quantity=Decimal("25"),
            wallet="Uniswap",
            notes="ETH -> SOL via DEX",
        ),
        Transaction(
            type=TransactionType.RECEIVE,
            date=datetime(2024, 3, 10),
            asset="BTC",
            quantity=Decimal("0.01"),
            price_usd=Decimal("71000"),
            total_usd=Decimal("710"),
            notes="Airdrop from partnership",
        ),
    ]
    store = TransactionStore()
    for t in txns:
        store.add(t)
    return store


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "demo":
        store = _demo_store()
        method = CostBasisMethod(args.method)
        demo_prices = {
            "BTC": Decimal("65000"),
            "ETH": Decimal("3500"),
            "SOL": Decimal("150"),
        }
        rg = ReportGenerator(store, method, demo_prices)
        rg.portfolio_text()
        print()
        rg.capital_gains_text()
        print()
        rg.income_text()
        print()
        rg.ledger_text()
        return

    if not args.command:
        parser.print_help()
        return

    store = _load_store(args.ledger)
    method = CostBasisMethod(args.method)

    if args.command == "portfolio":
        prices = _parse_prices(getattr(args, "price", None))
        rg = ReportGenerator(store, method, prices)
        rg.portfolio_text()

    elif args.command == "gains":
        rg = ReportGenerator(store, method)
        rg.capital_gains_text(year=getattr(args, "year", None))

    elif args.command == "income":
        rg = ReportGenerator(store, method)
        rg.income_text(year=getattr(args, "year", None))

    elif args.command == "ledger":
        rg = ReportGenerator(store, method)
        rg.ledger_text()

    elif args.command == "export-gains":
        rg = ReportGenerator(store, method)
        out_path = Path(args.out)
        year = getattr(args, "year", None)
        if out_path.suffix.lower() == ".json":
            rg.save_capital_gains_json(out_path, year)
        else:
            rg.save_capital_gains_csv(out_path, year)
        print(f"Exported to {out_path}")


if __name__ == "__main__":
    main()
