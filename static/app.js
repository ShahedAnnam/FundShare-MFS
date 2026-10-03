// ============================================================
//  FundShare App.js — Complete Frontend Engine
//  Handles: Auth, Navigation, All API calls, Role-based UI
// ============================================================

const state = {
  user: null,
  wallet: null,
  funds: [],
  merchants: [],
  familyPasses: { issued: [], received: [] },
  notifications: [],
  unreadNotifications: 0,
  currentTab: 'home',
  selectedMerchant: null,
  selectedFamilyPass: null,
  contacts: [],
  pickerConfig: null,
};

// ============================================================
// CSRF TOKEN
// ============================================================
function getCsrfToken() {
  const cookie = document.cookie.split(';').find(c => c.trim().startsWith('csrftoken='));
  return cookie ? cookie.split('=')[1].trim() : '';
}

// ============================================================
// HTTP HELPERS
// ============================================================
async function apiGet(url) {
  const r = await fetch(url, { credentials: 'same-origin' });
  if (r.status === 401) { window.location.href = '/login/'; return null; }
  return r.json();
}

async function apiPost(url, data) {
  const r = await fetch(url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
    body: JSON.stringify(data)
  });
  if (r.status === 401) { window.location.href = '/login/'; return null; }
  return { ok: r.ok, status: r.status, data: await r.json() };
}

async function apiPatch(url, data) {
  const r = await fetch(url, {
    method: 'PATCH',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
    body: JSON.stringify(data)
  });
  if (r.status === 401) { window.location.href = '/login/'; return null; }
  return { ok: r.ok, status: r.status, data: await r.json() };
}

async function apiDelete(url) {
  const r = await fetch(url, {
    method: 'DELETE',
    credentials: 'same-origin',
    headers: { 'X-CSRFToken': getCsrfToken() }
  });
  if (r.status === 401) { window.location.href = '/login/'; return null; }
  const data = r.status !== 204 ? await r.json().catch(() => ({})) : {};
  return { ok: r.ok, status: r.status, data };
}

