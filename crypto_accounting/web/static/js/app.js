/**
 * Crypto Accounting System – Single-Page Application
 * Vanilla JS, no framework dependencies.
 */

"use strict";

// ============================================================
// API helpers
// ============================================================

const api = {
  async get(path) {
    const r = await fetch(`/api${path}`);
    if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || r.statusText); }
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(`/api${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || r.statusText); }
    return r.json();
  },
  async put(path, body) {
    const r = await fetch(`/api${path}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || r.statusText); }
    return r.json();
  },
  async del(path) {
    const r = await fetch(`/api${path}`, { method: "DELETE" });
    if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || r.statusText); }
    return r.json();
  },
  async uploadFile(path, file) {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch(`/api${path}`, { method: "POST", body: fd });
    if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || r.statusText); }
    return r.json();
  },
};

// ============================================================
// Toast notifications
// ============================================================

function toast(msg, type = "success", duration = 4000) {
  const container = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), duration);
}

// ============================================================
// State
// ============================================================

const state = {
  config: null,
  transactions: [],
  portfolio: null,
  gains: null,
  income: null,
  fxRates: null,
  currentPage: "dashboard",
};

// ============================================================
// Routing / Navigation
// ============================================================

function navigate(page) {
  document.querySelectorAll(".nav-item").forEach(el => el.classList.toggle("active", el.dataset.page === page));
  document.querySelectorAll(".page").forEach(el => el.classList.toggle("active", el.id === `page-${page}`));
  document.getElementById("breadcrumb").textContent = pageTitles[page] || page;
  state.currentPage = page;
  pageLoaders[page]?.();
}

const pageTitles = {
  dashboard:        "Dashboard",
  portfolio:        "Portfolio",
  transactions:     "Transactions",
  gains:            "Capital Gains",
  income:           "Income",
  import:           "Import",
  fiat:             "Fiat Accounts",
  exchange:         "Exchange Rates",
  settings:         "Settings",
  telegram:         "Telegram Bot",
  "report-builder": "Custom Report",
};

const pageLoaders = {
  dashboard:        loadDashboard,
  portfolio:        loadPortfolio,
  transactions:     loadTransactions,
  gains:            loadGains,
  income:           loadIncome,
  fiat:             loadFiatAccounts,
  exchange:         loadExchangeRates,
  settings:         loadSettings,
  telegram:         loadTelegramPage,
  "report-builder": loadReportBuilder,
};

// ============================================================
// Formatting helpers
// ============================================================

const fmt = {
  usd(n, decimals = 2) {
    if (n == null || isNaN(+n)) return "—";
    const abs = Math.abs(+n);
    const sign = +n < 0 ? "-" : "";
    const sym = state.config?.currency_symbol || "$";
    return `${sign}${sym}${abs.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;
  },
  qty(n, decimals = 8) {
    if (n == null || isNaN(+n)) return "—";
    return (+n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: decimals });
  },
  pct(n) {
    if (n == null || isNaN(+n)) return "—";
    const sign = +n >= 0 ? "+" : "";
    return `${sign}${(+n).toFixed(2)}%`;
  },
  date(s) {
    if (!s) return "—";
    return new Date(s).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
  },
  pnlClass(n) {
    if (n == null || isNaN(+n)) return "";
    return +n >= 0 ? "pnl-positive" : "pnl-negative";
  },
};

function badgeHtml(type) {
  const cls = `badge badge-${type.replace(/_/g, "-")}`;
  return `<span class="${cls}">${type.replace(/_/g, " ")}</span>`;
}

// ============================================================
// Dashboard
// ============================================================

async function loadDashboard() {
  try {
    const [portfolio, summary, fx, fiatData] = await Promise.all([
      api.get("/portfolio"),
      api.get("/summary"),
      api.get("/fx/rates").catch(() => null),
      api.get("/fiat-accounts").catch(() => null),
    ]);
    state.portfolio = portfolio;
    state.fxRates = fx;

    if (fiatData) {
      const sym = fiatData.base_symbol || fiatData.base_currency || "$";
      const bal = +fiatData.total_balance_base || 0;
      document.getElementById("kpi-fiat-balance").textContent = fmt.usd(bal);
      document.getElementById("kpi-fiat-sub").textContent =
        `${(fiatData.accounts || []).length} currencies in base (${fiatData.base_currency})`;
    }

    const holdings = portfolio.holdings || [];
    const gains = summary.gains || {};
    const store = summary.store || {};

    const totalBasis = +portfolio.summary.total_cost_basis_usd || 0;
    const totalMV = portfolio.summary.total_market_value_usd != null
      ? +portfolio.summary.total_market_value_usd : null;
    const totalPnl = totalMV != null ? totalMV - totalBasis : null;

    document.getElementById("kpi-basis").textContent      = fmt.usd(totalBasis);
    document.getElementById("kpi-mv").textContent         = fmt.usd(totalMV);
    document.getElementById("kpi-pnl").textContent        = fmt.usd(totalPnl);
    document.getElementById("kpi-pnl").className          = `kpi-value ${fmt.pnlClass(totalPnl)}`;
    document.getElementById("kpi-gain-loss").textContent  = fmt.usd(gains.total_gain_loss_usd);
    document.getElementById("kpi-txns").textContent       = store.total_transactions ?? "—";
    document.getElementById("kpi-assets").textContent     = (store.assets || []).length;
    document.getElementById("kpi-gain-loss").className    = `kpi-value ${fmt.pnlClass(gains.total_gain_loss_usd)}`;

    renderAllocationChart(holdings);
    renderTopHoldings(holdings);

  } catch (e) {
    toast("Dashboard load failed: " + e.message, "error");
  }
}

function renderAllocationChart(holdings) {
  const ctx = document.getElementById("allocation-chart");
  if (!ctx) return;

  // Destroy previous chart instance
  if (window._allocationChart) { window._allocationChart.destroy(); }

  const labels = holdings.map(h => h.asset);
  const data   = holdings.map(h => +(h.market_value_usd || h.total_cost_basis_usd) || 0);
  const colors = ["#2563eb","#16a34a","#dc2626","#ca8a04","#7c3aed","#0891b2","#d97706","#9333ea"];

  window._allocationChart = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels,
      datasets: [{ data, backgroundColor: colors.slice(0, labels.length), borderWidth: 2, borderColor: "#fff" }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "right", labels: { boxWidth: 12, font: { size: 12 } } },
        tooltip: {
          callbacks: {
            label: ctx => ` ${ctx.label}: ${fmt.usd(ctx.parsed)}`,
          },
        },
      },
    },
  });
}

function renderTopHoldings(holdings) {
  const tbody = document.getElementById("top-holdings-body");
  if (!tbody) return;
  if (!holdings.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No holdings yet</td></tr>`;
    return;
  }
  tbody.innerHTML = holdings.slice(0, 8).map(h => {
    const pnlUsd = h.unrealised_pnl_usd != null ? fmt.usd(h.unrealised_pnl_usd) : "—";
    const pnlPct = h.unrealised_pnl_pct != null ? fmt.pct(h.unrealised_pnl_pct) : "";
    const pnlClass = fmt.pnlClass(h.unrealised_pnl_usd);
    return `
      <tr>
        <td><strong>${h.asset}</strong></td>
        <td class="text-right text-mono">${fmt.qty(h.quantity)}</td>
        <td class="text-right">${fmt.usd(h.average_cost_usd)}</td>
        <td class="text-right">${h.market_value_usd != null ? fmt.usd(h.market_value_usd) : "—"}</td>
        <td class="text-right ${pnlClass}">${pnlUsd} ${pnlPct ? `<small>(${pnlPct})</small>` : ""}</td>
      </tr>`;
  }).join("");
}

