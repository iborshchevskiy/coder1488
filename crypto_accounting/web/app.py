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
POST /api/telegram/webhook              – Telegram bot webhook receiver
GET  /api/telegram/config               – get Telegram bot config (admin)
PUT  /api/telegram/config               – update Telegram bot config (admin)
POST /api/telegram/setwebhook           – register webhook URL with Telegram
GET  /api/telegram/users                – list registered Telegram users (admin)
DELETE /api/telegram/users/{chat_id}    – remove a user (admin)
GET  /api/telegram/subscriptions        – list all wallet subscriptions (admin)
POST /api/telegram/notify/test          – send a test notification (admin)
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
from ..telegram.bot import TelegramBot
from ..telegram.tg_store import TelegramStore, TelegramConfig
from ..telegram.handlers import BotHandlers
from ..telegram.notifications import NotificationDispatcher

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


def _get_tg_store() -> TelegramStore:
    return _state["tg_store"]


def _get_dispatcher() -> Optional[NotificationDispatcher]:
    return _state.get("dispatcher")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    storage = get_storage(_DATA_DIR)
    _state["storage"] = storage
    _state["config"] = storage.load_config()
    _state["store"] = storage.load_store()
    cache_dir = _DATA_DIR if isinstance(storage, FileStorage) else Path("/tmp/crypto_fx_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    _state["converter"] = FiatConverter(_get_config(), cache_dir)

    # Telegram
    tg_store = TelegramStore.auto(_DATA_DIR if isinstance(storage, FileStorage) else None)
    _state["tg_store"] = tg_store
    tg_cfg = tg_store.config
    if tg_cfg.token:
        bot = TelegramBot(tg_cfg.token)
        _state["bot"] = bot
        _state["dispatcher"] = NotificationDispatcher(bot, tg_store)
    else:
        _state["bot"] = None
        _state["dispatcher"] = None
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
        new_txns: List[Transaction] = []
        for t in txns:
            if t.tx_hash and t.tx_hash in existing_hashes:
                dup_count += 1
                continue
            store.add(t)
            if t.tx_hash:
                existing_hashes.add(t.tx_hash)
            new_txns.append(t)
            new_count += 1
        _save_store()
        # Fire Telegram notifications for new transactions
        dispatcher = _get_dispatcher()
        if dispatcher and new_txns:
            try:
                dispatcher.notify_transactions(new_txns)
                tg_cfg = _get_tg_store().config
                if tg_cfg.admin_chat_ids:
                    dispatcher.notify_import_summary(
                        tg_cfg.admin_chat_ids, new_txns, new_count, dup_count
                    )
            except Exception:
                log.exception("Telegram notification error")
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

    # ---------------------------------------------------------------- #
    # Custom Reports
    # ---------------------------------------------------------------- #

    @app.get("/api/reports/meta")
    async def reports_meta():
        """Return distinct wallets, assets and transaction types present in the store."""
        store = _get_store()
        all_txns = store.all()
        wallets = sorted({t.wallet for t in all_txns if t.wallet})
        assets = sorted({t.asset for t in all_txns if t.asset})
        types = sorted({t.type.value for t in all_txns})
        years = sorted({t.date.year for t in all_txns}, reverse=True)
        return {"wallets": wallets, "assets": assets, "types": types, "years": years}

    @app.get("/api/reports/custom")
    async def custom_report(
        # Filters
        wallets: Optional[str] = Query(None, description="Comma-separated wallet names"),
        assets: Optional[str] = Query(None, description="Comma-separated asset symbols"),
        types: Optional[str] = Query(None, description="Comma-separated transaction types"),
        date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
        date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
        # Options
        include_gains: bool = Query(False),
        group_by: Optional[str] = Query(None, description="asset|wallet|month|type"),
        base_currency: Optional[str] = Query(None),
        method: Optional[str] = Query(None),
    ):
        from datetime import date as date_cls
        store = _get_store()
        cfg = _get_config()
        converter: FiatConverter = _state["converter"]
        converter.ensure_loaded()
        base = (base_currency or cfg.base_currency).upper()
        if base not in SUPPORTED_FIAT:
            raise HTTPException(400, f"Unsupported currency: {base}")

        # Parse filter sets
        wallet_set = {w.strip() for w in wallets.split(",")} if wallets else None
        asset_set = {a.strip().upper() for a in assets.split(",")} if assets else None
        type_set: Optional[set] = None
        if types:
            try:
                type_set = {TransactionType(t.strip()) for t in types.split(",")}
            except ValueError as e:
                raise HTTPException(400, f"Invalid type: {e}")

        # Parse date range
        dt_from = dt_to = None
        try:
            if date_from:
                from datetime import datetime as _dt
                dt_from = _dt.strptime(date_from, "%Y-%m-%d")
            if date_to:
                from datetime import datetime as _dt
                dt_to = _dt.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except ValueError as e:
            raise HTTPException(400, f"Invalid date: {e}")

        # Apply filters
        txns = store.all()
        if wallet_set:
            txns = [t for t in txns if t.wallet in wallet_set]
        if asset_set:
            txns = [t for t in txns if t.asset.upper() in asset_set]
        if type_set:
            txns = [t for t in txns if t.type in type_set]
        if dt_from:
            txns = [t for t in txns if t.date >= dt_from]
        if dt_to:
            txns = [t for t in txns if t.date <= dt_to]

        # FX helper
        def to_base(usd_val: Optional[Decimal]) -> Optional[Decimal]:
            if usd_val is None:
                return None
            if base == "USD":
                return usd_val
            try:
                return usd_val * converter.get_rate("USD", base)
            except Exception:
                return usd_val

        # Build transaction rows
        INBOUND = {
            TransactionType.BUY, TransactionType.RECEIVE, TransactionType.TRANSFER_IN,
            TransactionType.MINING, TransactionType.INCOME, TransactionType.FIAT_DEPOSIT,
        }
        rows = []
        total_in = Decimal("0")
        total_out = Decimal("0")
        total_fees = Decimal("0")

        for t in txns:
            usd = t.total_usd or Decimal("0")
            base_val = to_base(usd) or Decimal("0")
            fee_base = to_base(t.fee_usd) or Decimal("0")
            is_in = t.type in INBOUND
            if is_in:
                total_in += base_val
            else:
                total_out += base_val
            total_fees += fee_base
            rows.append(t.to_dict())

        # Grouping
        grouped: Optional[dict] = None
        if group_by:
            from collections import defaultdict
            groups: dict = defaultdict(lambda: {"count": 0, "inflow": Decimal("0"), "outflow": Decimal("0"), "fees": Decimal("0")})

            def _key(t) -> str:
                if group_by == "asset":
                    return t.asset
                if group_by == "wallet":
                    return t.wallet or "(no wallet)"
                if group_by == "type":
                    return t.type.value
                if group_by == "month":
                    return t.date.strftime("%Y-%m")
                return "all"

            for t in txns:
                k = _key(t)
                g = groups[k]
                g["count"] += 1
                usd = t.total_usd or Decimal("0")
                bv = to_base(usd) or Decimal("0")
                if t.type in INBOUND:
                    g["inflow"] += bv
                else:
                    g["outflow"] += bv
                g["fees"] += to_base(t.fee_usd) or Decimal("0")

            grouped = {
                k: {
                    "count": v["count"],
                    "inflow": str(v["inflow"].quantize(Decimal("0.01"))),
                    "outflow": str(v["outflow"].quantize(Decimal("0.01"))),
                    "net": str((v["inflow"] - v["outflow"]).quantize(Decimal("0.01"))),
                    "fees": str(v["fees"].quantize(Decimal("0.01"))),
                }
                for k, v in sorted(groups.items())
            }

        # Capital gains (optional)
        gains_data: Optional[dict] = None
        if include_gains:
            cost_method = CostBasisMethod(method or cfg.cost_basis_method)
            engine = TaxEngine(store, cost_method)
            # Filter gains by date range / asset
            all_gains = engine.gains()
            filtered_gains = all_gains
            if dt_from:
                filtered_gains = [g for g in filtered_gains if g.disposal_date >= dt_from]
            if dt_to:
                filtered_gains = [g for g in filtered_gains if g.disposal_date <= dt_to]
            if asset_set:
                filtered_gains = [g for g in filtered_gains if g.asset.upper() in asset_set]

            total_gain = sum(g.gain_loss_usd for g in filtered_gains)
            st_gain = sum(g.gain_loss_usd for g in filtered_gains if not g.is_long_term)
            lt_gain = sum(g.gain_loss_usd for g in filtered_gains if g.is_long_term)
            gains_data = {
                "records": [g.to_dict() for g in filtered_gains],
                "summary": {
                    "total_gain_loss_usd": str(total_gain.quantize(Decimal("0.01"))),
                    "short_term_usd": str(st_gain.quantize(Decimal("0.01"))),
                    "long_term_usd": str(lt_gain.quantize(Decimal("0.01"))),
                    "count": len(filtered_gains),
                },
            }

        return {
            "filters": {
                "wallets": list(wallet_set) if wallet_set else None,
                "assets": list(asset_set) if asset_set else None,
                "types": [t.value for t in type_set] if type_set else None,
                "date_from": date_from,
                "date_to": date_to,
                "base_currency": base,
                "group_by": group_by,
            },
            "transactions": rows,
            "summary": {
                "count": len(rows),
                "total_inflow": str(total_in.quantize(Decimal("0.01"))),
                "total_outflow": str(total_out.quantize(Decimal("0.01"))),
                "net": str((total_in - total_out).quantize(Decimal("0.01"))),
                "total_fees": str(total_fees.quantize(Decimal("0.01"))),
                "base_currency": base,
            },
            "grouped": grouped,
            "gains": gains_data,
        }

    @app.get("/api/reports/export")
    async def export_report(
        format: str = Query("csv", description="csv or json"),
        wallets: Optional[str] = None,
        assets: Optional[str] = None,
        types: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        include_gains: bool = False,
        group_by: Optional[str] = None,
        base_currency: Optional[str] = None,
        method: Optional[str] = None,
    ):
        """Download report as CSV or JSON file."""
        import io
        import csv as csv_mod
        from fastapi.responses import StreamingResponse

        # Reuse custom_report logic by calling it directly with a fake scope
        # Build query string and forward to custom_report handler
        data = await custom_report(
            wallets=wallets, assets=assets, types=types,
            date_from=date_from, date_to=date_to,
            include_gains=include_gains, group_by=group_by,
            base_currency=base_currency, method=method,
        )

        filename_base = f"crypto_report_{date_from or 'all'}_{date_to or 'now'}"

        if format == "json":
            import json as json_mod
            content = json_mod.dumps(data, indent=2, default=str)
            return StreamingResponse(
                iter([content]),
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="{filename_base}.json"'},
            )

        # CSV export
        buf = io.StringIO()
        writer = csv_mod.writer(buf)

        # Summary header
        s = data["summary"]
        writer.writerow(["=== REPORT SUMMARY ==="])
        writer.writerow(["Transactions", s["count"]])
        writer.writerow(["Total Inflow", s["total_inflow"], s["base_currency"]])
        writer.writerow(["Total Outflow", s["total_outflow"], s["base_currency"]])
        writer.writerow(["Net", s["net"], s["base_currency"]])
        writer.writerow(["Fees", s["total_fees"], s["base_currency"]])
        writer.writerow([])

        # Grouped summary if present
        if data.get("grouped"):
            writer.writerow(["=== GROUPED BY", (data["filters"].get("group_by") or "").upper(), "==="])
            writer.writerow(["Group", "Count", "Inflow", "Outflow", "Net", "Fees"])
            for grp, vals in data["grouped"].items():
                writer.writerow([grp, vals["count"], vals["inflow"], vals["outflow"], vals["net"], vals["fees"]])
            writer.writerow([])

        # Gains if present
        if data.get("gains"):
            gs = data["gains"]["summary"]
            writer.writerow(["=== CAPITAL GAINS ==="])
            writer.writerow(["Total Gain/Loss USD", gs["total_gain_loss_usd"]])
            writer.writerow(["Short-Term", gs["short_term_usd"]])
            writer.writerow(["Long-Term", gs["long_term_usd"]])
            writer.writerow([])
            if data["gains"]["records"]:
                g_fields = list(data["gains"]["records"][0].keys())
                writer.writerow(g_fields)
                for g in data["gains"]["records"]:
                    writer.writerow([g.get(f, "") for f in g_fields])
                writer.writerow([])

        # Transactions
        writer.writerow(["=== TRANSACTIONS ==="])
        if data["transactions"]:
            fields = list(data["transactions"][0].keys())
            writer.writerow(fields)
            for t in data["transactions"]:
                writer.writerow([t.get(f, "") for f in fields])

        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.csv"'},
        )

    # ---------------------------------------------------------------- #
    # Telegram – Webhook receiver
    # ---------------------------------------------------------------- #

    class _WebhookSecret:
        """Header dependency for Telegram webhook secret validation."""
        pass

    from fastapi import Request, Header

    @app.post("/api/telegram/webhook", include_in_schema=False)
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: Optional[str] = Header(None),
    ):
        tg_store = _get_tg_store()
        cfg = tg_store.config
        # Validate secret token if configured
        if cfg.webhook_secret and x_telegram_bot_api_secret_token != cfg.webhook_secret:
            raise HTTPException(403, "Invalid secret token")
        bot = _state.get("bot")
        if not bot:
            raise HTTPException(503, "Telegram bot not configured")
        try:
            update = await request.json()
            handlers = BotHandlers(bot, tg_store)
            handlers.handle_update(update)
        except Exception:
            log.exception("Webhook handler error")
        return {"ok": True}

    # ---------------------------------------------------------------- #
    # Telegram – Admin config API
    # ---------------------------------------------------------------- #

    class TelegramConfigBody(BaseModel):
        token: Optional[str] = None
        admin_chat_ids: Optional[List[int]] = None
        notifications_enabled: Optional[bool] = None
        webhook_secret: Optional[str] = None

    @app.get("/api/telegram/config")
    async def get_telegram_config():
        cfg = _get_tg_store().config
        d = cfg.to_dict()
        # Mask the token — only expose whether it's set
        d["token_set"] = bool(d.get("token"))
        d["token"] = "***" if d.get("token") else ""
        bot = _state.get("bot")
        d["bot_connected"] = False
        if bot:
            info = bot.get_me()
            d["bot_connected"] = info.get("ok", False)
            if info.get("ok"):
                d["bot_username"] = info["result"].get("username", "")
        return d

    @app.put("/api/telegram/config")
    async def update_telegram_config(body: TelegramConfigBody):
        tg_store = _get_tg_store()
        cfg = tg_store.config
        if body.token is not None and body.token not in ("", "***"):
            cfg.token = body.token
        if body.admin_chat_ids is not None:
            cfg.admin_chat_ids = body.admin_chat_ids
        if body.notifications_enabled is not None:
            cfg.notifications_enabled = body.notifications_enabled
        if body.webhook_secret is not None:
            cfg.webhook_secret = body.webhook_secret
        tg_store.save_config(cfg)
        # Re-initialise bot with new token
        if cfg.token:
            bot = TelegramBot(cfg.token)
            _state["bot"] = bot
            _state["dispatcher"] = NotificationDispatcher(bot, tg_store)
        return {"ok": True}

    class SetWebhookBody(BaseModel):
        url: str

    @app.post("/api/telegram/setwebhook")
    async def set_telegram_webhook(body: SetWebhookBody):
        bot = _state.get("bot")
        if not bot:
            raise HTTPException(503, "Telegram bot not configured — set token first")
        tg_store = _get_tg_store()
        cfg = tg_store.config
        result = bot.set_webhook(body.url, secret_token=cfg.webhook_secret or None)
        if result.get("ok"):
            cfg.webhook_url = body.url
            tg_store.save_config(cfg)
            return {"ok": True, "webhook_url": body.url}
        raise HTTPException(502, f"Telegram error: {result.get('description')}")

    # ---------------------------------------------------------------- #
    # Telegram – Users admin API
    # ---------------------------------------------------------------- #

    @app.get("/api/telegram/users")
    async def list_telegram_users():
        users = list(_get_tg_store().users.values())
        return {
            "total": len(users),
            "users": [u.to_dict() for u in users],
        }

    @app.delete("/api/telegram/users/{chat_id}")
    async def delete_telegram_user(chat_id: int):
        tg_store = _get_tg_store()
        if tg_store.get_user(chat_id) is None:
            raise HTTPException(404, "User not found")
        tg_store.delete_user(chat_id)
        return {"ok": True}

    @app.get("/api/telegram/subscriptions")
    async def list_telegram_subscriptions():
        subs = _get_tg_store().subscriptions
        return {
            "total_wallets": len(subs),
            "subscriptions": {addr: ids for addr, ids in subs.items()},
        }

    class TestNotifyBody(BaseModel):
        chat_id: int
        message: str = "🧪 Test notification from Crypto Accounting System"

    @app.post("/api/telegram/notify/test")
    async def send_test_notification(body: TestNotifyBody):
        bot = _state.get("bot")
        if not bot:
            raise HTTPException(503, "Telegram bot not configured")
        result = bot.send_message(body.chat_id, body.message)
        if result.get("ok"):
            return {"ok": True}
        raise HTTPException(502, f"Telegram error: {result.get('description')}")

    return app


app = create_app()
