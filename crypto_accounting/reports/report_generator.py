"""
ReportGenerator – produces text, CSV, and JSON reports.

Reports available
-----------------
- Portfolio summary   : current holdings and (if prices given) market values
- Capital gains       : realised gain/loss per disposal, grouped by year
- Income              : mining / staking / airdrop income by year
- Transaction ledger  : full list of transactions
"""

from __future__ import annotations

import csv
import json
import sys
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional, TextIO

from ..engine.tax_engine import GainRecord, TaxEngine, CostBasisMethod
from ..engine.portfolio import Portfolio, HoldingSnapshot
from ..engine.transaction_store import TransactionStore
from ..models.transaction import TransactionType


_SEP = "-" * 72


class ReportGenerator:
    def __init__(
        self,
        store: TransactionStore,
        method: CostBasisMethod = CostBasisMethod.FIFO,
        prices: Optional[Dict[str, Decimal]] = None,
    ) -> None:
        self._store = store
        self._method = method
        self._prices = prices or {}

        self._engine = TaxEngine(store, method)
        self._engine.compute()

        self._portfolio = Portfolio.from_store(store)

    # ------------------------------------------------------------------ #
    # Portfolio report
    # ------------------------------------------------------------------ #

    def portfolio_text(self, out: TextIO = sys.stdout) -> str:
        holdings = self._portfolio.holdings(self._prices or None)
        buf = StringIO()

        buf.write(_SEP + "\n")
        buf.write("  PORTFOLIO SUMMARY\n")
        buf.write(_SEP + "\n")

        if not holdings:
            buf.write("  No holdings found.\n")
        else:
            header = f"{'Asset':<8} {'Quantity':>20} {'Avg Cost':>12} {'Total Basis':>14}"
            if self._prices:
                header += f" {'Mkt Value':>14} {'Unreal P&L':>14} {'%':>8}"
            buf.write(header + "\n")
            buf.write("-" * len(header) + "\n")

            total_basis = Decimal("0")
            total_mv = Decimal("0")
            for h in holdings:
                qty_str = f"{h.quantity:.8f}".rstrip("0").rstrip(".")
                line = (
                    f"{h.asset:<8} {qty_str:>20} "
                    f"${h.average_cost_usd:>11,.2f} "
                    f"${h.total_cost_basis:>13,.2f}"
                )
                total_basis += h.total_cost_basis
                if self._prices:
                    mv = h.market_value_usd or Decimal("0")
                    pnl = h.unrealised_pnl_usd or Decimal("0")
                    pct = h.unrealised_pnl_pct or Decimal("0")
                    total_mv += mv
                    sign = "+" if pnl >= 0 else ""
                    line += (
                        f"  ${mv:>12,.2f}  {sign}${pnl:>11,.2f}  {sign}{pct:>6.2f}%"
                    )
                buf.write(line + "\n")

            buf.write("-" * len(header) + "\n")
            footer = f"{'TOTAL':<8} {' ':>20} {' ':>12} ${total_basis:>13,.2f}"
            if self._prices:
                pnl = total_mv - total_basis
                sign = "+" if pnl >= 0 else ""
                footer += f"  ${total_mv:>12,.2f}  {sign}${pnl:>11,.2f}"
            buf.write(footer + "\n")

        result = buf.getvalue()
        out.write(result)
        return result

    # ------------------------------------------------------------------ #
    # Capital gains report
    # ------------------------------------------------------------------ #

    def capital_gains_text(
        self,
        year: Optional[int] = None,
        out: TextIO = sys.stdout,
    ) -> str:
        records = self._engine.gains(year)
        buf = StringIO()

        label = str(year) if year else "All Years"
        buf.write(_SEP + "\n")
        buf.write(f"  CAPITAL GAINS / LOSSES  ({label})  [{self._method.value.upper()}]\n")
        buf.write(_SEP + "\n")

        if not records:
            buf.write("  No disposals found.\n")
        else:
            header = (
                f"{'Date':<12} {'Asset':<8} {'Qty':>18} "
                f"{'Proceeds':>12} {'Basis':>12} {'Fees':>8} "
                f"{'Gain/Loss':>12} {'Term':<12}"
            )
            buf.write(header + "\n")
            buf.write("-" * len(header) + "\n")

            for r in records:
                sign = "+" if r.gain_loss_usd >= 0 else ""
                qty_str = f"{r.quantity_disposed:.8f}".rstrip("0").rstrip(".")
                buf.write(
                    f"{r.disposal_date.date()!s:<12} {r.asset:<8} {qty_str:>18} "
                    f"${r.proceeds_usd:>10,.2f}  "
                    f"${r.cost_basis_usd:>10,.2f}  "
                    f"${r.fee_usd:>6,.2f}  "
                    f"{sign}${r.gain_loss_usd:>10,.2f}  "
                    f"{r.term:<12}\n"
                )

            summary = self._engine.summary(year)
            buf.write("-" * len(header) + "\n")
            buf.write(
                f"\n  Total gain/loss   : ${summary['total_gain_loss_usd']:>12,.2f}\n"
                f"  Long-term         : ${summary['long_term_gain_loss_usd']:>12,.2f}\n"
                f"  Short-term        : ${summary['short_term_gain_loss_usd']:>12,.2f}\n"
                f"  Number of disposals: {summary['num_disposals']}\n"
            )

        result = buf.getvalue()
        out.write(result)
        return result

    # ------------------------------------------------------------------ #
    # Income report
    # ------------------------------------------------------------------ #

    def income_text(
        self,
        year: Optional[int] = None,
        out: TextIO = sys.stdout,
    ) -> str:
        income_types = {TransactionType.MINING, TransactionType.INCOME, TransactionType.RECEIVE}
        txns = self._store.by_type(*income_types)
        if year:
            txns = [t for t in txns if t.date.year == year]

        buf = StringIO()
        label = str(year) if year else "All Years"
        buf.write(_SEP + "\n")
        buf.write(f"  INCOME REPORT  ({label})\n")
        buf.write(_SEP + "\n")

        if not txns:
            buf.write("  No income transactions found.\n")
        else:
            header = (
                f"{'Date':<12} {'Type':<14} {'Asset':<8} "
                f"{'Qty':>18} {'Value USD':>12} {'Notes'}"
            )
            buf.write(header + "\n")
            buf.write("-" * 80 + "\n")
            total = Decimal("0")
            for t in txns:
                val = t.total_usd or Decimal("0")
                total += val
                qty_str = f"{t.quantity:.8f}".rstrip("0").rstrip(".")
                buf.write(
                    f"{t.date.date()!s:<12} {t.type.value:<14} {t.asset:<8} "
                    f"{qty_str:>18} ${val:>10,.2f}  {t.notes or ''}\n"
                )
            buf.write("-" * 80 + "\n")
            buf.write(f"  Total income: ${total:,.2f} USD\n")

        result = buf.getvalue()
        out.write(result)
        return result

    # ------------------------------------------------------------------ #
    # Transaction ledger
    # ------------------------------------------------------------------ #

    def ledger_text(self, out: TextIO = sys.stdout) -> str:
        txns = self._store.all()
        buf = StringIO()

        buf.write(_SEP + "\n")
        buf.write("  TRANSACTION LEDGER\n")
        buf.write(_SEP + "\n")

        header = (
            f"{'Date':<12} {'Type':<14} {'Asset':<8} {'Qty':>18} "
            f"{'Total USD':>12} {'Fee USD':>8} {'Wallet':<16} {'Notes'}"
        )
        buf.write(header + "\n")
        buf.write("-" * len(header) + "\n")

        for t in txns:
            qty_str = f"{t.quantity:.8f}".rstrip("0").rstrip(".")
            total_str = f"${t.total_usd:,.2f}" if t.total_usd else "—"
            fee_str = f"${t.fee_usd:,.2f}" if t.fee_usd else "—"
            buf.write(
                f"{t.date.date()!s:<12} {t.type.value:<14} {t.asset:<8} "
                f"{qty_str:>18} {total_str:>12} {fee_str:>8} "
                f"{(t.wallet or ''):>16}  {t.notes or ''}\n"
            )

        result = buf.getvalue()
        out.write(result)
        return result

    # ------------------------------------------------------------------ #
    # CSV / JSON export
    # ------------------------------------------------------------------ #

    def save_capital_gains_csv(
        self, path: str | Path, year: Optional[int] = None
    ) -> None:
        path = Path(path)
        records = self._engine.gains(year)
        fields = [
            "disposal_date", "asset", "quantity", "proceeds_usd",
            "cost_basis_usd", "fee_usd", "gain_loss_usd", "term", "method",
        ]
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for r in records:
                writer.writerow({k: r.to_dict()[k] for k in fields})

    def save_capital_gains_json(
        self, path: str | Path, year: Optional[int] = None
    ) -> None:
        path = Path(path)
        records = self._engine.gains(year)
        with path.open("w", encoding="utf-8") as fh:
            json.dump([r.to_dict() for r in records], fh, indent=2)