// ============================================================
// Portfolio
// ============================================================

async function loadPortfolio() {
  const tbody = document.getElementById("portfolio-body");
  tbody.innerHTML = `<tr><td colspan="7"><span class="spinner"></span></td></tr>`;
  try {
    const data = await api.get("/portfolio");
    state.portfolio = data;
    const holdings = data.holdings || [];
    if (!holdings.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No holdings. Import transactions to get started.</td></tr>`;
      return;
    }
    tbody.innerHTML = holdings.map(h => {
      const pnlClass = fmt.pnlClass(h.unrealised_pnl_usd);
      return `
        <tr>
          <td><strong>${h.asset}</strong></td>
          <td class="text-right text-mono">${fmt.qty(h.quantity)}</td>
          <td class="text-right">${fmt.usd(h.average_cost_usd)}</td>
          <td class="text-right">${fmt.usd(h.total_cost_basis_usd)}</td>
          <td class="text-right">${h.market_value_usd != null ? fmt.usd(h.market_value_usd) : "—"}</td>
          <td class="text-right ${pnlClass}">${h.unrealised_pnl_usd != null ? fmt.usd(h.unrealised_pnl_usd) : "—"}</td>
          <td class="text-right ${pnlClass}">${h.unrealised_pnl_pct != null ? fmt.pct(h.unrealised_pnl_pct) : "—"}</td>
        </tr>`;
    }).join("");

    // Totals row
    const s = data.summary;
    const pnlTotal = s.total_market_value_usd && s.total_cost_basis_usd
      ? +s.total_market_value_usd - +s.total_cost_basis_usd : null;
    const pnlClass = fmt.pnlClass(pnlTotal);
    tbody.innerHTML += `
      <tr style="font-weight:600; background:var(--clr-surface-2)">
        <td>Total</td>
        <td></td><td></td>
        <td class="text-right">${fmt.usd(s.total_cost_basis_usd)}</td>
        <td class="text-right">${fmt.usd(s.total_market_value_usd)}</td>
        <td class="text-right ${pnlClass}">${fmt.usd(pnlTotal)}</td>
        <td></td>
      </tr>`;
  } catch (e) {
    toast("Portfolio load failed: " + e.message, "error");
  }
}

// ============================================================
// Transactions
// ============================================================

let txnOffset = 0;
const TX_PAGE_SIZE = 100;

async function loadTransactions(reset = true) {
  if (reset) txnOffset = 0;
  const tbody = document.getElementById("tx-body");
  tbody.innerHTML = `<tr><td colspan="8"><span class="spinner"></span></td></tr>`;

  const assetF  = document.getElementById("tx-filter-asset")?.value || "";
  const typeF   = document.getElementById("tx-filter-type")?.value  || "";
  const walletF = document.getElementById("tx-filter-wallet")?.value || "";
  const yearF   = document.getElementById("tx-filter-year")?.value  || "";

  let qs = `?limit=${TX_PAGE_SIZE}&offset=${txnOffset}`;
  if (assetF)  qs += `&asset=${encodeURIComponent(assetF)}`;
  if (typeF)   qs += `&type=${encodeURIComponent(typeF)}`;
  if (walletF) qs += `&wallet=${encodeURIComponent(walletF)}`;
  if (yearF)   qs += `&year=${encodeURIComponent(yearF)}`;

  try {
    const data = await api.get(`/transactions${qs}`);
    state.transactions = data.transactions;
    const total = data.total;
    document.getElementById("tx-count").textContent = `${total} transaction${total !== 1 ? "s" : ""}`;

    if (!data.transactions.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="empty-state">No transactions match your filters.</td></tr>`;
      return;
    }

    tbody.innerHTML = data.transactions.map(t => `
      <tr>
        <td>${fmt.date(t.date)}</td>
        <td>${badgeHtml(t.type)}</td>
        <td><strong>${t.asset}</strong></td>
        <td class="text-right text-mono">${fmt.qty(t.quantity)}</td>
        <td class="text-right">${t.total_usd ? fmt.usd(t.total_usd) : "—"}</td>
        <td class="text-right">${t.fee_usd ? fmt.usd(t.fee_usd) : "—"}</td>
        <td>${t.wallet || "—"}</td>
        <td>
          <button class="btn btn-ghost btn-sm" onclick="deleteTxn('${t.id}')" title="Delete">✕</button>
        </td>
      </tr>`).join("");

    // Pagination controls
    document.getElementById("tx-prev").disabled = txnOffset === 0;
    document.getElementById("tx-next").disabled = txnOffset + TX_PAGE_SIZE >= total;
    document.getElementById("tx-page-info").textContent =
      `${txnOffset + 1}–${Math.min(txnOffset + TX_PAGE_SIZE, total)} of ${total}`;
  } catch (e) {
    toast("Transactions load failed: " + e.message, "error");
  }
}

async function deleteTxn(id) {
  if (!confirm("Delete this transaction?")) return;
  try {
    await api.del(`/transactions/${id}`);
    toast("Transaction deleted");
    loadTransactions();
  } catch (e) {
    toast("Delete failed: " + e.message, "error");
  }
}

// ============================================================
// Add Transaction Modal
// ============================================================

