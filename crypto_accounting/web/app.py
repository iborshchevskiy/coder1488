"""
FastAPI application – REST API backend for the Crypto Accounting System.

Endpoints
---------
GET  /api/config                        – get system config
PUT  /api/config                        – update config
GET  /api/fx/rates                      – current FX rates relative to base currency
POST /api/fx/rates/manual               – set a manual rate override
GET  /api/portfolio                     – current crypto holdings
GET  /api/fiat-accounts                 – fiat currency account balances
GET  /api/fiat-accounts/{currency}      – single currency balance + ledger
GET  /api/transactions                  – list all transactions (filterable)
POST /api/transactions                  – add a transaction
DELETE /api/transactions/{id}           – remove a transaction
POST /api/import/csv                    – upload + auto-detect exchange CSV
POST /api/import/coinbase               – Coinbase CSV
POST /api/import/binance                – Binance CSV
POST /api/import/kraken                 – Kraken CSV
POST /api/import/crypto-com             – Crypto.com CSV
POST /api/import/blockchain/tron        – import from Tron address
POST /api/import/blockchain/eth         – import from Ethereum address
POST /api/import/blockchain/btc         – import from Bitcoin address
GET  /api/gains                         – realised capital gains
GET  /api/income                        – income transactions
GET  /api/summary                       – aggregate stats (year filter optional)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from ..config import Config, SUPPORTED_FIAT
from ..engine.transaction_store import TransactionStore
from ..engine.tax_engine import TaxEngine, CostBasisMethod
from ..engine.portfolio import Portfolio
from ..engine.fiat_converter import FiatConverter
from ..engine.wallet_importer import WalletImporter
from ..engine.blockchain_importer import BlockchainImporter
from ..engine.fiat_account import FiatAccountTracker
from ..models.transaction import Transaction, TransactionType
from ..config import FIAT_SYMBOLS
from ..storage import get_storage, FileStorage

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Application state
# ------------------------------------------------------------------ #

_DATA_DIR = Path.home() / ".crypto_accounting"

_state: Dict[str, Any] = {}


def _get_config() -> Config:
    return _state.get("config", Config())


def _get_store() -> TransactionStore:
    return _state.get("store", TransactionStore())


def _save_store() -> None:
    _state["storage"].save_store(_get_store())


@asynccontextmanager
async def _lifespan(app: FastAPI):
    storage = get_storage(_DATA_DIR)
    _state["storage"] = storage
    _state["config"] = storage.load_config()
    _state["store"] = storage.load_store()
    cache_dir = _DATA_DIR if isinstance(storage, FileStorage) else Path("/tmp/crypto_fx_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    _state["converter"] = FiatConverter(_get_config(), cache_dir)
    yield


# ------------------------------------------------------------------ #
# App factory
# ------------------------------------------------------------------ #

def create_app() -> FastAPI:
    app = FastAPI(
        title="Crypto Accounting System",
        version="2.0.0",
        lifespan=_lifespan,
    )

    # Serve the single-page UI
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def root():
        index = static_dir / "index.html"
        if index.exists():
            return HTMLResponse(index.read_text())
        return HTMLResponse("<h1>Crypto Accounting</h1><p>Static files not found.</p>")

    # ---------------------------------------------------------------- #
    # Config
    # ---------------------------------------------------------------- #

    @app.get("/api/config")
    async def get_config():
        cfg = _get_config()
        return {**cfg.to_dict(), "supported_fiat": SUPPORTED_FIAT}

    class ConfigUpdate(BaseModel):
        base_currency: Optional[str] = None
        cost_basis_method: Optional[str] = None
        tax_year_start_month: Optional[int] = None
        include_fees_in_basis: Optional[bool] = None
        rate_provider: Optional[str] = None
        rate_api_key: Optional[str] = None
        manual_rates: Optional[Dict[str, float]] = None

    @app.put("/api/config")
    async def update_config(body: ConfigUpdate):
        cfg = _get_config()
        data = cfg.to_dict()
        for key, val in body.model_dump(exclude_none=True).items():
            data[key] = val
        new_cfg = Config.from_dict(data)
        if new_cfg.base_currency not in SUPPORTED_FIAT:
            raise HTTPException(400, f"Unsupported currency: {new_cfg.base_currency}")
        _state["storage"].save_config(new_cfg)
        _state["config"] = new_cfg
        cache_dir = _DATA_DIR if isinstance(_state["storage"], FileStorage) else Path("/tmp/crypto_fx_cache")
        _state["converter"] = FiatConverter(new_cfg, cache_dir)
        return {"ok": True, "config": new_cfg.to_dict()}

    # ---------------------------------------------------------------- #
    # FX Rates
    # ---------------------------------------------------------------- #

    @app.get("/api/fx/rates")
    async def get_fx_rates():
        converter: FiatConverter = _state["converter"]
        try:
            converter.ensure_loaded()
            rates = converter.get_all_rates()
            return {
                "base": _get_config().base_currency,
                "rates": {k: str(v) for k, v in rates.items()},
                "last_updated": converter.last_updated,
            }
        except Exception as e:
            raise HTTPException(503, f"FX rates unavailable: {e}")

    class ManualRateBody(BaseModel):
        from_currency: str
        to_currency: str
        rate: float

    @app.post("/api/fx/rates/manual")
    async def set_manual_rate(body: ManualRateBody):
        converter: FiatConverter = _state["converter"]
        cfg = _get_config()
        converter.set_manual_rate(body.from_currency, body.to_currency, body.rate)
        cfg.manual_rates[f"{body.from_currency.upper()}{body.to_currency.upper()}"] = body.rate
        _state["storage"].save_config(cfg)
        return {"ok": True}

    # ---------------------------------------------------------------- #
    # Portfolio
    # ---------------------------------------------------------------- #

    @app.get("/api/portfolio")
    async def get_portfolio(prices: Optional[str] = Query(None, description="JSON: {BTC:65000,...}")):
        store = _get_store()
        portfolio = Portfolio.from_store(store)
        price_map: Optional[Dict[str, Decimal]] = None
        if prices:
            import json
            try:
                raw = json.loads(prices)
                price_map = {k.upper(): Decimal(str(v)) for k, v in raw.items()}
            except Exception:
                pass

        holdings = portfolio.holdings(price_map)
        cfg = _get_config()
        converter: FiatConverter = _state["converter"]
        converter.ensure_loaded()

        result = []
        for h in holdings:
            item = {
                "asset": h.asset,
                "quantity": str(h.quantity),
                "average_cost_usd": str(h.average_cost_usd.quantize(Decimal("0.01"))),
                "total_cost_basis_usd": str(h.total_cost_basis),
                "num_lots": h.num_lots,
            }
            if h.current_price_usd:
                item["market_value_usd"] = str(h.market_value_usd)
                item["unrealised_pnl_usd"] = str(h.unrealised_pnl_usd)
                item["unrealised_pnl_pct"] = str(h.unrealised_pnl_pct)
            # Convert to base currency
            if cfg.base_currency != "USD":
                rate = converter.get_rate("USD", cfg.base_currency)
                item["total_cost_basis_base"] = str(
                    (h.total_cost_basis * rate).quantize(Decimal("0.01"))
                )
                if h.market_value_usd:
                    item["market_value_base"] = str(
                        (h.market_value_usd * rate).quantize(Decimal("0.01"))
                    )
            result.append(item)

        total_basis = sum(h.total_cost_basis for h in holdings)
        total_mv = sum(
            h.market_value_usd for h in holdings if h.market_value_usd is not None
        ) or None

        return {
            "holdings": result,
            "summary": {
                "total_cost_basis_usd": str(total_basis.quantize(Decimal("0.01"))),
                "total_market_value_usd": str(total_mv.quantize(Decimal("0.01"))) if total_mv else None,
                "base_currency": cfg.base_currency,
            },
        }

    # ---------------------------------------------------------------- #
    # Fiat Accounts
    # ---------------------------------------------------------------- #

    @app.get("/api/fiat-accounts")
    async def get_fiat_accounts():
        """Return aggregate fiat balances per currency."""
        store = _get_store()
        tracker = FiatAccountTracker.from_store(store)
        accounts = tracker.accounts(include_zero=True)
        converter: FiatConverter = _state["converter"]
        cfg = _get_config()
        converter.ensure_loaded()

        result = []
        for acc in accounts:
            item = acc.to_dict()
            item["symbol"] = FIAT_SYMBOLS.get(acc.currency, acc.currency)
            # Convert balance to base currency if different
            if cfg.base_currency != acc.currency:
                try:
                    rate = converter.get_rate(acc.currency, cfg.base_currency)
                    item["balance_base"] = str(
                        (acc.balance * rate).quantize(Decimal("0.01"))
                    )
                    item["base_currency"] = cfg.base_currency
                except Exception:
                    pass
            result.append(item)

        # Total balance converted to base currency
        total_base = Decimal("0")
        for acc in accounts:
            try:
                rate = converter.get_rate(acc.currency, cfg.base_currency)
                total_base += acc.balance * rate
            except Exception:
                pass

        return {
            "accounts": result,
            "total_balance_base": str(total_base.quantize(Decimal("0.01"))),
            "base_currency": cfg.base_currency,
            "base_symbol": FIAT_SYMBOLS.get(cfg.base_currency, cfg.base_currency),
        }

    @app.get("/api/fiat-accounts/{currency}")
    async def get_fiat_account(
        currency: str,
        wallet: Optional[str] = None,
        limit: int = Query(200, le=2000),
    ):
        """Return balance and full ledger for a single fiat currency."""
        store = _get_store()
        tracker = FiatAccountTracker.from_store(store)
        currency = currency.upper()
        account = tracker.account(currency)
        if not account:
            raise HTTPException(404, f"No fiat account found for {currency}")

        entries = tracker.ledger(currency, wallet)
        return {
            "account": account.to_dict(),
            "ledger": [e.to_dict() for e in entries[-limit:]],
            "symbol": FIAT_SYMBOLS.get(currency, currency),
        }

    # ---------------------------------------------------------------- #
    # Transactions
    # ---------------------------------------------------------------- #

    @app.get("/api/transactions")
    async def list_transactions(
        asset: Optional[str] = None,
        type: Optional[str] = None,
        wallet: Optional[str] = None,
        year: Optional[int] = None,
        limit: int = Query(500, le=2000),
        offset: int = 0,
    ):
        store = _get_store()
        txns = store.all()
        if asset:
            txns = [t for t in txns if t.asset.upper() == asset.upper()]
        if type:
            try:
                tt = TransactionType(type)
                txns = [t for t in txns if t.type == tt]
            except ValueError:
                pass
        if wallet:
            txns = [t for t in txns if t.wallet == wallet]
        if year:
            txns = [t for t in txns if t.date.year == year]

        total = len(txns)
        page = txns[offset: offset + limit]
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "transactions": [t.to_dict() for t in page],
        }

    class TransactionBody(BaseModel):
        type: str
        date: str
        asset: str
        quantity: str
        price_usd: Optional[str] = None
        total_usd: Optional[str] = None
        fee_usd: Optional[str] = None
        fee_asset: Optional[str] = None
        fee_quantity: Optional[str] = None
        fiat_currency: Optional[str] = None
        fiat_amount: Optional[str] = None
        fx_rate_to_usd: Optional[str] = None
        swap_asset: Optional[str] = None
        swap_quantity: Optional[str] = None
        wallet: Optional[str] = None
        notes: Optional[str] = None
        tx_hash: Optional[str] = None

    @app.post("/api/transactions", status_code=201)
    async def add_transaction(body: TransactionBody):
        from datetime import datetime
        try:
            data = body.model_dump()
            # Parse date flexibly
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    data["date"] = datetime.strptime(data["date"], fmt)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"Cannot parse date: {data['date']}")
            txn = Transaction.from_dict({k: (str(v) if v is not None else "") for k, v in data.items()})
            _get_store().add(txn)
            _save_store()
            return {"ok": True, "transaction": txn.to_dict()}
        except Exception as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/transactions/{txn_id}")
    async def delete_transaction(txn_id: str):
        removed = _get_store().remove(txn_id)
        if not removed:
            raise HTTPException(404, "Transaction not found")
        _save_store()
        return {"ok": True}

    # ---------------------------------------------------------------- #
    # Import – Exchange CSV
    # ---------------------------------------------------------------- #

    async def _save_upload(file: UploadFile) -> Path:
        import tempfile
        suffix = Path(file.filename).suffix if file.filename else ".csv"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(await file.read())
            return Path(f.name)

    def _merge_import(txns: List[Transaction]) -> dict:
        store = _get_store()
        existing_hashes = {t.tx_hash for t in store.all() if t.tx_hash}
        new_count = 0
        dup_count = 0
        for t in txns:
            if t.tx_hash and t.tx_hash in existing_hashes:
                dup_count += 1
                continue
            store.add(t)
            if t.tx_hash:
                existing_hashes.add(t.tx_hash)
            new_count += 1
        _save_store()
        return {"imported": new_count, "duplicates_skipped": dup_count}

    @app.post("/api/import/csv")
    async def import_auto_csv(file: UploadFile = File(...)):
        path = await _save_upload(file)
        try:
            txns = WalletImporter().detect_and_import(path)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return _merge_import(txns)

    @app.post("/api/import/coinbase")
    async def import_coinbase(file: UploadFile = File(...)):
        path = await _save_upload(file)
        txns = WalletImporter().from_coinbase_csv(path)
        return _merge_import(txns)

    @app.post("/api/import/binance")
    async def import_binance(file: UploadFile = File(...)):
        path = await _save_upload(file)
        txns = WalletImporter().from_binance_csv(path)
        return _merge_import(txns)

    @app.post("/api/import/kraken")
    async def import_kraken(file: UploadFile = File(...)):
        path = await _save_upload(file)
        txns = WalletImporter().from_kraken_csv(path)
        return _merge_import(txns)

    @app.post("/api/import/crypto-com")
    async def import_crypto_com(file: UploadFile = File(...)):
        path = await _save_upload(file)
        txns = WalletImporter().from_crypto_com_csv(path)
        return _merge_import(txns)

    # ---------------------------------------------------------------- #
    # Import – Blockchain
    # ---------------------------------------------------------------- #

    class TronImportBody(BaseModel):
        address: str
        tokens: Optional[List[str]] = None
        include_trx: bool = True

    @app.post("/api/import/blockchain/tron")
    async def import_tron(body: TronImportBody):
        if not body.address.startswith("T") or len(body.address) < 30:
            raise HTTPException(400, "Invalid Tron address (must start with T, ~34 chars)")
        try:
            txns = BlockchainImporter().from_tron(
                body.address, tokens=body.tokens, include_trx=body.include_trx
            )
        except Exception as e:
            raise HTTPException(502, f"Tron API error: {e}")
        return _merge_import(txns)

    class EthImportBody(BaseModel):
        address: str
        tokens: Optional[List[str]] = None
        include_eth: bool = True
        etherscan_key: Optional[str] = None

    @app.post("/api/import/blockchain/eth")
    async def import_ethereum(body: EthImportBody):
        if not body.address.startswith("0x") or len(body.address) != 42:
            raise HTTPException(400, "Invalid Ethereum address (must be 0x + 40 hex chars)")
        try:
            txns = BlockchainImporter().from_ethereum(
                body.address,
                tokens=body.tokens,
                include_eth=body.include_eth,
                etherscan_key=body.etherscan_key,
            )
        except Exception as e:
            raise HTTPException(502, f"Ethereum API error: {e}")
        return _merge_import(txns)

    class BtcImportBody(BaseModel):
        address: str

    @app.post("/api/import/blockchain/btc")
    async def import_bitcoin(body: BtcImportBody):
        try:
            txns = BlockchainImporter().from_bitcoin(body.address)
        except Exception as e:
            raise HTTPException(502, f"Bitcoin API error: {e}")
        return _merge_import(txns)

    # ---------------------------------------------------------------- #
    # Reports
    # ---------------------------------------------------------------- #

    @app.get("/api/gains")
    async def get_gains(year: Optional[int] = None, method: Optional[str] = None):
        store = _get_store()
        cfg = _get_config()
        m = CostBasisMethod(method or cfg.cost_basis_method)
        engine = TaxEngine(store, m)
        records = engine.gains(year)
        summary = engine.summary(year)
        return {
            "gains": [r.to_dict() for r in records],
            "summary": {k: str(v) if isinstance(v, Decimal) else v for k, v in summary.items()},
        }

    @app.get("/api/income")
    async def get_income(year: Optional[int] = None):
        store = _get_store()
        from ..models.transaction import ACQUISITION_TYPES
        income_types = {TransactionType.MINING, TransactionType.INCOME, TransactionType.RECEIVE}
        txns = store.by_type(*income_types)
        if year:
            txns = [t for t in txns if t.date.year == year]
        total = sum(t.total_usd or Decimal("0") for t in txns)
        return {
            "income": [t.to_dict() for t in txns],
            "total_usd": str(total.quantize(Decimal("0.01"))),
        }

    @app.get("/api/summary")
    async def get_summary(year: Optional[int] = None):
        store = _get_store()
        cfg = _get_config()
        engine = TaxEngine(store, CostBasisMethod(cfg.cost_basis_method))
        gains_summary = engine.summary(year)
        store_summary = store.summary()
        return {
            "store": store_summary,
            "gains": {k: str(v) if isinstance(v, Decimal) else v for k, v in gains_summary.items()},
            "base_currency": cfg.base_currency,
        }

    return app


app = create_app()