// ============================================================
// TOAST NOTIFICATIONS
// ============================================================
function showToast(type, message, duration = 4000) {
  const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<span class="toast-icon">${icons[type] || 'ℹ️'}</span><span class="toast-msg">${message}</span>`;
  const container = document.getElementById('toastContainer');
  container.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transform = 'translateY(-10px)'; el.style.transition = '0.3s'; setTimeout(() => el.remove(), 300); }, duration);
}

// ============================================================
// MODAL MANAGEMENT
// ============================================================
function openModal(id) {
  const el = document.getElementById(id);
  if (el) { el.classList.add('show'); document.body.style.overflow = 'hidden'; }
  // Pre-populate wallet hint for fund creation
  if (id === 'createFundModal' && state.wallet) {
    document.getElementById('fundWalletHint').textContent = `Available wallet balance: ৳${fmt(state.wallet)}`;
  }
  if (id === 'transferFundModal') populateFundSelects();
  if (id === 'fpMemberPayModal') populateFPMerchantSelect();
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) { el.classList.remove('show'); document.body.style.overflow = ''; }
}

// Close on overlay click
document.addEventListener('click', e => {
  if (e.target.classList.contains('modal-overlay')) closeModal(e.target.id);
});

// ============================================================
// NAVIGATION
// ============================================================
const TAB_MAP = {
  home: 'home', funds: 'funds', payments: 'payments', familypass: 'familypass',
  ai: 'ai', more: 'more', history: 'home'
};

function navigateTo(tab) {
  if (tab === 'history') {
    openTxnHistoryModal();
    return;
  }
  const mapped = TAB_MAP[tab] || tab;
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const panel = document.getElementById(`tab-${mapped}`);
  const navBtn = document.getElementById(`nav-${mapped}`);
  if (panel) panel.classList.add('active');
  if (navBtn) navBtn.classList.add('active');
  state.currentTab = mapped;
  if (mapped === 'funds') loadFunds();
  if (mapped === 'payments') loadMerchants();
  if (mapped === 'familypass') loadFamilyPass();
  if (mapped === 'more') loadMoreTab();
  if (mapped === 'ai') initAiChat();
}

// ============================================================
// FORMAT HELPERS
// ============================================================
function fmt(n) { return parseFloat(n || 0).toLocaleString('en-BD', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function fmtDate(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleDateString('en-BD', { day: 'numeric', month: 'short' }) + ' ' + d.toLocaleTimeString('en-BD', { hour: '2-digit', minute: '2-digit', hour12: true });
}
function timeAgo(ts) {
  if (!ts) return '';
  const diff = (Date.now() - new Date(ts).getTime()) / 1000;
  if (diff < 60) return 'Just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

const CATEGORY_ICONS = {
  'Grocery': '🛒', 'Medicine': '💊', 'Treatment': '🏥', 'Education': '📚',
  'Electricity': '⚡', 'Restaurant/Food': '🍽', 'Transport': '🚌',
  'Rent': '🏠', 'Shopping': '🛍', 'Other': '📦'
};
const CATEGORY_COLORS = {
  'Grocery': '#10B981', 'Medicine': '#EF4444', 'Treatment': '#F59E0B',
  'Education': '#3B82F6', 'Electricity': '#FBBF24', 'Restaurant/Food': '#F97316',
  'Transport': '#6366F1', 'Rent': '#8B5CF6', 'Shopping': '#EC4899', 'Other': '#6B7280'
};
const TXN_TYPE_LABELS = {
  'CASH_IN': 'Add Money', 'SEND_MONEY': 'Send Money', 'MERCHANT_PAYMENT': 'Payment',
  'MOBILE_RECHARGE': 'Recharge', 'BILL_PAYMENT': 'Bill Pay', 'CASH_OUT': 'Cash Out',
  'FUND_ALLOCATION': 'Fund Allocation', 'FUND_TRANSFER': 'Fund Transfer'
};

// ============================================================
// INIT APP
// ============================================================
async function initApp() {
  const meData = await apiGet('/api/auth/me/');
  if (!meData) return;

  state.user = meData.user;
  state.wallet = meData.wallet_balance;
  state.unreadNotifications = meData.unread_notifications || 0;

  renderHeader();
  checkRoleBasedUI();
  await loadDashboard();
  loadNotifications();
  loadContacts();
  initAiChat();

  // Check for stored Gemini key
  const storedKey = localStorage.getItem('gemini_api_key');
  if (storedKey) {
    const input = document.getElementById('geminiKeyInput');
    if (input) input.value = storedKey;
    updateGeminiStatus(true);
  }
}

// ============================================================
// RENDER HEADER
// ============================================================
function renderHeader() {
  const u = state.user;
  if (!u) return;
  const initials = (u.full_name || u.username || 'U').substring(0, 2).toUpperCase();
  document.getElementById('headerAvatar').textContent = initials;
  document.getElementById('headerName').textContent = (u.full_name || u.username || 'User').split(' ')[0];
  if (state.unreadNotifications > 0) {
    const badge = document.getElementById('notifCount');
    badge.textContent = state.unreadNotifications;
    badge.style.display = 'flex';
  }
}

// ============================================================
// ROLE-BASED UI
// ============================================================
function checkRoleBasedUI() {
  const role = state.user?.effective_role || state.user?.role || 'CUSTOMER';
  // Show/hide nav items based on role
  const fundsNav = document.getElementById('nav-funds');
  const fpNav = document.getElementById('nav-familypass');
  const ov = document.getElementById('fpOwnerView');
  const mv = document.getElementById('fpMemberView');

  if (role === 'MERCHANT') {
    // Merchant: hide funds and familypass nav
    if (fundsNav) fundsNav.style.display = 'none';
    if (fpNav) fpNav.style.display = 'none';
  } else if (role === 'MEMBER') {
    // Member: show familypass but no fund creation
    if (fundsNav) fundsNav.style.display = 'none';
    if (fpNav) fpNav.style.display = 'flex';
    if (ov) ov.style.display = 'none';
    if (mv) mv.style.display = 'block';
  } else {
    // Customer / Wallet Owner: full normal access
    if (fundsNav) fundsNav.style.display = 'flex';
    if (fpNav) fpNav.style.display = 'flex';
    if (ov) ov.style.display = 'block';
    if (mv) mv.style.display = 'none';
  }

  // Role badge on profile
  const roleBadge = document.getElementById('profileRoleBadge');
  if (roleBadge) {
    const labels = {
      CUSTOMER: '👤 Customer / Wallet Owner',
      MEMBER: '👥 FamilyPass Member',
      MERCHANT: '🏪 Merchant',
      ADMIN: '🔑 Admin / Evaluator'
    };
    roleBadge.textContent = labels[role] || role;
  }
}

// ============================================================
// DASHBOARD
// ============================================================
async function loadDashboard() {
  const data = await apiGet('/api/wallet/summary/');
  if (!data) return;

  state.wallet = data.wallet_balance;
  document.getElementById('walletBalance').textContent = fmt(data.wallet_balance);
  document.getElementById('balanceSub').textContent =
    `Total Wealth: ৳${fmt(data.total_liquid_wealth)} • Funds: ৳${fmt(data.funds_total_balance)}`;

  // Recent transactions
  renderRecentTxns(data.recent_transactions || []);

  // FamilyPass alert
  if (data.active_family_passes_count > 0) {
    document.getElementById('fpAlertCard').style.display = 'block';
    document.getElementById('fpAlertContent').innerHTML =
      `<div style="font-size:13px;color:var(--text-secondary);">
        <span style="font-weight:600;color:var(--primary);">${data.active_family_passes_count}</span> active pass(es) • 
        Used: <strong>৳${fmt(data.family_pass_total_used)}</strong> • 
        Remaining: <strong>৳${fmt(data.family_pass_total_limit - data.family_pass_total_used)}</strong>
      </div>`;
  }

  // Overrun warning
  if (data.overrun_funds_count > 0) {
    showToast('warning', `⚠️ ${data.overrun_funds_count} fund(s) may exceed budget this month`);
  }
}

function renderTxnItemHtml(t) {
  const currentUserId = state.user ? state.user.id : null;
  const isRejected = t.status === 'REJECTED';
  const isCashIn = t.transaction_type === 'CASH_IN';
  const isIncomingP2P = (t.transaction_type === 'SEND_MONEY' || t.transaction_type === 'RECEIVE_MONEY') && currentUserId && (t.receiver === currentUserId) && (t.sender !== currentUserId);
  const isCredit = isCashIn || isIncomingP2P;
  const isFp = t.payment_source === 'FAMILY_PASS';
  const isFpMember = isFp && currentUserId && (t.sender === currentUserId);
  const isFpOwner = isFp && currentUserId && (t.sender !== currentUserId);

  let icon = CATEGORY_ICONS[t.category] || (isCredit ? '💚' : '💸');
  if (isRejected) icon = '🚫';
  else if (isFp) icon = '👨‍👩‍👧';
  else if (isCredit) icon = '⬆️';

  let title = t.merchant_name || t.receiver_name || TXN_TYPE_LABELS[t.transaction_type] || t.transaction_type;
  if (isCashIn) {
    title = 'Add Money (Bank Deposit)';
  } else if (isIncomingP2P) {
    title = `Received from ${t.sender_name || t.sender_username || 'User'}`;
  } else if (isFpOwner) {
    title = `${t.merchant_name || 'Merchant'} <span class="pill pill-purple" style="font-size:9px;">FamilyPass</span>`;
  } else if (isFpMember) {
    title = `${t.merchant_name || 'Merchant'} <span class="pill pill-purple" style="font-size:9px;">FamilyPass</span>`;
  }

  let meta = `${TXN_TYPE_LABELS[t.transaction_type] || t.transaction_type} • ${timeAgo(t.timestamp)}`;
  if (isRejected) {
    meta = `${t.rejection_reason || 'Transaction rejected'} • ${timeAgo(t.timestamp)}`;
  } else if (isFpOwner) {
    meta = `Spent by ${t.sender_name || t.sender_username || 'Member'} • ${timeAgo(t.timestamp)}`;
  } else if (isFpMember) {
    meta = `Paid via FamilyPass • ${timeAgo(t.timestamp)}`;
  }

  let amountHtml = '';
  if (isRejected) {
    amountHtml = `<div class="txn-amount" style="color:var(--danger);font-size:12px;font-weight:700;text-align:right;">
      ৳0.00
      <div style="font-size:9px;color:var(--danger);font-weight:600;">REJECTED</div>
    </div>`;
  } else if (isFpMember) {
    amountHtml = `<div class="txn-amount" style="color:var(--purple);font-size:12px;font-weight:700;text-align:right;">
      ৳${fmt(t.amount)}
      <div style="font-size:9px;color:var(--purple);font-weight:600;">Pass Spending</div>
    </div>`;
  } else if (isCredit) {
    amountHtml = `<div class="txn-amount credit">+৳${fmt(t.amount)}</div>`;
  } else {
    amountHtml = `<div class="txn-amount debit">-৳${fmt(t.amount)}</div>`;
  }

  return `<div class="txn-item">
    <div class="txn-icon ${isRejected ? 'debit' : (isCredit ? 'credit' : (isFp ? 'purple' : 'debit'))}">${icon}</div>
    <div class="txn-info">
      <div class="txn-name">${title}</div>
      <div class="txn-meta">${meta}</div>
    </div>
    ${amountHtml}
  </div>`;
}

function renderRecentTxns(txns) {
  const el = document.getElementById('recentTxns');
  if (!txns || txns.length === 0) {
    el.innerHTML = '<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-title">No transactions yet</div></div>';
    return;
  }
  el.innerHTML = txns.slice(0, 6).map(renderTxnItemHtml).join('');
}

let currentTxnFilter = '';

async function openTxnHistoryModal() {
  openModal('txnHistoryModal');
  await loadTxnHistory('');
}

async function loadTxnHistory(filterType = '') {
  currentTxnFilter = filterType;
  document.querySelectorAll('#txnHistoryFilters .ai-prompt-chip').forEach(btn => btn.classList.remove('active'));
  const activeId = filterType === 'MERCHANT_PAYMENT' ? 'thf-pay' :
                   filterType === 'CASH_IN' ? 'thf-cashin' :
                   filterType === 'SEND_MONEY' ? 'thf-send' :
                   filterType === 'CASH_OUT' ? 'thf-cashout' : 'thf-all';
  const activeBtn = document.getElementById(activeId);
  if (activeBtn) activeBtn.classList.add('active');

  const el = document.getElementById('fullTxnList');
  if (!el) return;
  el.innerHTML = '<div style="text-align:center;padding:24px;color:var(--text-muted);">Loading transactions...</div>';

  let url = '/api/transactions/';
  if (filterType) url += `?type=${filterType}`;
  const data = await apiGet(url);
  if (!data || data.length === 0) {
    el.innerHTML = '<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-title">No transactions found</div></div>';
    return;
  }
  el.innerHTML = data.map(renderTxnItemHtml).join('');
}

async function refreshFinancialState() {
  await loadDashboard();
  if (state.currentTab === 'funds') loadFunds();
  if (state.currentTab === 'familypass') loadFamilyPass();
  if (state.currentTab === 'more') loadMoreTab();
}

// ============================================================
// FUNDS
// ============================================================
async function loadFunds() {
  const funds = await apiGet('/api/funds/');
  if (!funds) return;
  state.funds = Array.isArray(funds) ? funds : [];
  renderFunds();
}

function renderFunds() {
  const el = document.getElementById('fundsList');
  const transferCard = document.getElementById('transferCard');
  if (state.funds.length === 0) {
    el.innerHTML = `<div class="empty-state">
      <div class="empty-icon">🎯</div>
      <div class="empty-title">No Purpose Funds yet</div>
      <div class="empty-sub">Create funds to control where your money is spent</div>
      <button class="btn-primary" style="max-width:200px;margin:0 auto;" onclick="openModal('createFundModal')">Create First Fund</button>
    </div>`;
    if (transferCard) transferCard.style.display = 'none';
    return;
  }
  if (transferCard && state.funds.length >= 2) transferCard.style.display = 'block';

  el.innerHTML = state.funds.map(f => {
    const alloc = parseFloat(f.allocated_amount) || 0;
    const curr = parseFloat(f.current_balance) || 0;
    const spent = Math.max(0, alloc - curr);
    const pct = alloc > 0 ? Math.min(100, (spent / alloc) * 100) : 0;
    const color = CATEGORY_COLORS[f.category] || '#10B981';
    const icon = CATEGORY_ICONS[f.category] || '💰';
    const fc = f.forecast;
    let forecastBadge = '';
    if (fc) {
      if (fc.potential_overrun > 0) {
        forecastBadge = `<span class="fund-forecast-badge forecast-danger">🔴 Risk: ৳${fmt(fc.potential_overrun)} overrun</span>`;
      } else {
        forecastBadge = `<span class="fund-forecast-badge forecast-ok">✅ On track</span>`;
      }
    }
    const recipientInfo = (f.recipient_name || f.recipient_username)
      ? `<div style="font-size:11px;color:var(--text-secondary);margin-top:4px;">👤 Recipient: <strong style="color:var(--text);">${f.recipient_name || f.recipient_username}</strong></div>`
      : '';

    return `<div class="fund-card" style="border-left-color:${color};">
      <div class="fund-header">
        <div class="fund-name-row">
          <div class="fund-icon" style="background:${color}22;">${icon}</div>
          <div>
            <div class="fund-name">${f.name}</div>
            <div class="fund-category">${f.category} • ${pct.toFixed(0)}% used</div>
            ${recipientInfo}
          </div>
        </div>
        <div class="fund-balance">
          <div class="fund-balance-amount">৳${fmt(curr)}</div>
          <div class="fund-balance-label">Remaining</div>
        </div>
      </div>
      <div class="fund-progress-bar">
        <div class="fund-progress-fill" style="width:${pct}%;background:${pct > 85 ? '#EF4444' : pct > 65 ? '#F59E0B' : color};"></div>
      </div>
      <div class="fund-stats">
        <span>Allocated: <span class="fund-stat-val">৳${fmt(alloc)}</span></span>
        <span>Spent: <span class="fund-stat-val">৳${fmt(spent)}</span></span>
      </div>
      ${forecastBadge}
      <div class="fund-card-actions">
        <button class="fund-action-btn" onclick="openEditFundModal(${f.id})">✏️ Edit</button>
        <button class="fund-action-btn fund-action-delete" onclick="doDeleteFund(${f.id}, '${f.name.replace(/'/g, "\\'")}')">🗑️ Delete</button>
      </div>
    </div>`;
  }).join('');
}

// ============================================================
// MERCHANTS
// ============================================================
let allMerchants = [];
let activeCategory = '';

async function loadMerchants() {
  if (allMerchants.length > 0) { renderMerchants(); return; }
  const merchants = await apiGet('/api/merchants/');
  if (!merchants) return;
  allMerchants = merchants;
  state.merchants = merchants;
  renderMerchants();
}

function filterMerchants(query) {
  const filtered = allMerchants.filter(m =>
    m.business_name.toLowerCase().includes(query.toLowerCase()) &&
    (activeCategory === '' || m.category === activeCategory)
  );
  renderMerchantGrid(filtered);
}

function filterByCategory(cat) {
  activeCategory = cat;
  document.querySelectorAll('#categoryFilter .ai-prompt-chip').forEach(btn => {
    btn.style.borderColor = btn.textContent.includes(cat === '' ? 'All' : cat) ? 'var(--primary)' : '';
    btn.style.color = btn.textContent.includes(cat === '' ? 'All' : cat) ? 'var(--primary)' : '';
    btn.style.background = btn.textContent.includes(cat === '' ? 'All' : cat) ? 'var(--primary-light)' : '';
  });
  filterMerchants(document.getElementById('merchantSearch')?.value || '');
}

function renderMerchants() {
  renderMerchantGrid(allMerchants);
}

function renderMerchantGrid(merchants) {
  const el = document.getElementById('merchantGrid');
  if (!merchants || merchants.length === 0) {
    el.innerHTML = '<div class="empty-state"><div class="empty-icon">🏪</div><div class="empty-title">No merchants found</div></div>';
    return;
  }
  el.innerHTML = merchants.map(m => {
    const icon = CATEGORY_ICONS[m.category] || '🏪';
    const color = CATEGORY_COLORS[m.category] || '#6B7280';
    return `<div class="card" style="margin-bottom:10px;cursor:pointer;border-left:4px solid ${color};" onclick="selectMerchant(${m.id})">
      <div style="display:flex;align-items:center;gap:12px;">
        <div style="width:46px;height:46px;border-radius:12px;background:${color}22;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0;">${icon}</div>
        <div style="flex:1;min-width:0;">
          <div style="font-size:14px;font-weight:700;color:var(--text);">${m.business_name}</div>
          <div style="font-size:12px;color:var(--text-muted);">${m.category}</div>
        </div>
        <div style="font-size:20px;">›</div>
      </div>
    </div>`;
  }).join('');
}

function selectMerchant(id) {
  state.selectedMerchant = allMerchants.find(m => m.id === id);
  if (!state.selectedMerchant) return;
  const m = state.selectedMerchant;
  document.getElementById('payMerchantSub').textContent = `Paying: ${m.business_name} (${m.category})`;
  buildPaymentSourceSelector(m);

  // Initialize checkout item builder
  checkoutItems.payMerchant = [];
  renderCheckoutPresets('payMerchant', m.category);
  renderCheckoutItemsList('payMerchant');
  syncCheckoutTotal('payMerchant');
  document.getElementById('payAmount').value = '';

  openModal('payMerchantModal');
}

function buildPaymentSourceSelector(merchant) {
  const el = document.getElementById('paySourceSelector');
  let html = `<div class="source-option selected" onclick="selectSource(this,'NORMAL_WALLET',null)">
    <span class="source-radio"></span>
    <div class="source-info">
      <div class="source-name">💰 Normal Wallet</div>
      <div class="source-balance">Balance: ৳${fmt(state.wallet)}</div>
    </div>
    <span class="source-badge source-badge-green">Default</span>
  </div>`;

  const matchingFunds = (state.funds || []).filter(f => f.category === merchant.category);
  matchingFunds.forEach(f => {
    html += `<div class="source-option" onclick="selectSource(this,'PURPOSE_FUND',${f.id})">
      <span class="source-radio"></span>
      <div class="source-info">
        <div class="source-name">${CATEGORY_ICONS[f.category] || '🎯'} ${f.name} Fund</div>
        <div class="source-balance">Remaining: ৳${fmt(f.current_balance)}</div>
      </div>
      <span class="source-badge source-badge-blue">Restricted</span>
    </div>`;
  });

  // If no matching fund but other funds exist — show disabled options
  const nonMatchingFunds = (state.funds || []).filter(f => f.category !== merchant.category);
  nonMatchingFunds.forEach(f => {
    html += `<div class="source-option" style="opacity:0.5;cursor:not-allowed;" title="Cannot pay ${merchant.category} merchant with ${f.category} fund">
      <span class="source-radio"></span>
      <div class="source-info">
        <div class="source-name">${CATEGORY_ICONS[f.category] || '🎯'} ${f.name} Fund <span class="pill pill-red" style="font-size:9px;">RESTRICTED</span></div>
        <div class="source-balance">Category mismatch: ${f.category} ≠ ${merchant.category}</div>
      </div>
    </div>`;
  });

  // FamilyPass for members
  const receivedPasses = (state.familyPasses.received || []).filter(fp => fp.status === 'ACTIVE');
  receivedPasses.forEach(fp => {
    const pIcon = PURPOSE_ICONS[fp.purpose] || '🎯';
    html += `<div class="source-option" onclick="selectSource(this,'FAMILY_PASS',${fp.id})">
      <span class="source-radio"></span>
      <div class="source-info">
        <div class="source-name">👨‍👩‍👧 ${pIcon} ${fp.purpose_label} (from ${fp.owner_name || 'Owner'})</div>
        <div class="source-balance">Available: ৳${fmt(fp.remaining_limit)} / Limit: ৳${fmt(fp.limit_amount)} • Expires: ${fp.expiry_date}</div>
      </div>
      <span class="source-badge source-badge-purple">FamilyPass</span>
    </div>`;
  });

  el.innerHTML = html;
  el.dataset.source = 'NORMAL_WALLET';
  el.dataset.fundId = '';
  el.dataset.fpId = '';
}

function selectSource(el, source, id) {
  document.querySelectorAll('.source-option').forEach(o => o.classList.remove('selected'));
  el.classList.add('selected');
  const selector = document.getElementById('paySourceSelector');
  selector.dataset.source = source;
  selector.dataset.fundId = (source === 'PURPOSE_FUND') ? id : '';
  selector.dataset.fpId = (source === 'FAMILY_PASS') ? id : '';
}

// ============================================================
// FAMILYPASS PURPOSE CONFIGURATION & METADATA
// ============================================================
const PURPOSE_ICONS = {
  'Grocery': '🛒',
  'Education': '📚',
  'Medical': '💊',
  'Shopping': '🛍️',
  'Dining': '🍽️',
  'Transport': '🚌',
  'Bills & Utilities': '⚡',
  'Emergency': '🚨',
  'Other': '📦'
};

function onFPPurposeSelectChange(mode) {
  const prefix = mode === 'edit' ? 'editFP' : 'fp';
  const sel = document.getElementById(`${prefix}PurposeSelect`);
  const purpose = sel ? sel.value : 'Grocery';
  const customGroup = document.getElementById(`${prefix}CustomPurposeGroup`);

  if (purpose === 'Other') {
    if (customGroup) customGroup.style.display = 'block';
  } else {
    if (customGroup) customGroup.style.display = 'none';
  }
}

// ============================================================
// FAMILYPASS
// ============================================================
async function loadFamilyPass() {
  const data = await apiGet('/api/family-pass/');
  if (!data) return;
  state.familyPasses = { issued: data.issued_passes || [], received: data.received_passes || [] };
  if (data.effective_role && state.user) {
    state.user.role = data.effective_role;
    state.user.effective_role = data.effective_role;
    state.user.effective_role_display = data.effective_role_display;
    checkRoleBasedUI();
  }
  renderFamilyPass();
}

function renderFamilyPass() {
  const role = state.user?.effective_role || state.user?.role;
  if (role === 'MEMBER') {
    renderFPMemberView();
  } else {
    renderFPOwnerView();
  }
}

function renderFPOwnerView() {
  const el = document.getElementById('fpIssuedList');
  const passes = state.familyPasses.issued || [];
  if (passes.length === 0) {
    el.innerHTML = `<div class="empty-state">
      <div class="empty-icon">👨‍👩‍👧</div>
      <div class="empty-title">No FamilyPass issued</div>
      <div class="empty-sub">Grant a FamilyPass to let trusted family members spend from your wallet</div>
      <button class="btn-primary" style="max-width:200px;margin:0 auto;" onclick="openModal('createFPModal')">Grant FamilyPass</button>
    </div>`;
    return;
  }
  el.innerHTML = passes.map(fp => {
    const limit = parseFloat(fp.limit_amount) || 0;
    const used = parseFloat(fp.used_amount) || 0;
    const rem = parseFloat(fp.remaining_limit) || (limit - used);
    const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;
    const statusClass = { ACTIVE: 'fp-status-active', REVOKED: 'fp-status-revoked', EXPIRED: 'fp-status-expired' }[fp.status] || 'fp-status-expired';
    const initials = (fp.member_name || fp.member_username || 'M').substring(0, 2).toUpperCase();
    const pIcon = PURPOSE_ICONS[fp.purpose] || '🎯';

    return `<div class="fp-card">
      <div class="fp-header">
        <div class="fp-member">
          <div class="fp-avatar">${initials}</div>
          <div>
            <div class="fp-member-name">${fp.member_name || fp.member_username} (@${fp.member_username})</div>
            <div style="margin-top:2px;">
              <span class="pill pill-green" style="font-size:10px;font-weight:700;">${pIcon} ${fp.purpose_label || 'Family Spending'}</span>
            </div>
          </div>
        </div>
        <span class="fp-status-badge ${statusClass}">${fp.status}</span>
      </div>
      <div class="fp-progress-section">
        <div class="fp-progress-label">
          <span>Used: ৳${fmt(used)}</span>
          <span>Limit: ৳${fmt(limit)}</span>
        </div>
        <div class="fp-progress-bar">
          <div class="fp-progress-fill" style="width:${pct}%;background:${pct > 85 ? '#EF4444' : pct > 65 ? '#F59E0B' : 'var(--primary)'};"></div>
        </div>
      </div>
      <div class="fp-meta-grid">
        <div class="fp-meta-item">
          <span class="fp-meta-value">৳${fmt(rem)}</span>
          <span class="fp-meta-label">Remaining</span>
        </div>
        <div class="fp-meta-item">
          <span class="fp-meta-value">${fp.expiry_date || '---'}</span>
          <span class="fp-meta-label">Expires</span>
        </div>
        <div class="fp-meta-item">
          <span class="fp-meta-value">${fp.allowed_action === 'ALL' ? 'All Actions' : 'Merchant Pay'}</span>
          <span class="fp-meta-label">Permission</span>
        </div>
      </div>
      ${fp.status === 'ACTIVE' ? `<div class="fp-actions">
        <button class="fp-action-btn fp-action-edit" onclick="openEditFPModal(${fp.id})">✏️ Edit</button>
        <button class="fp-action-btn fp-action-revoke" onclick="revokeFP(${fp.id})">🚫 Revoke</button>
        <button class="fp-action-btn fp-action-view" onclick="viewFPActivity(${fp.id})">📋 View Activity</button>
      </div>` : `<div class="fp-actions">
        <button class="fp-action-btn fp-action-view" style="flex:1;" onclick="viewFPActivity(${fp.id})">📋 View Activity</button>
      </div>`}
    </div>`;
  }).join('');
}

function renderFPMemberView() {
  const received = state.familyPasses.received || [];
  const el = document.getElementById('fpReceivedList');
  if (received.length === 0) {
    el.innerHTML = `<div class="empty-state">
      <div class="empty-icon">🎁</div>
      <div class="empty-title">No FamilyPass received</div>
      <div class="empty-sub">Ask your family member to grant you a FamilyPass</div>
    </div>`;
    return;
  }
  el.innerHTML = received.map(fp => {
    const limit = parseFloat(fp.limit_amount) || 0;
    const used = parseFloat(fp.used_amount) || 0;
    const rem = parseFloat(fp.remaining_limit) || (limit - used);
    const pIcon = PURPOSE_ICONS[fp.purpose] || '🎯';

    return `<div class="received-fp-card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;">
        <div class="rfp-owner">From: <strong>${fp.owner_name || fp.owner_username}</strong></div>
        <span class="pill pill-purple" style="font-size:11px;background:rgba(255,255,255,0.25);color:#fff;font-weight:700;">${pIcon} ${fp.purpose_label}</span>
      </div>
      <div class="rfp-limit">৳${fmt(limit)}</div>
      <div class="rfp-limit-label">Total Spending Limit</div>
      <div class="rfp-remaining">৳${fmt(rem)} remaining</div>
      <div class="rfp-expiry" style="margin-top:6px;">
        📅 Valid until: <strong>${fp.expiry_date || '---'}</strong>
      </div>
      <div style="height:16px"></div>
      <button class="btn-primary" style="background:rgba(255,255,255,0.25);border:1.5px solid rgba(255,255,255,0.4);" 
        onclick="openFPMemberPay(${fp.id},'${fp.owner_name || fp.owner_username}',${rem})">
        💳 Use FamilyPass to Pay
      </button>
    </div>`;
  }).join('');
}

// ============================================================
// MORE TAB (Merchant, Admin, Reports)
// ============================================================
async function loadMoreTab() {
  const role = state.user?.role;
  const profileData = state.user;
  document.getElementById('profileName').textContent = profileData?.full_name || profileData?.username || 'User';
  document.getElementById('profilePhone').textContent = profileData?.phone || `@${profileData?.username}`;
  const initials = (profileData?.full_name || profileData?.username || 'U').substring(0, 2).toUpperCase();
  document.getElementById('profileAvatar').textContent = initials;

  if (role === 'MERCHANT') {
    document.getElementById('merchantDashSection').style.display = 'block';
    document.getElementById('reportsSection').style.display = 'none';
    await loadMerchantDashboard();
  } else if (role === 'ADMIN') {
    document.getElementById('evalSection').style.display = 'block';
    await loadEvalDashboard();
    loadReport('monthly');
  } else {
    loadReport('monthly');
  }
}

async function loadMerchantDashboard() {
  const data = await apiGet('/api/merchant/dashboard/');
  if (!data || !data.merchant) return;
  const m = data.merchant;
  document.getElementById('mDashName').textContent = m.business_name;
  document.getElementById('mDashCat').textContent = m.category;
  document.getElementById('mDashTotal').textContent = `৳${fmt(data.total_received_volume)}`;
  const txnEl = document.getElementById('merchantTxnList');
  if (!data.transactions || data.transactions.length === 0) {
    txnEl.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);">No transactions yet</div>';
    return;
  }
  txnEl.innerHTML = data.transactions.map(t => `
    <div class="txn-item">
      <div class="txn-icon credit">💳</div>
      <div class="txn-info">
        <div class="txn-name">${t.sender_name || 'Customer'}</div>
        <div class="txn-meta">${t.payment_source} • ${timeAgo(t.timestamp)}</div>
      </div>
      <div class="txn-amount credit">+৳${fmt(t.amount)}</div>
    </div>`).join('');
}

async function loadEvalDashboard() {
  const data = await apiGet('/api/evaluation/metrics/');
  if (!data) return;
  const metricsEl = document.getElementById('evalMetrics');
  const anomaly = data.anomaly_detection || {};
  const forecast = data.forecasting || {};
  const ds = data.dataset_stats || {};
  metricsEl.innerHTML = `
    <div class="metric-card">
      <div class="metric-value">${(anomaly.f1_score || 0).toFixed(2)}</div>
      <div class="metric-label">Anomaly F1-Score</div>
      <div class="metric-sub">Precision: ${(anomaly.precision || 0).toFixed(2)}</div>
    </div>
    <div class="metric-card">
      <div class="metric-value">${(anomaly.roc_auc || 0).toFixed(3)}</div>
      <div class="metric-label">ROC-AUC Score</div>
      <div class="metric-sub">IsolationForest ML</div>
    </div>
    <div class="metric-card">
      <div class="metric-value">৳${fmt(forecast.mae || 0)}</div>
      <div class="metric-label">Forecast MAE</div>
      <div class="metric-sub">Budget Predictor</div>
    </div>
    <div class="metric-card">
      <div class="metric-value">${ds.total_transactions || 0}</div>
      <div class="metric-label">Total Transactions</div>
      <div class="metric-sub">${ds.synthetic_customers || 0} customers</div>
    </div>`;
  document.getElementById('evalDetailsCard').innerHTML = `
    <div class="card-header"><span class="card-title">📊 ML Performance Summary</span></div>
    <div style="font-size:13px;line-height:1.8;color:var(--text-secondary);">
      <div>🤖 <strong>Anomaly Detector:</strong> IsolationForest — Recall ${(anomaly.recall||0).toFixed(2)}, F1 ${(anomaly.f1_score||0).toFixed(2)}</div>
      <div>📈 <strong>Budget Forecaster:</strong> MAE ৳${fmt(forecast.mae||0)}, RMSE ৳${fmt(forecast.rmse||0)}</div>
      <div>🔐 <strong>Privacy:</strong> ${data.responsible_ai_summary?.privacy || 'Synthetic data only'}</div>
      <div>👁 <strong>Transparency:</strong> ${data.responsible_ai_summary?.transparency || 'Explainable AI'}</div>
      <div>✋ <strong>Control:</strong> ${data.responsible_ai_summary?.human_control || 'Human-in-the-loop'}</div>
    </div>`;
}

async function loadReport(period) {
  const data = await apiGet(`/api/reports/?period=${period}`);
  if (!data) return;
  const el = document.getElementById('reportContent');
  const stats = data.overview || {};
  const byCategory = data.by_category || {};
  const categories = Object.entries(byCategory).sort((a,b) => b[1]-a[1]);
  const maxVal = categories.length > 0 ? categories[0][1] : 1;

  el.innerHTML = `
    <div class="report-stat-grid">
      <div class="report-stat">
        <div class="report-stat-val">৳${fmt(stats.total_spent || 0)}</div>
        <div class="report-stat-label">Total Spent</div>
      </div>
      <div class="report-stat">
        <div class="report-stat-val">${stats.total_transactions || 0}</div>
        <div class="report-stat-label">Transactions</div>
      </div>
      <div class="report-stat">
        <div class="report-stat-val">৳${fmt(stats.average_transaction || 0)}</div>
        <div class="report-stat-label">Avg Transaction</div>
      </div>
      <div class="report-stat">
        <div class="report-stat-val">${stats.savings_rate !== undefined && stats.savings_rate !== null ? (stats.savings_rate * 100).toFixed(1) + '%' : 'N/A'}</div>
        <div class="report-stat-label">Savings Rate</div>
      </div>
    </div>
    ${categories.length > 0 ? `
    <div class="report-bar-chart">
      <div class="card-title" style="margin-bottom:14px;">Spending by Category</div>
      ${categories.map(([cat, amt]) => `
        <div class="bar-row">
          <div class="bar-label">${CATEGORY_ICONS[cat] || '📦'} ${cat}</div>
          <div class="bar-bg"><div class="bar-fill" style="width:${(amt/maxVal)*100}%;background:${CATEGORY_COLORS[cat]||'var(--primary)'};"></div></div>
          <div class="bar-value">৳${fmt(amt)}</div>
        </div>`).join('')}
    </div>` : '<div style="font-size:12px;color:var(--text-muted);text-align:center;padding:12px;">No spending recorded in this period</div>'}
    ${data.ai_summary ? `
    <div class="card" style="margin-top:14px;background:var(--primary-light);border:1px solid rgba(0,135,90,0.2);">
      <div style="font-size:12px;font-weight:700;color:var(--primary-dark);margin-bottom:4px;">🤖 AI Financial Insights (${data.report_title || 'Report'})</div>
      <div style="font-size:12px;color:var(--text);line-height:1.5;">${data.ai_summary}</div>
    </div>` : ''}`;
}

// ============================================================
// NOTIFICATIONS
// ============================================================
async function loadNotifications() {
  const data = await apiGet('/api/notifications/');
  if (!data) return;
  state.notifications = data;
  renderNotifications();
}

function renderNotifications() {
  const el = document.getElementById('notifList');
  if (!state.notifications || state.notifications.length === 0) {
    el.innerHTML = '<div class="empty-state"><div class="empty-icon">🔔</div><div class="empty-title">No notifications</div></div>';
    return;
  }
  el.innerHTML = state.notifications.map(n => `
    <div class="notif-item ${!n.is_read ? 'unread' : ''}" onclick="markNotifRead(${n.id})">
      <div class="notif-item-title">${n.title}</div>
      <div class="notif-item-msg">${n.message}</div>
      <div class="notif-item-time">${timeAgo(n.created_at)}</div>
    </div>`).join('');
}

async function markNotifRead(id) {
  await apiPost(`/api/notifications/${id}/read/`, {});
  const notif = state.notifications.find(n => n.id === id);
  if (notif) notif.is_read = true;
  renderNotifications();
}

function openNotifications() {
  document.getElementById('notifPanel').classList.add('open');
  document.getElementById('notifOverlay').classList.add('show');
  document.getElementById('notifCount').style.display = 'none';
  loadNotifications();
}

function closeNotifications() {
  document.getElementById('notifPanel').classList.remove('open');
  document.getElementById('notifOverlay').classList.remove('show');
}

// ============================================================
// AI COACH
// ============================================================
let aiInitialized = false;

function initAiChat() {
  if (aiInitialized) return;
  aiInitialized = true;
  // Check if Gemini key is available
  const storedKey = localStorage.getItem('gemini_api_key');
  const badge = document.getElementById('aiInitBadge');
  if (badge) {
    badge.textContent = storedKey ? 'Gemini 2.0 Flash' : 'Offline AI Engine';
    badge.className = `ai-source-badge ${storedKey ? 'ai-powered-badge' : ''}`;
  }
}

function sendQuickPrompt(prompt) {
  const input = document.getElementById('chatInput');
  if (input) input.value = prompt;
  sendAiMessage();
}

async function sendAiMessage() {
  const input = document.getElementById('chatInput');
  const question = input?.value?.trim();
  if (!question) return;
  input.value = '';

  const container = document.getElementById('chatContainer');
  // Add user message
  container.innerHTML += `<div class="chat-msg user">
    <div class="chat-bubble">${question}</div>
    <div class="chat-time">${new Date().toLocaleTimeString('en-BD', {hour:'2-digit',minute:'2-digit',hour12:true})}</div>
  </div>`;

  // Add loading
  const loadId = 'loading_' + Date.now();
  container.innerHTML += `<div class="chat-msg ai" id="${loadId}">
    <div class="chat-bubble">🤔 Analyzing your financial data...</div>
  </div>`;
  container.scrollTop = container.scrollHeight;

  const result = await apiPost('/api/ai/query/', { question, lang: 'en' });
  document.getElementById(loadId)?.remove();

  if (!result || !result.data) {
    container.innerHTML += `<div class="chat-msg ai"><div class="chat-bubble">⚠️ Could not get AI response. Please try again.</div></div>`;
    container.scrollTop = container.scrollHeight;
    return;
  }

  const resp = result.data;
  const answer = resp.answer || resp.error || 'No response';
  const source = resp.source || 'AI Engine';
  const isGemini = resp.ai_powered;
  const formattedAnswer = answer.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>').replace(/•/g, '<br>•');

  container.innerHTML += `<div class="chat-msg ai">
    <div class="chat-bubble">${formattedAnswer}</div>
    <div class="chat-time">
      ${new Date().toLocaleTimeString('en-BD', {hour:'2-digit',minute:'2-digit',hour12:true})}
      <span class="ai-source-badge ${isGemini ? 'ai-powered-badge' : ''}">${source}</span>
    </div>
  </div>`;
  container.scrollTop = container.scrollHeight;
}

// ============================================================
// TRANSACTIONS (ACTIONS)
// ============================================================
async function doCashIn() {
  const amount = document.getElementById('cashInAmount').value;
  const ref = document.getElementById('cashInRef').value;
  if (!amount || amount <= 0) { showToast('error', 'Enter a valid amount'); return; }
  const r = await apiPost('/api/wallet/cash-in/', { amount, reference: ref });
  if (!r) return;
  if (r.ok) {
    showToast('success', r.data.message || 'Money added successfully!');
    closeModal('cashInModal');
    document.getElementById('cashInAmount').value = '';
    state.wallet = r.data.new_balance;
    document.getElementById('walletBalance').textContent = fmt(state.wallet);
    refreshFinancialState();
  } else {
    showToast('error', r.data.error || 'Failed to add money');
  }
}

async function doSendMoney() {
  const receiver = document.getElementById('sendReceiver').value;
  const amount = document.getElementById('sendAmount').value;
  const ref = document.getElementById('sendRef').value;
  if (!receiver) { showToast('error', 'Enter recipient phone or username'); return; }
  if (!amount || amount <= 0) { showToast('error', 'Enter a valid amount'); return; }
  const r = await apiPost('/api/wallet/send/', { receiver, amount, reference: ref });
  if (!r) return;
  if (r.ok) {
    showToast('success', r.data.message || 'Money sent!');
    closeModal('sendMoneyModal');
    document.getElementById('sendAmount').value = '';
    document.getElementById('sendReceiver').value = '';
    refreshFinancialState();
  } else {
    showToast('error', r.data.error || 'Transfer failed');
  }
}

async function doUtility(type, amountId, refId) {
  const amount = document.getElementById(amountId)?.value;
  const refEl = document.getElementById(refId);
  const ref = refEl ? refEl.value : '';
  if (!amount || amount <= 0) { showToast('error', 'Enter a valid amount'); return; }
  const r = await apiPost('/api/wallet/utility/', { action_type: type, amount, reference: ref });
  if (!r) return;
  const modalMap = { RECHARGE: 'rechargeModal', BILL: 'billModal', CASHOUT: 'cashOutModal' };
  if (r.ok) {
    showToast('success', r.data.message || 'Transaction successful!');
    closeModal(modalMap[type]);
    document.getElementById(amountId).value = '';
    refreshFinancialState();
  } else {
    showToast('error', r.data.error || 'Transaction failed');
  }
}

async function doCreateFund() {
  const name = document.getElementById('fundName').value.trim();
  const category = document.getElementById('fundCategory').value;
  const allocation = document.getElementById('fundAllocation').value;
  const budget = document.getElementById('fundBudget').value;
  const recipientEl = document.getElementById('fundRecipient');
  const recipient = recipientEl ? recipientEl.value.trim() : '';

  if (!name) { showToast('error', 'Enter a fund name'); return; }
  if (!category) { showToast('error', 'Select a category'); return; }

  const payload = {
    name, category,
    allocated_amount: allocation || '0',
    monthly_budget: budget || allocation || '0'
  };
  if (recipient) {
    payload.recipient = recipient;
  }

  const r = await apiPost('/api/funds/', payload);
  if (!r) return;
  if (r.ok) {
    showToast('success', `✅ ${name} Fund created!`);
    closeModal('createFundModal');
    document.getElementById('fundName').value = '';
    document.getElementById('fundCategory').value = '';
    document.getElementById('fundAllocation').value = '';
    document.getElementById('fundBudget').value = '';
    if (recipientEl) recipientEl.value = '';
    refreshFinancialState();
  } else {
    showToast('error', r.data.error || 'Failed to create fund');
  }
}

function openEditFundModal(fundId) {
  const fund = state.funds.find(f => f.id === fundId);
  if (!fund) return;
  document.getElementById('editFundId').value = fund.id;
  document.getElementById('editFundName').value = fund.name || '';
  document.getElementById('editFundCategory').value = fund.category || '';
  document.getElementById('editFundRecipient').value = fund.recipient_username || fund.recipient_phone || '';
  document.getElementById('editFundBudget').value = fund.monthly_budget || '';
  openModal('editFundModal');
}

async function doUpdateFund() {
  const id = document.getElementById('editFundId').value;
  const name = document.getElementById('editFundName').value.trim();
  const category = document.getElementById('editFundCategory').value;
  const recipient = document.getElementById('editFundRecipient').value.trim();
  const budget = document.getElementById('editFundBudget').value;

  if (!name) { showToast('error', 'Enter a fund name'); return; }
  if (!category) { showToast('error', 'Select a category'); return; }

  const payload = {
    name,
    category,
    monthly_budget: budget || '0',
    recipient: recipient || ''
  };

  const r = await apiPatch(`/api/funds/${id}/`, payload);
  if (!r) return;
  if (r.ok) {
    showToast('success', `✅ Fund updated successfully!`);
    closeModal('editFundModal');
    refreshFinancialState();
  } else {
    showToast('error', r.data?.error || 'Failed to update fund');
  }
}

async function doDeleteFund(fundId, fundName) {
  if (!confirm(`Are you sure you want to delete or close "${fundName}"?\nAny remaining balance will be returned to your wallet.`)) {
    return;
  }
  const r = await apiDelete(`/api/funds/${fundId}/`);
  if (!r) return;
  if (r.ok) {
    showToast('success', r.data?.message || 'Fund deleted/closed successfully');
    refreshFinancialState();
  } else {
    showToast('error', r.data?.error || 'Failed to delete fund');
  }
}

function populateFundSelects() {
  const src = document.getElementById('transferSource');
  const dst = document.getElementById('transferDest');
  const opts = state.funds.map(f => `<option value="${f.id}">${CATEGORY_ICONS[f.category]||'💰'} ${f.name} (৳${fmt(f.current_balance)})</option>`).join('');
  if (src) src.innerHTML = opts;
  if (dst) dst.innerHTML = opts;
}

async function doFundTransfer() {
  const srcId = document.getElementById('transferSource').value;
  const dstId = document.getElementById('transferDest').value;
  const amount = document.getElementById('transferAmount').value;
  const reason = document.getElementById('transferReason').value;
  if (!srcId || !dstId) { showToast('error', 'Select source and destination funds'); return; }
  if (srcId === dstId) { showToast('error', 'Source and destination cannot be the same'); return; }
  if (!amount || amount <= 0) { showToast('error', 'Enter a valid amount'); return; }
  const r = await apiPost('/api/funds/transfer/', { source_fund_id: srcId, destination_fund_id: dstId, amount, reason });
  if (!r) return;
  if (r.ok) {
    showToast('success', r.data.message || 'Transfer successful!');
    closeModal('transferFundModal');
    document.getElementById('transferAmount').value = '';
    refreshFinancialState();
  } else {
    showToast('error', r.data.error || 'Transfer failed');
  }
}

// ============================================================
// CHECKOUT ITEM BUILDER
// ============================================================
const checkoutItems = {
  payMerchant: [],
  fpMember: []
};

const MERCHANT_PRESETS = {
  'Grocery': [
    { name: 'Rice (Miniket 2kg)', qty: 2, price: 80 },
    { name: 'Soybean Oil (1L)', qty: 1, price: 180 },
    { name: 'Fresh Milk (1L)', qty: 1, price: 90 },
    { name: 'Sugar (1kg)', qty: 1, price: 135 },
    { name: 'Atta / Flour (2kg)', qty: 2, price: 55 }
  ],
  'Medicine': [
    { name: 'Napa Extra (1 strip)', qty: 1, price: 35 },
    { name: 'Paracetamol 500mg', qty: 1, price: 25 },
    { name: 'Antacid Plus', qty: 1, price: 30 },
    { name: 'Cevit / Vitamin C', qty: 1, price: 40 }
  ],
  'Treatment': [
    { name: 'Doctor Consultation', qty: 1, price: 500 },
    { name: 'Blood Glucose Test', qty: 1, price: 250 },
    { name: 'ECG Report', qty: 1, price: 400 }
  ],
  'Education': [
    { name: 'Notebooks (3 pack)', qty: 3, price: 60 },
    { name: 'Pen Set (10 pcs)', qty: 1, price: 120 },
    { name: 'Reference Textbook', qty: 1, price: 350 }
  ],
  'Restaurant/Food': [
    { name: 'Chicken Biryani', qty: 1, price: 220 },
    { name: 'Soft Drink (500ml)', qty: 1, price: 40 },
    { name: 'Mineral Water (500ml)', qty: 1, price: 25 }
  ],
  'default': [
    { name: 'Standard Product', qty: 1, price: 100 },
    { name: 'Essential Goods', qty: 1, price: 150 }
  ]
};

function renderCheckoutPresets(prefix, category) {
  const container = document.getElementById(`${prefix}Presets`);
  if (!container) return;
  const presets = MERCHANT_PRESETS[category] || MERCHANT_PRESETS['default'];
  container.innerHTML = presets.map((p, i) => `
    <span class="checkout-preset-tag" onclick="applyCheckoutPreset('${prefix}', '${p.name}', ${p.qty}, ${p.price})">+ ${p.name} (৳${p.price})</span>
  `).join('');
}

function applyCheckoutPreset(prefix, name, qty, price) {
  addCheckoutItemRow(prefix, name, qty, price);
}

function addCheckoutItemRow(prefix, name = '', qty = 1, price = 0) {
  checkoutItems[prefix].push({
    item_name: name,
    quantity: qty,
    unit_price: price
  });
  renderCheckoutItemsList(prefix);
  syncCheckoutTotal(prefix);
}

function removeCheckoutItemRow(prefix, index) {
  checkoutItems[prefix].splice(index, 1);
  renderCheckoutItemsList(prefix);
  syncCheckoutTotal(prefix);
}

function updateCheckoutItem(prefix, index, field, value) {
  if (!checkoutItems[prefix][index]) return;
  if (field === 'item_name') {
    checkoutItems[prefix][index].item_name = value;
  } else if (field === 'quantity') {
    checkoutItems[prefix][index].quantity = parseFloat(value) || 0;
  } else if (field === 'unit_price') {
    checkoutItems[prefix][index].unit_price = parseFloat(value) || 0;
  }
  syncCheckoutTotal(prefix);
}

function renderCheckoutItemsList(prefix) {
  const container = document.getElementById(`${prefix}ItemsList`);
  if (!container) return;
  const items = checkoutItems[prefix];
  if (items.length === 0) {
    container.innerHTML = `<div style="font-size:11px;color:var(--text-muted);font-style:italic;padding:4px 0;">No items added yet. Click "+ Add Item" or choose a quick preset above.</div>`;
    return;
  }
  container.innerHTML = items.map((item, idx) => `
    <div class="checkout-item-row">
      <input type="text" class="checkout-item-input" placeholder="Item name" value="${item.item_name}" oninput="updateCheckoutItem('${prefix}', ${idx}, 'item_name', this.value)">
      <input type="number" class="checkout-item-input" placeholder="Qty" min="0.1" step="any" value="${item.quantity}" oninput="updateCheckoutItem('${prefix}', ${idx}, 'quantity', this.value)">
      <input type="number" class="checkout-item-input" placeholder="Price ৳" min="0" step="any" value="${item.unit_price}" oninput="updateCheckoutItem('${prefix}', ${idx}, 'unit_price', this.value)">
      <button type="button" class="checkout-item-del-btn" onclick="removeCheckoutItemRow('${prefix}', ${idx})" title="Remove item">✕</button>
    </div>
  `).join('');
}

function syncCheckoutTotal(prefix) {
  const items = checkoutItems[prefix];
  const total = items.reduce((sum, itm) => sum + ((parseFloat(itm.quantity) || 0) * (parseFloat(itm.unit_price) || 0)), 0);
  const totalEl = document.getElementById(`${prefix}ItemsTotal`);
  if (totalEl) totalEl.textContent = `৳${fmt(total)}`;

  const amountInput = document.getElementById(prefix === 'payMerchant' ? 'payAmount' : 'fpPayAmount');
  if (amountInput) {
    if (items.length > 0) {
      amountInput.value = total.toFixed(2);
      amountInput.readOnly = true;
      amountInput.style.background = '#F3F4F6';
    } else {
      amountInput.readOnly = false;
      amountInput.style.background = '#fff';
    }
  }
}

async function doPayMerchant() {
  const selector = document.getElementById('paySourceSelector');
  const source = selector.dataset.source || 'NORMAL_WALLET';
  const fundId = selector.dataset.fundId;
  const fpId = selector.dataset.fpId;
  const merchant = state.selectedMerchant;
  if (!merchant) { showToast('error', 'No merchant selected'); return; }

  const items = checkoutItems.payMerchant;
  let amount = document.getElementById('payAmount').value;

  if (items.length > 0) {
    for (let itm of items) {
      if (!itm.item_name || !itm.item_name.trim()) {
        showToast('error', 'Please provide a name for all line items');
        return;
      }
      if (!itm.quantity || itm.quantity <= 0) {
        showToast('error', `Invalid quantity for item "${itm.item_name}"`);
        return;
      }
      if (itm.unit_price === undefined || itm.unit_price < 0) {
        showToast('error', `Invalid unit price for item "${itm.item_name}"`);
        return;
      }
    }
  } else {
    if (!amount || amount <= 0) { showToast('error', 'Enter a valid amount'); return; }
  }

  const payload = {
    merchant_id: merchant.id,
    payment_source: source,
    ...(fundId ? { purpose_fund_id: fundId } : {}),
    ...(fpId ? { family_pass_id: fpId } : {}),
    ...(items.length > 0 ? { items: items.map(it => ({
      item_name: it.item_name.trim(),
      quantity: it.quantity,
      unit_price: it.unit_price
    })) } : { amount })
  };

  const r = await apiPost('/api/pay/', payload);
  if (!r) return;
  if (r.ok) {
    showToast('success', r.data.message || 'Payment successful!');
    closeModal('payMerchantModal');
    checkoutItems.payMerchant = [];
    document.getElementById('payAmount').value = '';
    refreshFinancialState();
  } else {
    const err = r.data;
    if (err.is_category_mismatch) {
      showToast('error', `🚫 Category Restriction: Cannot pay ${merchant.category} merchant using this fund`, 6000);
    } else {
      showToast('error', err.error || 'Payment failed');
    }
  }
}

async function doCreateFamilyPass() {
  const member = document.getElementById('fpMember').value.trim();
  const limit = document.getElementById('fpLimit').value;
  const duration = document.getElementById('fpDuration').value;
  const purpose = document.getElementById('fpPurposeSelect') ? document.getElementById('fpPurposeSelect').value : 'Grocery';
  const customPurpose = document.getElementById('fpCustomPurpose') ? document.getElementById('fpCustomPurpose').value.trim() : '';

  if (!member) { showToast('error', 'Enter member phone or username'); return; }
  if (!limit || parseFloat(limit) <= 0) { showToast('error', 'Enter a valid spending limit greater than zero'); return; }

  const payload = {
    member,
    limit_amount: limit,
    duration_days: duration,
    purpose,
    custom_purpose: customPurpose
  };

  const r = await apiPost('/api/family-pass/', payload);
  if (!r) return;
  if (r.ok) {
    showToast('success', `✅ FamilyPass granted to ${member}!`);
    closeModal('createFPModal');
    document.getElementById('fpMember').value = '';
    document.getElementById('fpLimit').value = '';
    if (document.getElementById('fpCustomPurpose')) document.getElementById('fpCustomPurpose').value = '';
    loadFamilyPass();
  } else {
    showToast('error', r.data.error || 'Failed to create FamilyPass');
  }
}

let currentEditingPass = null;

async function openEditFPModal(id) {
  const passes = state.familyPasses.issued || [];
  let fp = passes.find(p => p.id === id);
  if (!fp) {
    const res = await apiGet(`/api/family-pass/${id}/`);
    if (res) fp = res;
  }
  if (!fp) {
    showToast('error', 'FamilyPass not found');
    return;
  }
  currentEditingPass = fp;

  document.getElementById('editFPId').value = fp.id;
  document.getElementById('editFPMemberName').textContent = `${fp.member_name || fp.member_username} (@${fp.member_username})`;
  document.getElementById('editFPUsedAmount').textContent = `৳${fmt(fp.used_amount)}`;
  document.getElementById('editFPCurrentLimit').textContent = `৳${fmt(fp.limit_amount)}`;
  document.getElementById('editFPLimit').value = fp.limit_amount;
  document.getElementById('editFPLimit').min = fp.used_amount;
  document.getElementById('editFPLimitHint').textContent = `Must be at least ৳${fmt(fp.used_amount)} (amount already spent)`;
  document.getElementById('editFPExpiryDate').value = fp.expiry_date || '';
  if (document.getElementById('editFPAction')) {
    document.getElementById('editFPAction').value = fp.allowed_action || 'MERCHANT_PAYMENT';
  }

  const pSel = document.getElementById('editFPPurposeSelect');
  if (pSel) {
    pSel.value = fp.purpose || 'Other';
    onFPPurposeSelectChange('edit');
    if (fp.purpose === 'Other') {
      document.getElementById('editFPCustomPurpose').value = fp.custom_purpose || '';
    }
  }

  openModal('editFPModal');
}

async function doSaveEditFamilyPass() {
  if (!currentEditingPass) return;
  const id = document.getElementById('editFPId').value;
  const limit = document.getElementById('editFPLimit').value;
  const purpose = document.getElementById('editFPPurposeSelect').value;
  const customPurpose = document.getElementById('editFPCustomPurpose').value.trim();
  const expiryDate = document.getElementById('editFPExpiryDate').value;
  const action = document.getElementById('editFPAction') ? document.getElementById('editFPAction').value : 'MERCHANT_PAYMENT';

  if (!limit || parseFloat(limit) <= 0) {
    showToast('error', 'Enter a valid spending limit greater than zero.');
    return;
  }

  const used = parseFloat(currentEditingPass.used_amount) || 0;
  if (parseFloat(limit) < used) {
    showToast('error', `New limit (৳${fmt(limit)}) cannot be lower than amount already spent (৳${fmt(used)}).`);
    return;
  }

  if (!expiryDate) {
    showToast('error', 'Please select an expiry date.');
    return;
  }

  // Confirmation before saving important permission changes
  if (!confirm(`Are you sure you want to save changes to this FamilyPass for ${currentEditingPass.member_name || currentEditingPass.member_username}?`)) {
    return;
  }

  const payload = {
    limit_amount: limit,
    expiry_date: expiryDate,
    purpose: purpose,
    custom_purpose: customPurpose,
    allowed_action: action
  };

  const r = await apiPatch(`/api/family-pass/${id}/`, payload);
  if (!r) return;
  if (r.ok) {
    showToast('success', 'FamilyPass updated successfully!');
    closeModal('editFPModal');
    loadFamilyPass();
  } else {
    showToast('error', r.data.error || 'Failed to update FamilyPass');
  }
}

async function revokeFP(id) {
  if (!confirm('Are you sure you want to revoke this FamilyPass? The recipient will immediately lose spending permission.')) return;
  const r = await apiPost(`/api/family-pass/${id}/revoke/`, {});
  if (!r) return;
  if (r.ok) {
    showToast('success', r.data.message || 'FamilyPass revoked successfully');
    loadFamilyPass();
    // If the logged in user was the member, recalculate their state
    if (state.user && state.user.id === r.data.member_id) {
      loadMe();
    }
  } else {
    showToast('error', r.data.error || 'Failed to revoke FamilyPass');
  }
}

async function viewFPActivity(id) {
  // Show modal immediately with loading indicator
  const summaryEl = document.getElementById('fpActivitySummary');
  const listEl = document.getElementById('fpActivityList');
  const badgeEl = document.getElementById('fpActivityCountBadge');

  if (summaryEl) summaryEl.innerHTML = `<div style="text-align:center;padding:20px;color:var(--text-muted);font-size:13px;">⏳ Loading FamilyPass details...</div>`;
  if (listEl) listEl.innerHTML = `<div style="text-align:center;padding:30px;color:var(--text-muted);font-size:13px;">⏳ Loading transactions & purchase records...</div>`;
  if (badgeEl) badgeEl.textContent = 'Loading...';

  openModal('fpActivityModal');

  const data = await apiGet(`/api/family-pass/${id}/activity/`);
  if (!data) {
    if (listEl) listEl.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">Failed to load activity</div><div class="empty-sub">Please check your connection and try again.</div></div>`;
    return;
  }

  const fp = data.family_pass;
  const activities = data.activities || data.transactions || [];

  if (badgeEl) badgeEl.textContent = `${activities.length} transaction${activities.length === 1 ? '' : 's'}`;

  // Render Summary
  const initials = (fp.member_name || fp.member_username || 'M').substring(0, 2).toUpperCase();
  const limit = parseFloat(fp.limit_amount) || 0;
  const used = parseFloat(fp.used_amount) || 0;
  const rem = parseFloat(fp.remaining_limit) || 0;
  const statusClass = { ACTIVE: 'fp-status-active', REVOKED: 'fp-status-revoked', EXPIRED: 'fp-status-expired' }[fp.status] || '';

  if (summaryEl) {
    summaryEl.innerHTML = `
      <div class="fp-act-header">
        <div class="fp-act-member">
          <div class="fp-act-avatar">${initials}</div>
          <div>
            <div class="fp-act-name">${fp.member_name || fp.member_username}</div>
            <div class="fp-act-purpose">${fp.purpose_label || 'Family Spending'}</div>
          </div>
        </div>
        <span class="fp-status-badge ${statusClass}">${fp.status}</span>
      </div>
      <div class="fp-act-stats">
        <div class="fp-act-stat">
          <span class="fp-act-stat-label">Total Limit</span>
          <span class="fp-act-stat-val">৳${fmt(limit)}</span>
        </div>
        <div class="fp-act-stat">
          <span class="fp-act-stat-label">Used</span>
          <span class="fp-act-stat-val" style="color:#DC2626;">৳${fmt(used)}</span>
        </div>
        <div class="fp-act-stat">
          <span class="fp-act-stat-label">Remaining</span>
          <span class="fp-act-stat-val" style="color:#059669;">৳${fmt(rem)}</span>
        </div>
        <div class="fp-act-stat">
          <span class="fp-act-stat-label">Expires</span>
          <span class="fp-act-stat-val">${fp.expiry_date || '---'}</span>
        </div>
      </div>
    `;
  }

  // Render Activities
  if (listEl) {
    if (activities.length === 0) {
      listEl.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">🧾</div>
          <div class="empty-title">No transactions recorded</div>
          <div class="empty-sub">${fp.member_name || 'Member'} has not made any purchases with this FamilyPass yet.</div>
        </div>`;
      return;
    }

    listEl.innerHTML = activities.map(act => {
      const dt = act.timestamp ? new Date(act.timestamp).toLocaleString('en-US', {
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit', hour12: true
      }) : '---';
      const merchantName = act.merchant_name || (act.merchant ? act.merchant.name : 'Merchant');
      const merchantLoc = act.merchant_location || (act.merchant ? act.merchant.location : '');
      const category = act.category || 'General';
      const icon = CATEGORY_ICONS[category] || '🏪';
      const hasItems = act.items && act.items.length > 0;
      const itemsCount = hasItems ? act.items.length : 0;
      const remAfter = act.remaining_limit_after !== undefined ? `Remaining after: ৳${fmt(act.remaining_limit_after)}` : '';

      let itemsHtml = '';
      if (hasItems) {
        const itemRows = act.items.map(it => `
          <tr>
            <td style="font-weight:600;">${it.item_name || it.name}</td>
            <td style="text-align:center;">${it.quantity}</td>
            <td style="text-align:right;">৳${fmt(it.unit_price)}</td>
            <td style="text-align:right;font-weight:700;">৳${fmt(it.line_total || it.total)}</td>
          </tr>
        `).join('');

        itemsHtml = `
          <div class="fp-txn-expandable" id="fp-txn-items-${act.id}" style="display:none;">
            <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;margin-bottom:6px;">Purchased Items (${itemsCount})</div>
            <table class="fp-items-table">
              <thead>
                <tr>
                  <th>Item</th>
                  <th style="text-align:center;">Qty</th>
                  <th style="text-align:right;">Unit Price</th>
                  <th style="text-align:right;">Total</th>
                </tr>
              </thead>
              <tbody>
                ${itemRows}
                <tr style="border-top:1.5px solid #D1D5DB;background:#F3F4F6;">
                  <td colspan="3" style="font-weight:700;text-align:right;">Subtotal:</td>
                  <td style="text-align:right;font-weight:800;color:#059669;">৳${fmt(act.amount)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        `;
      } else {
        itemsHtml = `
          <div class="fp-txn-expandable" id="fp-txn-items-${act.id}" style="display:none;">
            <div class="fp-no-items-notice">
              <span>ℹ️</span>
              <span>Item-level purchase details were not recorded for this transaction.</span>
            </div>
          </div>
        `;
      }

      return `
        <div class="fp-txn-card">
          <div class="fp-txn-top">
            <div style="display:flex;align-items:flex-start;gap:10px;">
              <div style="width:36px;height:36px;border-radius:10px;background:var(--primary-light);display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;">
                ${icon}
              </div>
              <div>
                <div class="fp-txn-merchant-title">${merchantName}</div>
                <div class="fp-txn-merchant-sub">
                  <span>${category}</span>
                  ${merchantLoc ? `<span>• 📍 ${merchantLoc}</span>` : ''}
                  <span>• 🕒 ${dt}</span>
                </div>
                <div style="font-size:11px;color:var(--text-muted);margin-top:2px;font-family:monospace;">
                  ID: ${act.transaction_id || act.reference || ('TXN-' + act.id)}
                </div>
              </div>
            </div>
            <div style="text-align:right;">
              <div class="fp-txn-amount">-৳${fmt(act.amount)}</div>
              ${remAfter ? `<div class="fp-txn-rem-badge">${remAfter}</div>` : ''}
            </div>
          </div>

          <div class="fp-txn-details-toggle" onclick="toggleTxnItems(${act.id})">
            <span class="fp-toggle-label" id="fp-toggle-btn-${act.id}">
              <span>${hasItems ? `▼ View Purchased Items (${itemsCount})` : '▼ View Details'}</span>
            </span>
            <span style="font-size:10px;color:var(--text-muted);text-transform:uppercase;font-weight:700;">
              ${act.status || 'COMPLETED'}
            </span>
          </div>

          ${itemsHtml}
        </div>
      `;
    }).join('');
  }
}

function toggleTxnItems(actId) {
  const el = document.getElementById(`fp-txn-items-${actId}`);
  const btn = document.getElementById(`fp-toggle-btn-${actId}`);
  if (!el) return;
  const isHidden = (el.style.display === 'none' || !el.style.display);
  el.style.display = isHidden ? 'block' : 'none';
  if (btn) {
    const text = btn.textContent;
    if (isHidden) {
      btn.innerHTML = text.replace('▼', '▲').replace('View', 'Hide');
    } else {
      btn.innerHTML = text.replace('▲', '▼').replace('Hide', 'View');
    }
  }
}

// ============================================================
// FAMILYPASS MEMBER PAYMENT
// ============================================================
function openFPMemberPay(fpId, ownerName, remaining) {
  state.selectedFamilyPass = { id: fpId, ownerName, remaining };
  document.getElementById('fpMemberPaySub').textContent = `Using FamilyPass from: ${ownerName}`;
  document.getElementById('fpPayLimitInfo').innerHTML = `<div style="font-size:12px;color:var(--primary-dark);">Remaining limit: <strong>৳${fmt(remaining)}</strong></div>`;
  populateFPMerchantSelect();

  // Initialize checkout item builder for FamilyPass
  checkoutItems.fpMember = [];
  const sel = document.getElementById('fpMerchantSelect');
  const merchantId = sel ? sel.value : null;
  const merchants = allMerchants.length > 0 ? allMerchants : state.merchants;
  const merchant = merchants.find(m => m.id == merchantId);
  renderCheckoutPresets('fpMember', merchant ? merchant.category : 'default');
  renderCheckoutItemsList('fpMember');
  syncCheckoutTotal('fpMember');
  document.getElementById('fpPayAmount').value = '';

  openModal('fpMemberPayModal');
}

function onFPMerchantSelectChange() {
  const sel = document.getElementById('fpMerchantSelect');
  const merchantId = sel ? sel.value : null;
  const merchants = allMerchants.length > 0 ? allMerchants : state.merchants;
  const merchant = merchants.find(m => m.id == merchantId);
  renderCheckoutPresets('fpMember', merchant ? merchant.category : 'default');
}

function populateFPMerchantSelect() {
  const el = document.getElementById('fpMerchantSelect');
  if (!el) return;
  const merchants = allMerchants.length > 0 ? allMerchants : state.merchants;
  el.innerHTML = merchants.map(m => `<option value="${m.id}">${CATEGORY_ICONS[m.category]||'🏪'} ${m.business_name} (${m.category})</option>`).join('');
}

async function doFPMemberPay() {
  const merchantId = document.getElementById('fpMerchantSelect').value;
  if (!merchantId) { showToast('error', 'Select a merchant'); return; }
  if (!state.selectedFamilyPass) { showToast('error', 'No FamilyPass selected'); return; }

  const items = checkoutItems.fpMember;
  let amount = document.getElementById('fpPayAmount').value;
  const remLimit = parseFloat(state.selectedFamilyPass.remaining_limit || state.selectedFamilyPass.remaining) || 0;

  if (items.length > 0) {
    for (let itm of items) {
      if (!itm.item_name || !itm.item_name.trim()) {
        showToast('error', 'Please provide a name for all line items');
        return;
      }
      if (!itm.quantity || itm.quantity <= 0) {
        showToast('error', `Invalid quantity for item "${itm.item_name}"`);
        return;
      }
      if (itm.unit_price === undefined || itm.unit_price < 0) {
        showToast('error', `Invalid unit price for item "${itm.item_name}"`);
        return;
      }
    }
    const total = items.reduce((s, it) => s + (it.quantity * it.unit_price), 0);
    if (total > remLimit) {
      showToast('error', `Spending exceeds remaining FamilyPass allowance (৳${fmt(remLimit)})`);
      return;
    }
  } else {
    if (!amount || amount <= 0) { showToast('error', 'Enter a valid amount'); return; }
    if (parseFloat(amount) > remLimit) {
      showToast('error', `Amount exceeds remaining FamilyPass allowance (৳${fmt(remLimit)})`);
      return;
    }
  }

  const payload = {
    merchant_id: merchantId,
    payment_source: 'FAMILY_PASS',
    family_pass_id: state.selectedFamilyPass.id,
    ...(items.length > 0 ? { items: items.map(it => ({
      item_name: it.item_name.trim(),
      quantity: it.quantity,
      unit_price: it.unit_price
    })) } : { amount })
  };

  const r = await apiPost('/api/pay/', payload);
  if (!r) return;
  if (r.ok) {
    showToast('success', r.data.message || 'FamilyPass payment successful!');
    closeModal('fpMemberPayModal');
    checkoutItems.fpMember = [];
    document.getElementById('fpPayAmount').value = '';
    refreshFinancialState();
  } else {
    showToast('error', r.data.error || 'Payment failed');
  }
}

// ============================================================
// GEMINI KEY MANAGEMENT
// ============================================================
async function saveGeminiKey() {
  const key = document.getElementById('geminiKeyInput').value.trim();
  if (!key) { showToast('error', 'Enter a valid API key'); return; }
  // Save to localStorage (in production, would save to server settings)
  localStorage.setItem('gemini_api_key', key);
  // Send to backend to update env
  const r = await apiPost('/api/ai/set-key/', { gemini_api_key: key });
  updateGeminiStatus(true);
  showToast('success', '✅ Gemini API key saved! AI responses now powered by Gemini 2.0 Flash');
  aiInitialized = false;
  initAiChat();
}

function updateGeminiStatus(active) {
  const el = document.getElementById('geminiKeyStatus');
  if (el) {
    el.textContent = active ? '✅ Gemini 2.0 Flash — Active' : 'Not configured — using offline AI';
    el.style.color = active ? 'var(--primary)' : '';
  }
}

// ============================================================
// SEED DATA
// ============================================================
async function doSeedData() {
  const r = await apiPost('/api/seed/', { wipe: true });
  if (!r) return;
  if (r.ok) {
    showToast('success', '✅ Demo data reset! Refreshing...');
    setTimeout(() => location.reload(), 2000);
  } else {
    showToast('error', r.data?.error || 'Failed to reset data');
  }
}

// ============================================================
// PROFILE / LOGOUT
// ============================================================
function showProfile() {
  navigateTo('more');
}

async function doLogout() {
  try {
    const csrfToken = getCsrfToken();
    const r = await fetch('/logout/', {
      method: 'GET',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrfToken }
    });
    window.location.href = '/login/';
  } catch (e) {
    window.location.href = '/login/';
  }
}

// ============================================================
// CONTACT BOOK
// ============================================================
async function loadContacts(query = '') {
  const url = query ? `/api/contacts/search/?q=${encodeURIComponent(query)}` : '/api/contacts/';
  const data = await apiGet(url);
  if (!data) return [];
  state.contacts = Array.isArray(data) ? data : [];
  return state.contacts;
}

function openContactBookModal() {
  loadContacts().then(() => {
    const searchInput = document.getElementById('contactBookSearch');
    if (searchInput) searchInput.value = '';
    renderContacts();
    openModal('contactBookModal');
  });
}

function filterContacts(query) {
  const q = query.toLowerCase().trim();
  if (!q) {
    renderContacts(state.contacts);
    return;
  }
  const filtered = state.contacts.filter(c => 
    (c.name && c.name.toLowerCase().includes(q)) ||
    (c.phone && c.phone.includes(q)) ||
    (c.username && c.username.toLowerCase().includes(q))
  );
  renderContacts(filtered);
}

function renderContacts(list = state.contacts) {
  const el = document.getElementById('contactBookList');
  if (!el) return;

  if (!list || list.length === 0) {
    el.innerHTML = `
      <div class="empty-state" style="padding:24px 12px;">
        <div class="empty-icon">📖</div>
        <div class="empty-title">No contacts found</div>
        <div class="empty-sub">Add friends and family to your personal contact book</div>
        <button class="btn-primary" style="max-width:180px;margin:8px auto 0;" onclick="openAddContactModal()">+ Add Contact</button>
      </div>`;
    return;
  }

  el.innerHTML = list.map(c => {
    const initial = (c.name || 'C').charAt(0).toUpperCase();
    const isReg = !!c.is_registered;
    const badge = isReg
      ? `<span class="contact-badge badge-registered">✓ FundShare account</span>`
      : `<span class="contact-badge badge-unregistered">Not registered</span>`;
    const userTag = c.username ? `<span style="font-size:11px;color:var(--text-muted);margin-left:4px;">(@${c.username})</span>` : '';

    return `
      <div class="contact-card">
        <div class="contact-main">
          <div class="contact-avatar">${initial}</div>
          <div class="contact-info">
            <div class="contact-name">${c.name} ${userTag}</div>
            <div class="contact-phone">${c.phone}</div>
            <div style="margin-top:2px;">${badge}</div>
          </div>
        </div>
        <div class="contact-actions-row">
          <div style="display:flex;gap:4px;flex-wrap:wrap;">
            <button class="contact-btn contact-btn-edit" onclick="openEditContactModal(${c.id})">✏️ Edit</button>
            <button class="contact-btn contact-btn-delete" onclick="doDeleteContact(${c.id}, '${c.name.replace(/'/g, "\\'")}')">🗑️ Delete</button>
          </div>
          <div style="display:flex;gap:4px;flex-wrap:wrap;">
            <button class="contact-btn" style="color:var(--primary);border-color:var(--primary);" title="Recharge Mobile" onclick="quickRechargeContact('${c.phone}')">📱 Recharge</button>
            ${isReg ? `<button class="contact-btn contact-btn-primary" title="Send Money" onclick="quickSendMoneyContact('${c.phone}')">📲 Send</button>` : `<button class="contact-btn contact-btn-disabled" disabled title="Send Money requires registered account">Send 🚫</button>`}
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function quickRechargeContact(phone) {
  closeModal('contactBookModal');
  const input = document.getElementById('rechargePhone');
  if (input) input.value = phone;
  openModal('rechargeModal');
}

function quickSendMoneyContact(phone) {
  closeModal('contactBookModal');
  const input = document.getElementById('sendReceiver');
  if (input) input.value = phone;
  openModal('sendMoneyModal');
}

function openAddContactModal() {
  closeModal('contactBookModal');
  document.getElementById('newContactName').value = '';
  document.getElementById('newContactPhone').value = '';
  document.getElementById('newContactUsername').value = '';
  openModal('addContactModal');
}

async function doCreateContact() {
  const name = document.getElementById('newContactName').value.trim();
  const phone = document.getElementById('newContactPhone').value.trim();
  const username = document.getElementById('newContactUsername').value.trim();

  if (!name) { showToast('error', 'Enter a contact name'); return; }
  if (!phone) { showToast('error', 'Enter a valid phone number'); return; }

  const r = await apiPost('/api/contacts/', { name, phone, username: username || undefined });
  if (!r) return;
  if (r.ok) {
    showToast('success', `✅ Contact "${name}" saved!`);
    closeModal('addContactModal');
    openContactBookModal();
  } else {
    showToast('error', r.data?.phone || r.data?.error || 'Failed to save contact');
  }
}

function openEditContactModal(id) {
  const c = state.contacts.find(x => x.id === id);
  if (!c) return;
  closeModal('contactBookModal');
  document.getElementById('editContactId').value = c.id;
  document.getElementById('editContactName').value = c.name || '';
  document.getElementById('editContactPhone').value = c.phone || '';
  document.getElementById('editContactUsername').value = c.username || '';
  openModal('editContactModal');
}

async function doUpdateContact() {
  const id = document.getElementById('editContactId').value;
  const name = document.getElementById('editContactName').value.trim();
  const phone = document.getElementById('editContactPhone').value.trim();
  const username = document.getElementById('editContactUsername').value.trim();

  if (!name) { showToast('error', 'Enter a contact name'); return; }
  if (!phone) { showToast('error', 'Enter a valid phone number'); return; }

  const r = await apiPatch(`/api/contacts/${id}/`, { name, phone, username: username || '' });
  if (!r) return;
  if (r.ok) {
    showToast('success', `✅ Contact "${name}" updated!`);
    closeModal('editContactModal');
    openContactBookModal();
  } else {
    showToast('error', r.data?.phone || r.data?.error || 'Failed to update contact');
  }
}

async function doDeleteContact(id, name) {
  if (!confirm(`Are you sure you want to remove "${name}" from your contacts?`)) return;
  const r = await apiDelete(`/api/contacts/${id}/`);
  if (!r) return;
  if (r.ok) {
    showToast('success', `Contact deleted`);
    await loadContacts();
    renderContacts();
  } else {
    showToast('error', r.data?.error || 'Failed to delete contact');
  }
}

// ============================================================
// REUSABLE CONTACT PICKER
// ============================================================
async function openContactPicker(config) {
  // config: { inputId, feature: 'send_money'|'mobile_recharge'|'fund_share'|'family_pass', title, returnModalId }
  state.pickerConfig = config;
  const titleEl = document.getElementById('contactPickerTitle');
  const subEl = document.getElementById('contactPickerSubtitle');
  const searchInput = document.getElementById('contactPickerSearch');

  if (titleEl) titleEl.textContent = config.title || '🔍 Select Contact';

  let subText = 'Choose a contact from your saved contacts';
  if (config.feature === 'mobile_recharge') {
    subText = '📱 Select any contact — FundShare account not required for recharge';
  } else if (config.feature === 'send_money') {
    subText = '📤 Select a recipient — requires a registered FundShare account';
  } else if (config.feature === 'fund_share') {
    subText = '🎯 Select fund recipient — requires a registered FundShare account';
  } else if (config.feature === 'family_pass') {
    subText = '👨‍👩‍👧 Select family member — requires a registered FundShare account';
  }
  if (subEl) subEl.textContent = subText;
  if (searchInput) searchInput.value = '';

  if (config.returnModalId) {
    closeModal(config.returnModalId);
  }

  await loadContacts();
  renderPickerList();
  openModal('contactPickerModal');
}

function closeContactPicker() {
  closeModal('contactPickerModal');
  if (state.pickerConfig && state.pickerConfig.returnModalId) {
    openModal(state.pickerConfig.returnModalId);
  }
  state.pickerConfig = null;
}

function filterPickerContacts(query) {
  const q = query.toLowerCase().trim();
  if (!q) {
    renderPickerList(state.contacts);
    return;
  }
  const filtered = state.contacts.filter(c =>
    (c.name && c.name.toLowerCase().includes(q)) ||
    (c.phone && c.phone.includes(q)) ||
    (c.username && c.username.toLowerCase().includes(q))
  );
  renderPickerList(filtered);
}

function renderPickerList(list = state.contacts) {
  const el = document.getElementById('contactPickerList');
  if (!el) return;

  const feature = state.pickerConfig ? state.pickerConfig.feature : 'general';
  const allowsUnregistered = (feature === 'mobile_recharge');

  if (!list || list.length === 0) {
    el.innerHTML = `
      <div class="empty-state" style="padding:20px 10px;">
        <div class="empty-icon">📖</div>
        <div class="empty-title">No contacts available</div>
        <div class="empty-sub">Save contacts in your Contact Book to quickly pick them here</div>
      </div>`;
    return;
  }

  el.innerHTML = list.map(c => {
    const initial = (c.name || 'C').charAt(0).toUpperCase();
    const isReg = !!c.is_registered;
    const isSelectable = allowsUnregistered || isReg;

    const badge = isReg
      ? `<span class="contact-badge badge-registered">✓ FundShare account</span>`
      : `<span class="contact-badge badge-unregistered">Not registered</span>`;

    let buttonHtml = '';
    if (isSelectable) {
      buttonHtml = `<button class="contact-btn contact-btn-primary" onclick="selectPickerContact('${c.phone}', '${(c.username || '').replace(/'/g, "\\'")}', '${c.name.replace(/'/g, "\\'")}')">Select</button>`;
    } else {
      buttonHtml = `<button class="contact-btn contact-btn-disabled" disabled title="Account not registered for this feature">Unavailable</button>`;
    }

    const featureNote = (!allowsUnregistered && !isReg)
      ? `<div style="font-size:10.5px;color:var(--danger);margin-top:3px;">⚠️ Send Money / FundShare requires a registered account</div>`
      : '';

    return `
      <div class="contact-card" style="opacity:${isSelectable ? '1' : '0.65'}">
        <div class="contact-main">
          <div class="contact-avatar" style="background:${isReg ? 'var(--primary-light)' : '#F3F4F6'};color:${isReg ? 'var(--primary-dark)' : '#6B7280'}">${initial}</div>
          <div class="contact-info">
            <div class="contact-name">${c.name} ${c.username ? `<span style="font-size:11px;color:var(--text-muted);">(@${c.username})</span>` : ''}</div>
            <div class="contact-phone">${c.phone}</div>
            <div style="margin-top:2px;">${badge}</div>
            ${featureNote}
          </div>
          <div>${buttonHtml}</div>
        </div>
      </div>
    `;
  }).join('');
}

function selectPickerContact(phone, username, name) {
  if (!state.pickerConfig) return;
  const input = document.getElementById(state.pickerConfig.inputId);
  if (input) {
    input.value = phone;
  }
  showToast('info', `Selected ${name} (${phone})`, 2500);
  closeContactPicker();
}

// ============================================================
// INIT ON DOM READY
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  initApp();
});