function openAddTxnModal() {
  document.getElementById("modal-add-txn").classList.remove("hidden");
}

function closeAddTxnModal() {
  document.getElementById("modal-add-txn").classList.add("hidden");
  document.getElementById("form-add-txn").reset();
}

async function submitAddTxn(e) {
  e.preventDefault();
  const form = e.target;
  const data = Object.fromEntries(new FormData(form).entries());
  // Remove empty strings
  Object.keys(data).forEach(k => { if (data[k] === "") delete data[k]; });
  try {
    await api.post("/transactions", data);
    toast("Transaction added");
    closeAddTxnModal();
    loadTransactions();
  } catch (err) {
    toast("Error: " + err.message, "error");
  }
}

// ============================================================
// Capital Gains
// ============================================================

async function loadGains() {
  const year = document.getElementById("gains-year")?.value || "";
  const method = document.getElementById("gains-method")?.value || "";
  let qs = "?";
  if (year)   qs += `year=${year}&`;
  if (method) qs += `method=${method}`;

  const tbody = document.getElementById("gains-body");
  tbody.innerHTML = `<tr><td colspan="8"><span class="spinner"></span></td></tr>`;
  try {
    const data = await api.get(`/gains${qs}`);
    state.gains = data;
    const { gains, summary } = data;

    // KPI row
    document.getElementById("gains-total").textContent    = fmt.usd(summary.total_gain_loss_usd);
    document.getElementById("gains-lt").textContent       = fmt.usd(summary.long_term_gain_loss_usd);
    document.getElementById("gains-st").textContent       = fmt.usd(summary.short_term_gain_loss_usd);
    document.getElementById("gains-total").className      = `kpi-value ${fmt.pnlClass(summary.total_gain_loss_usd)}`;
    document.getElementById("gains-lt").className         = `kpi-value ${fmt.pnlClass(summary.long_term_gain_loss_usd)}`;
    document.getElementById("gains-st").className         = `kpi-value ${fmt.pnlClass(summary.short_term_gain_loss_usd)}`;

    if (!gains.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="empty-state">No disposals in selected period.</td></tr>`;
      return;
    }

    tbody.innerHTML = gains.map(r => {
      const pnlClass = fmt.pnlClass(r.gain_loss_usd);
      const termBadge = r.term === "long-term"
        ? `<span class="badge badge-receive">LT</span>`
        : `<span class="badge badge-send">ST</span>`;
      return `
        <tr>
          <td>${fmt.date(r.disposal_date)}</td>
          <td><strong>${r.asset}</strong></td>
          <td class="text-right text-mono">${fmt.qty(r.quantity)}</td>
          <td class="text-right">${fmt.usd(r.proceeds_usd)}</td>
          <td class="text-right">${fmt.usd(r.cost_basis_usd)}</td>
          <td class="text-right">${fmt.usd(r.fee_usd)}</td>
          <td class="text-right ${pnlClass}">${fmt.usd(r.gain_loss_usd)}</td>
          <td>${termBadge}</td>
        </tr>`;
    }).join("");
  } catch (e) {
    toast("Gains load failed: " + e.message, "error");
  }
}

// ============================================================
// Income
// ============================================================

async function loadIncome() {
  const year = document.getElementById("income-year")?.value || "";
  const tbody = document.getElementById("income-body");
  tbody.innerHTML = `<tr><td colspan="5"><span class="spinner"></span></td></tr>`;
  try {
    const data = await api.get(`/income${year ? "?year=" + year : ""}`);
    state.income = data;
    document.getElementById("income-total").textContent = fmt.usd(data.total_usd);
    const items = data.income || [];
    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No income transactions found.</td></tr>`;
      return;
    }
    tbody.innerHTML = items.map(t => `
      <tr>
        <td>${fmt.date(t.date)}</td>
        <td>${badgeHtml(t.type)}</td>
        <td><strong>${t.asset}</strong></td>
        <td class="text-right text-mono">${fmt.qty(t.quantity)}</td>
        <td class="text-right">${t.total_usd ? fmt.usd(t.total_usd) : "—"}</td>
      </tr>`).join("");
  } catch (e) {
    toast("Income load failed: " + e.message, "error");
  }
}

// ============================================================
// Exchange Rates
// ============================================================

async function loadExchangeRates() {
  const container = document.getElementById("fx-grid");
  container.innerHTML = `<span class="spinner"></span>`;
  try {
    const data = await api.get("/fx/rates");
    state.fxRates = data;
    document.getElementById("fx-base").textContent = data.base;
    document.getElementById("fx-updated").textContent = data.last_updated || "—";

    const rates = data.rates || {};
    const sorted = Object.entries(rates).sort((a, b) => a[0].localeCompare(b[0]));
    container.innerHTML = sorted.map(([code, rate]) => `
      <div class="fx-item">
        <span class="fx-pair">${data.base} / ${code}</span>
        <span class="fx-rate">${(+rate).toFixed(6)}</span>
      </div>`).join("");
  } catch (e) {
    toast("FX rates load failed: " + e.message, "error");
    container.innerHTML = `<p class="empty-state">Could not load rates. Using offline fallback.</p>`;
  }
}

async function saveManualRate(e) {
  e.preventDefault();
  const from = document.getElementById("manual-from").value.toUpperCase();
  const to   = document.getElementById("manual-to").value.toUpperCase();
  const rate = +document.getElementById("manual-rate").value;
  if (!from || !to || !rate) { toast("Fill all fields", "warning"); return; }
  try {
    await api.post("/fx/rates/manual", { from_currency: from, to_currency: to, rate });
    toast(`Rate ${from}/${to} = ${rate} saved`);
    loadExchangeRates();
  } catch (e) {
    toast("Error: " + e.message, "error");
  }
}

// ============================================================
// Import
// ============================================================

function setupImportTabs() {
  document.querySelectorAll("#page-import .tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#page-import .tab-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll("#page-import .tab-panel").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(btn.dataset.tab).classList.add("active");
    });
  });
}

