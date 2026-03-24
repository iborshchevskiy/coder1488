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
  dashboard:    "Dashboard",
  portfolio:    "Portfolio",
  transactions: "Transactions",
  gains:        "Capital Gains",
  income:       "Income",
  import:       "Import",
  exchange:     "Exchange Rates",
  settings:     "Settings",
};

const pageLoaders = {
  dashboard:    loadDashboard,
  portfolio:    loadPortfolio,
  transactions: loadTransactions,
  gains:        loadGains,
  income:       loadIncome,
  exchange:     loadExchangeRates,
  settings:     loadSettings,
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
    const [portfolio, summary, fx] = await Promise.all([
      api.get("/portfolio"),
      api.get("/summary"),
      api.get("/fx/rates").catch(() => null),
    ]);
    state.portfolio = portfolio;
    state.fxRates = fx;

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