function setupUploadZone(zoneId, inputId) {
  const zone  = document.getElementById(zoneId);
  const input = document.getElementById(inputId);
  if (!zone || !input) return;

  zone.addEventListener("click", () => input.click());
  zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("dragover"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
  zone.addEventListener("drop", e => {
    e.preventDefault();
    zone.classList.remove("dragover");
    if (e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      zone.querySelector(".upload-filename").textContent = e.dataTransfer.files[0].name;
    }
  });
  input.addEventListener("change", () => {
    if (input.files.length) zone.querySelector(".upload-filename").textContent = input.files[0].name;
  });
}

async function submitImport(endpoint, fileInputId) {
  const input = document.getElementById(fileInputId);
  if (!input.files.length) { toast("Select a file first", "warning"); return; }
  const btn = document.querySelector(`[data-import="${fileInputId}"]`);
  if (btn) { btn.disabled = true; btn.textContent = "Importing…"; }
  try {
    const result = await api.uploadFile(endpoint, input.files[0]);
    toast(`Imported ${result.imported} transactions (${result.duplicates_skipped} duplicates skipped)`, "success");
    input.value = "";
  } catch (e) {
    toast("Import failed: " + e.message, "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Import"; }
  }
}

async function submitBlockchainImport(chain) {
  const addressInput = document.getElementById(`bc-${chain}-address`);
  const address = addressInput?.value.trim();
  if (!address) { toast("Enter an address", "warning"); return; }

  const body = { address };
  if (chain === "tron") {
    const tokens = document.getElementById("bc-tron-tokens")?.value;
    body.tokens = tokens ? tokens.split(",").map(t => t.trim().toUpperCase()) : null;
    body.include_trx = document.getElementById("bc-tron-trx")?.checked ?? true;
  }
  if (chain === "eth") {
    const tokens = document.getElementById("bc-eth-tokens")?.value;
    body.tokens = tokens ? tokens.split(",").map(t => t.trim().toUpperCase()) : null;
    body.etherscan_key = document.getElementById("bc-eth-key")?.value.trim() || null;
  }

  const btn = document.getElementById(`bc-${chain}-btn`);
  if (btn) { btn.disabled = true; btn.textContent = "Fetching…"; }
  try {
    const result = await api.post(`/import/blockchain/${chain}`, body);
    toast(`Imported ${result.imported} transactions (${result.duplicates_skipped} skipped)`, "success");
    addressInput.value = "";
  } catch (e) {
    toast("Import failed: " + e.message, "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Fetch & Import"; }
  }
}

// ============================================================
// Settings
// ============================================================

async function loadSettings() {
  try {
    const cfg = await api.get("/config");
    state.config = cfg;
    document.getElementById("cfg-base-currency").value     = cfg.base_currency || "USD";
    document.getElementById("cfg-method").value            = cfg.cost_basis_method || "fifo";
    document.getElementById("cfg-tax-month").value         = cfg.tax_year_start_month || 1;
    document.getElementById("cfg-fees-in-basis").checked   = cfg.include_fees_in_basis !== false;
    document.getElementById("cfg-rate-provider").value     = cfg.rate_provider || "ecb";
    document.getElementById("cfg-rate-api-key").value      = cfg.rate_api_key || "";
    document.getElementById("topbar-currency").textContent = cfg.base_currency || "USD";

    // Populate currency select
    const sel = document.getElementById("cfg-base-currency");
    sel.innerHTML = "";
    Object.entries(cfg.supported_fiat || {}).forEach(([code, name]) => {
      const opt = document.createElement("option");
      opt.value = code;
      opt.textContent = `${code} – ${name}`;
      if (code === cfg.base_currency) opt.selected = true;
      sel.appendChild(opt);
    });
  } catch (e) {
    toast("Settings load failed: " + e.message, "error");
  }
}

async function saveSettings(e) {
  e.preventDefault();
  const body = {
    base_currency:        document.getElementById("cfg-base-currency").value,
    cost_basis_method:    document.getElementById("cfg-method").value,
    tax_year_start_month: +document.getElementById("cfg-tax-month").value,
    include_fees_in_basis:document.getElementById("cfg-fees-in-basis").checked,
    rate_provider:        document.getElementById("cfg-rate-provider").value,
    rate_api_key:         document.getElementById("cfg-rate-api-key").value || null,
  };
  try {
    const result = await api.put("/config", body);
    state.config = result.config;
    toast("Settings saved");
    document.getElementById("topbar-currency").textContent = body.base_currency;
  } catch (e) {
    toast("Save failed: " + e.message, "error");
  }
}

// ============================================================
// Fiat Accounts
// ============================================================

async function loadFiatAccounts() {
  try {
    const data = await api.get("/fiat-accounts");
    const accounts = data.accounts || [];

    // Render KPI summary cards
    const grid = document.getElementById("fiat-accounts-grid");
    if (!accounts.length) {
      grid.innerHTML = `<div class="kpi-card"><div class="kpi-label">No fiat accounts</div>
        <div class="kpi-value" style="font-size:1rem;color:var(--clr-text-muted)">
          Record buy/sell/deposit transactions with a fiat currency to see balances.
        </div></div>`;
    } else {
      grid.innerHTML = accounts.map(acc => {
        const bal = +acc.balance;
        const cls = bal >= 0 ? "" : "red";
        const sym = acc.symbol || acc.currency;
        return `
          <div class="kpi-card ${cls}" style="cursor:pointer" onclick="selectFiatCurrency('${acc.currency}')">
            <div class="kpi-label">${acc.currency}</div>
            <div class="kpi-value" style="font-size:1.4rem">${sym}${Math.abs(bal).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2})}</div>
            <div class="kpi-sub">${acc.num_buys} buys · ${acc.num_sells} sells</div>
          </div>`;
      }).join("") + `
        <div class="kpi-card blue">
          <div class="kpi-label">Total (${data.base_currency})</div>
          <div class="kpi-value" style="font-size:1.4rem">${fmt.usd(data.total_balance_base)}</div>
          <div class="kpi-sub">converted to base currency</div>
        </div>`;
    }

    // Populate currency selector
    const sel = document.getElementById("fiat-currency-select");
    sel.innerHTML = `<option value="">Select currency…</option>`;
    accounts.forEach(acc => {
      const opt = document.createElement("option");
      opt.value = acc.currency;
      opt.textContent = `${acc.currency} (bal: ${acc.symbol || acc.currency}${acc.balance})`;
      sel.appendChild(opt);
    });
  } catch (e) {
    toast("Fiat accounts load failed: " + e.message, "error");
  }
}

function selectFiatCurrency(currency) {
  document.getElementById("fiat-currency-select").value = currency;
  loadFiatLedger();
}

async function loadFiatLedger() {
  const currency = document.getElementById("fiat-currency-select").value;
  const tbody = document.getElementById("fiat-ledger-body");
  const statsEl = document.getElementById("fiat-detail-stats");

  if (!currency) {
    tbody.innerHTML = `<tr><td colspan="9" class="empty-state">Select a currency above.</td></tr>`;
    statsEl.style.display = "none";
    return;
  }

  tbody.innerHTML = `<tr><td colspan="9"><span class="spinner"></span></td></tr>`;

  try {
    const data = await api.get(`/fiat-accounts/${currency}`);
    const acc = data.account;
    const sym = data.symbol || currency;

    // Stats
    statsEl.style.display = "block";
    const bal = +acc.balance;
    document.getElementById("fiat-stat-balance").textContent =
      `${sym}${Math.abs(bal).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2})}`;
    document.getElementById("fiat-stat-balance").className =
      bal >= 0 ? "pnl-positive" : "pnl-negative";
    document.getElementById("fiat-stat-deposited").textContent  = `${sym}${fmtFiat(acc.total_deposited)}`;
    document.getElementById("fiat-stat-withdrawn").textContent  = `${sym}${fmtFiat(acc.total_withdrawn)}`;
    document.getElementById("fiat-stat-spent").textContent      = `${sym}${fmtFiat(acc.total_spent_on_buys)}`;
    document.getElementById("fiat-stat-received").textContent   = `${sym}${fmtFiat(acc.total_received_from_sells)}`;
    const pnl = +acc.realised_fiat_pnl;
    document.getElementById("fiat-stat-pnl").textContent =
      `${pnl >= 0 ? "+" : ""}${sym}${fmtFiat(acc.realised_fiat_pnl)}`;
    document.getElementById("fiat-stat-pnl").className =
      `kpi-value ${pnl >= 0 ? "pnl-positive" : "pnl-negative"}`;

    // Ledger
    const entries = data.ledger || [];
    if (!entries.length) {
      tbody.innerHTML = `<tr><td colspan="9" class="empty-state">No entries for ${currency}.</td></tr>`;
      return;
    }

    tbody.innerHTML = [...entries].reverse().map(e => {
      const amt = +e.amount;
      const cls = amt >= 0 ? "fiat-inflow" : "fiat-outflow";
      const sign = amt >= 0 ? "+" : "";
      const amtUsd = e.amount_usd ? fmt.usd(e.amount_usd) : "—";
      const qty = +e.crypto_quantity;
      const qtyStr = qty !== 0 ? fmt.qty(qty) : "—";
      return `
        <tr>
          <td>${fmt.date(e.date)}</td>
          <td>${badgeHtml(e.type)}</td>
          <td>${e.asset !== "FIAT" ? `<strong>${e.asset}</strong>` : "—"}</td>
          <td class="text-right text-mono">${qtyStr}</td>
          <td class="text-right text-mono ${cls}">${sign}${sym}${fmtFiat(e.amount)}</td>
          <td class="text-right">${amtUsd}</td>
          <td class="text-right text-mono">${sym}${fmtFiat(e.running_balance)}</td>
          <td>${e.wallet || "—"}</td>
          <td style="color:var(--clr-text-muted);font-size:.82rem">${e.notes || ""}</td>
        </tr>`;
    }).join("");
  } catch (e) {
    toast("Fiat ledger load failed: " + e.message, "error");
    tbody.innerHTML = `<tr><td colspan="9" class="empty-state">Failed to load.</td></tr>`;
  }
}

function fmtFiat(v) {
  const n = +v;
  if (isNaN(n)) return "—";
  return Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// ============================================================
// Transaction modal – fiat field visibility
// ============================================================

const FIAT_TYPES = new Set(["buy", "sell", "fiat_deposit", "fiat_withdrawal"]);

function onTxnTypeChange(type) {
  const section = document.getElementById("fiat-fields");
  const hint = document.getElementById("txn-fiat-amount-hint");
  const assetField = document.getElementById("txn-asset").closest(".field");
  const qtyField   = document.getElementById("txn-quantity").closest(".field");

  if (FIAT_TYPES.has(type)) {
    section.style.display = "contents";
    if (hint) {
      hint.textContent = type === "buy"
        ? "(fiat spent on this purchase)"
        : type === "sell"
        ? "(fiat received from this sale)"
        : "(amount moved)";
    }
  } else {
    section.style.display = "none";
  }

  // For pure fiat moves: asset is "FIAT", qty is 0 — pre-fill and hide
  if (type === "fiat_deposit" || type === "fiat_withdrawal") {
    document.getElementById("txn-asset").value = "FIAT";
    document.getElementById("txn-quantity").value = "0";
    assetField.style.display = "none";
    qtyField.style.display   = "none";
  } else {
    assetField.style.display = "";
    qtyField.style.display   = "";
    if (document.getElementById("txn-asset").value === "FIAT") {
      document.getElementById("txn-asset").value = "";
      document.getElementById("txn-quantity").value = "";
    }
  }
}

// ============================================================
// Initialisation
// ============================================================

async function init() {
  // Load config first for currency symbol
  try {
    state.config = await api.get("/config");
    document.getElementById("topbar-currency").textContent = state.config.base_currency || "USD";
  } catch (e) {
    console.warn("Config load failed", e);
  }

  // Nav clicks
  document.querySelectorAll(".nav-item").forEach(btn => {
    btn.addEventListener("click", () => navigate(btn.dataset.page));
  });

  // Transaction filters
  ["tx-filter-asset","tx-filter-type","tx-filter-wallet","tx-filter-year"].forEach(id => {
    document.getElementById(id)?.addEventListener("change", () => loadTransactions(true));
  });
  document.getElementById("tx-prev")?.addEventListener("click", () => {
    txnOffset = Math.max(0, txnOffset - TX_PAGE_SIZE);
    loadTransactions(false);
  });
  document.getElementById("tx-next")?.addEventListener("click", () => {
    txnOffset += TX_PAGE_SIZE;
    loadTransactions(false);
  });

  // Add txn modal
  document.getElementById("btn-add-txn")?.addEventListener("click", openAddTxnModal);
  document.getElementById("btn-close-add-txn")?.addEventListener("click", closeAddTxnModal);
  document.getElementById("btn-cancel-add-txn")?.addEventListener("click", closeAddTxnModal);
  document.getElementById("form-add-txn")?.addEventListener("submit", submitAddTxn);

  // Gains / Income filters
  document.getElementById("gains-filter-btn")?.addEventListener("click", loadGains);
  document.getElementById("income-filter-btn")?.addEventListener("click", loadIncome);

  // FX manual rate
  document.getElementById("form-manual-rate")?.addEventListener("submit", saveManualRate);

  // Settings
  document.getElementById("form-settings")?.addEventListener("submit", saveSettings);

  // Import tabs and upload zones
  setupImportTabs();
  setupUploadZone("zone-auto", "file-auto");
  setupUploadZone("zone-coinbase", "file-coinbase");
  setupUploadZone("zone-binance", "file-binance");
  setupUploadZone("zone-kraken", "file-kraken");
  setupUploadZone("zone-cryptodom", "file-cryptodom");

  // Default page
  navigate("dashboard");
}

document.addEventListener("DOMContentLoaded", init);

// ============================================================
// Telegram Admin Panel
// ============================================================

async function loadTelegramPage() {
  await loadTelegramConfig();
  await loadTelegramUsers();
  await loadTelegramSubscriptions();
}

async function loadTelegramConfig() {
  try {
    const cfg = await api.get("/telegram/config");
    // Badge
    const badge = document.getElementById("tg-bot-badge");
    if (cfg.bot_connected) {
      badge.textContent = `Connected @${cfg.bot_username || "bot"}`;
      badge.className = "badge badge-success";
    } else if (cfg.token_set) {
      badge.textContent = "Token set — not verified";
      badge.className = "badge badge-warning";
    } else {
      badge.textContent = "Not configured";
      badge.className = "badge badge-secondary";
    }
    // Fields — never show the actual token
    document.getElementById("tg-token-input").value = "";
    document.getElementById("tg-secret-input").value = "";
    document.getElementById("tg-admins-input").value = (cfg.admin_chat_ids || []).join(", ");
    document.getElementById("tg-notif-toggle").checked = cfg.notifications_enabled !== false;
    // Webhook
    if (cfg.webhook_url) {
      document.getElementById("tg-webhook-input").value = cfg.webhook_url;
      document.getElementById("tg-current-webhook").textContent = cfg.webhook_url;
      document.getElementById("tg-webhook-info").classList.remove("hidden");
    }
  } catch (e) {
    tgBanner(`Failed to load config: ${e.message}`, "error");
  }
}

async function saveTelegramConfig() {
  const tokenInput = document.getElementById("tg-token-input").value.trim();
  const secretInput = document.getElementById("tg-secret-input").value.trim();
  const adminsRaw = document.getElementById("tg-admins-input").value;
  const notifEnabled = document.getElementById("tg-notif-toggle").checked;

  const adminIds = adminsRaw.split(",")
    .map(s => parseInt(s.trim(), 10))
    .filter(n => !isNaN(n));

  const body = { admin_chat_ids: adminIds, notifications_enabled: notifEnabled };
  if (tokenInput) body.token = tokenInput;
  if (secretInput) body.webhook_secret = secretInput;

  try {
    await api.put("/telegram/config", body);
    tgBanner("Configuration saved.", "success");
    await loadTelegramConfig();
  } catch (e) {
    tgBanner(`Save failed: ${e.message}`, "error");
  }
}

async function registerWebhook() {
  const url = document.getElementById("tg-webhook-input").value.trim();
  if (!url) { tgBanner("Enter a webhook URL first.", "error"); return; }
  try {
    await api.post("/telegram/setwebhook", { url });
    tgBanner(`Webhook registered: ${url}`, "success");
    document.getElementById("tg-current-webhook").textContent = url;
    document.getElementById("tg-webhook-info").classList.remove("hidden");
  } catch (e) {
    tgBanner(`Webhook error: ${e.message}`, "error");
  }
}

async function sendTestNotification() {
  const chatId = parseInt(document.getElementById("tg-test-chatid").value, 10);
  const message = document.getElementById("tg-test-msg").value.trim();
  if (!chatId) { tgBanner("Enter a Chat ID.", "error"); return; }
  try {
    await api.post("/telegram/notify/test", { chat_id: chatId, message });
    tgBanner("Test notification sent!", "success");
  } catch (e) {
    tgBanner(`Failed: ${e.message}`, "error");
  }
}

async function loadTelegramUsers() {
  try {
    const data = await api.get("/telegram/users");
    const tbody = document.getElementById("tg-users-tbody");
    if (!data.users || data.users.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No users yet</td></tr>';
      return;
    }
    tbody.innerHTML = data.users.map(u => `
      <tr>
        <td><code>${u.chat_id}</code></td>
        <td>${u.username ? `@${u.username}` : "—"}</td>
        <td>${u.first_name || "—"}</td>
        <td>${u.wallets?.length || 0}</td>
        <td>${u.notifications_enabled ? "🔔 ON" : "🔕 OFF"}</td>
        <td>${u.is_admin ? "👑 Admin" : "User"}</td>
        <td>${u.registered_at ? u.registered_at.slice(0, 10) : "—"}</td>
        <td>
          <button class="btn btn-sm btn-danger" onclick="deleteTelegramUser(${u.chat_id})">Remove</button>
        </td>
      </tr>
    `).join("");
  } catch (e) {
    document.getElementById("tg-users-tbody").innerHTML =
      `<tr><td colspan="8" class="empty-state text-error">${e.message}</td></tr>`;
  }
}

async function deleteTelegramUser(chatId) {
  if (!confirm(`Remove user ${chatId}? They will lose their subscriptions.`)) return;
  try {
    await api.del(`/telegram/users/${chatId}`);
    toast("User removed", "success");
    await loadTelegramUsers();
    await loadTelegramSubscriptions();
  } catch (e) {
    toast(`Error: ${e.message}`, "error");
  }
}

async function loadTelegramSubscriptions() {
  try {
    const data = await api.get("/telegram/subscriptions");
    const tbody = document.getElementById("tg-subs-tbody");
    const subs = data.subscriptions || {};
    const keys = Object.keys(subs);
    if (keys.length === 0) {
      tbody.innerHTML = '<tr><td colspan="3" class="empty-state">No wallet subscriptions yet</td></tr>';
      return;
    }
    tbody.innerHTML = keys.map(addr => `
      <tr>
        <td><code>${addr}</code></td>
        <td>${subs[addr].length}</td>
        <td>${subs[addr].map(id => `<code>${id}</code>`).join(", ")}</td>
      </tr>
    `).join("");
  } catch (e) {
    document.getElementById("tg-subs-tbody").innerHTML =
      `<tr><td colspan="3" class="empty-state text-error">${e.message}</td></tr>`;
  }
}

function tgBanner(msg, type = "success") {
  const el = document.getElementById("tg-status-banner");
  el.textContent = msg;
  el.className = `alert alert-${type}`;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 5000);
}

// ============================================================
// Custom Report Builder
// ============================================================

const _rpt = {
  meta: null,       // {wallets, assets, types, years}
  lastResult: null, // last API response
};

async function loadReportBuilder() {
  try {
    _rpt.meta = await api.get("/reports/meta");
    _renderMultiselect("rpt-wallets-container", _rpt.meta.wallets, "rpt-wallet");
    _renderMultiselect("rpt-assets-container",  _rpt.meta.assets,  "rpt-asset");
    _renderTypeTags("rpt-types-container", _rpt.meta.types);
  } catch (e) {
    toast(`Failed to load report metadata: ${e.message}`, "error");
  }
}

// ── Multi-select helpers ──────────────────────────────────────

function _renderMultiselect(containerId, items, checkboxClass) {
  const box = document.getElementById(containerId);
  if (!items || items.length === 0) {
    box.innerHTML = '<span class="multiselect-placeholder">No data yet</span>';
    return;
  }
  box.innerHTML = items.map(item => `
    <label class="multiselect-item">
      <input type="checkbox" class="${checkboxClass}" value="${item}">
      <span>${item}</span>
    </label>
  `).join("");
}

function _renderTypeTags(containerId, types) {
  const box = document.getElementById(containerId);
  if (!types || types.length === 0) {
    box.innerHTML = '<span class="multiselect-placeholder">No data yet</span>';
    return;
  }
  const TYPE_COLORS = {
    buy: "tag-green", sell: "tag-red", receive: "tag-blue", send: "tag-orange",
    transfer_in: "tag-blue", transfer_out: "tag-orange", mining: "tag-purple",
    income: "tag-green", swap: "tag-yellow", fee: "tag-red",
    fiat_deposit: "tag-teal", fiat_withdrawal: "tag-red",
  };
  box.innerHTML = types.map(t => `
    <label class="tag-checkbox ${TYPE_COLORS[t] || ''}">
      <input type="checkbox" class="rpt-type" value="${t}" style="display:none">
      <span>${t.replace(/_/g, " ")}</span>
    </label>
  `).join("");
  // Toggle visual state on click
  box.querySelectorAll(".tag-checkbox").forEach(lbl => {
    lbl.addEventListener("click", () => {
      const cb = lbl.querySelector("input");
      cb.checked = !cb.checked;
      lbl.classList.toggle("tag-selected", cb.checked);
    });
  });
}

function _getChecked(cls) {
  return [...document.querySelectorAll(`.${cls}:checked`)].map(el => el.value);
}

// ── Quick date ranges ─────────────────────────────────────────

function applyQuickRange(val) {
  const from = document.getElementById("rpt-date-from");
  const to   = document.getElementById("rpt-date-to");
  const now  = new Date();
  const pad  = n => String(n).padStart(2, "0");
  const fmt  = d => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;

  from.value = "";
  to.value   = "";

  if (val === "all" || val === "") { return; }

  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  to.value = fmt(today);

  if (val === "last_30") {
    const d = new Date(today); d.setDate(d.getDate() - 30);
    from.value = fmt(d);
  } else if (val === "last_month") {
    const d = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    from.value = fmt(d);
    to.value   = fmt(new Date(today.getFullYear(), today.getMonth(), 0));
  } else if (val === "last_quarter") {
    const q = Math.floor(today.getMonth() / 3);
    const d = new Date(today.getFullYear(), (q - 1) * 3, 1);
    from.value = fmt(d);
    to.value   = fmt(new Date(today.getFullYear(), q * 3, 0));
  } else if (val === "last_year") {
    from.value = `${today.getFullYear() - 1}-01-01`;
    to.value   = `${today.getFullYear() - 1}-12-31`;
  } else if (val === "ytd") {
    from.value = `${today.getFullYear()}-01-01`;
  }
}

// ── Run report ────────────────────────────────────────────────

async function runReport() {
  const wallets = _getChecked("rpt-wallet");
  const assets  = _getChecked("rpt-asset");
  const types   = _getChecked("rpt-type");
  const dateFrom = document.getElementById("rpt-date-from").value;
  const dateTo   = document.getElementById("rpt-date-to").value;
  const groupBy  = document.getElementById("rpt-group-by").value;
  const currency = document.getElementById("rpt-currency").value;
  const method   = document.getElementById("rpt-method").value;
  const incGains = document.getElementById("rpt-include-gains").checked;

  const params = new URLSearchParams();
  if (wallets.length)  params.set("wallets",  wallets.join(","));
  if (assets.length)   params.set("assets",   assets.join(","));
  if (types.length)    params.set("types",    types.join(","));
  if (dateFrom)        params.set("date_from", dateFrom);
  if (dateTo)          params.set("date_to",   dateTo);
  if (groupBy)         params.set("group_by",  groupBy);
  if (currency)        params.set("base_currency", currency);
  if (method)          params.set("method",    method);
  if (incGains)        params.set("include_gains", "true");

  try {
    const data = await api.get(`/reports/custom?${params}`);
    _rpt.lastResult = data;
    _rpt.lastParams = params.toString();
    _renderReport(data);
  } catch (e) {
    toast(`Report error: ${e.message}`, "error");
  }
}

function _renderReport(data) {
  document.getElementById("rpt-empty").classList.add("hidden");
  document.getElementById("rpt-summary").classList.remove("hidden");

  const s = data.summary;
  const cur = s.base_currency;

  // KPI cards
  document.getElementById("rpt-kpi-grid").innerHTML = `
    <div class="kpi-card">
      <div class="kpi-label">Transactions</div>
      <div class="kpi-value">${s.count.toLocaleString()}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Total Inflow</div>
      <div class="kpi-value" style="color:var(--clr-success)">${fmtMoney(s.total_inflow)} ${cur}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Total Outflow</div>
      <div class="kpi-value" style="color:var(--clr-danger)">${fmtMoney(s.total_outflow)} ${cur}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Net</div>
      <div class="kpi-value" style="color:${parseFloat(s.net)>=0?'var(--clr-success)':'var(--clr-danger)'}">${fmtMoney(s.net)} ${cur}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Total Fees</div>
      <div class="kpi-value">${fmtMoney(s.total_fees)} ${cur}</div>
    </div>
  `;

  // Grouped table
  const grpSection = document.getElementById("rpt-grouped-section");
  if (data.grouped) {
    grpSection.classList.remove("hidden");
    const groupLabel = document.getElementById("rpt-group-by").options[document.getElementById("rpt-group-by").selectedIndex].text;
    document.getElementById("rpt-grouped-title").textContent = `Summary by ${groupLabel}`;
    document.getElementById("rpt-grouped-thead").innerHTML =
      `<th>${groupLabel}</th><th>Count</th><th>Inflow ${cur}</th><th>Outflow ${cur}</th><th>Net ${cur}</th><th>Fees ${cur}</th>`;
    document.getElementById("rpt-grouped-tbody").innerHTML = Object.entries(data.grouped).map(([k, v]) => `
      <tr>
        <td><strong>${k}</strong></td>
        <td>${v.count}</td>
        <td class="fiat-inflow">${fmtMoney(v.inflow)}</td>
        <td class="fiat-outflow">${fmtMoney(v.outflow)}</td>
        <td class="${parseFloat(v.net)>=0?'fiat-inflow':'fiat-outflow'}">${fmtMoney(v.net)}</td>
        <td>${fmtMoney(v.fees)}</td>
      </tr>
    `).join("");
  } else {
    grpSection.classList.add("hidden");
  }

  // Gains table
  const gainsSection = document.getElementById("rpt-gains-section");
  if (data.gains && data.gains.records.length) {
    gainsSection.classList.remove("hidden");
    const gs = data.gains.summary;
    const sign = v => parseFloat(v) >= 0 ? "+" : "";
    document.getElementById("rpt-gains-tbody").innerHTML = [
      `<tr class="table-subheader">
        <td colspan="6"><strong>Summary</strong></td>
        <td class="${parseFloat(gs.total_gain_loss_usd)>=0?'fiat-inflow':'fiat-outflow'}">
          ${sign(gs.total_gain_loss_usd)}${fmtMoney(gs.total_gain_loss_usd)} USD</td>
        <td>ST: ${fmtMoney(gs.short_term_usd)} / LT: ${fmtMoney(gs.long_term_usd)}</td>
      </tr>`,
      ...data.gains.records.map(g => `
        <tr>
          <td>${g.disposal_date ? g.disposal_date.slice(0,10) : "—"}</td>
          <td>${g.asset}</td>
          <td>${fmtNum(g.quantity_disposed)}</td>
          <td>${fmtMoney(g.proceeds_usd)}</td>
          <td>${fmtMoney(g.cost_basis_usd)}</td>
          <td>${fmtMoney(g.fee_usd || 0)}</td>
          <td class="${parseFloat(g.gain_loss_usd)>=0?'fiat-inflow':'fiat-outflow'}">
            ${sign(g.gain_loss_usd)}${fmtMoney(g.gain_loss_usd)}</td>
          <td><span class="badge ${g.is_long_term?'badge-success':'badge-warning'}">${g.is_long_term?"Long":"Short"}</span></td>
        </tr>
      `)
    ].join("");
  } else {
    gainsSection.classList.add("hidden");
  }

  // Transaction table
  const txns = data.transactions;
  document.getElementById("rpt-count-badge").textContent = txns.length;
  document.getElementById("rpt-txn-tbody").innerHTML = txns.length === 0
    ? '<tr><td colspan="9" class="empty-state">No transactions match these filters</td></tr>'
    : txns.map(t => `
      <tr>
        <td>${t.date ? t.date.slice(0,16).replace("T"," ") : "—"}</td>
        <td><span class="badge badge-type badge-${t.type}">${t.type}</span></td>
        <td><strong>${t.asset}</strong></td>
        <td class="mono">${fmtNum(t.quantity)}</td>
        <td class="mono">${t.price_usd ? "$"+fmtMoney(t.price_usd) : "—"}</td>
        <td class="mono">${t.total_usd ? "$"+fmtMoney(t.total_usd) : "—"}</td>
        <td class="mono">${t.fee_usd ? "$"+fmtMoney(t.fee_usd) : "—"}</td>
        <td>${t.wallet || "—"}</td>
        <td class="text-muted">${t.notes || ""}</td>
      </tr>
    `).join("");
}

// ── Export ────────────────────────────────────────────────────

function exportReport(format) {
  if (!_rpt.lastParams) { toast("Run a report first.", "error"); return; }
  const url = `/api/reports/export?format=${format}&${_rpt.lastParams}`;
  const a = document.createElement("a");
  a.href = url;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

function copyReportToClipboard() {
  if (!_rpt.lastResult) { toast("Run a report first.", "error"); return; }
  const data = _rpt.lastResult;
  const lines = [];
  const s = data.summary;
  lines.push(`Custom Report — ${new Date().toISOString().slice(0,10)}`);
  lines.push(`Transactions: ${s.count}  |  Inflow: ${s.total_inflow} ${s.base_currency}  |  Outflow: ${s.total_outflow}  |  Net: ${s.net}  |  Fees: ${s.total_fees}`);
  lines.push("");
  if (data.transactions.length) {
    lines.push(["Date","Type","Asset","Quantity","Price USD","Total USD","Fee USD","Wallet"].join("\t"));
    data.transactions.forEach(t => lines.push([
      t.date?.slice(0,16), t.type, t.asset, t.quantity,
      t.price_usd || "", t.total_usd || "", t.fee_usd || "", t.wallet || ""
    ].join("\t")));
  }
  navigator.clipboard.writeText(lines.join("\n"))
    .then(() => toast("Copied to clipboard!", "success"))
    .catch(() => toast("Copy failed — try the CSV export instead.", "error"));
}

// ── Helpers ───────────────────────────────────────────────────

function resetReportFilters() {
  document.getElementById("rpt-date-from").value = "";
  document.getElementById("rpt-date-to").value   = "";
  document.getElementById("rpt-quick-range").value = "";
  document.getElementById("rpt-group-by").value  = "";
  document.getElementById("rpt-currency").value  = "";
  document.getElementById("rpt-method").value    = "";
  document.getElementById("rpt-include-gains").checked = false;
  document.querySelectorAll(".rpt-wallet, .rpt-asset, .rpt-type").forEach(el => {
    el.checked = false;
    el.closest("label")?.classList.remove("tag-selected");
  });
  document.getElementById("rpt-summary").classList.add("hidden");
  document.getElementById("rpt-empty").classList.remove("hidden");
  _rpt.lastResult = null;
}

function fmtMoney(v) {
  const n = parseFloat(v) || 0;
  return Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtNum(v) {
  const n = parseFloat(v) || 0;
  if (Math.abs(n) < 0.0001) return n.toExponential(4);
  return n.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 8 });
}
