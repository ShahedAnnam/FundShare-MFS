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
  ai: 'ai', more: 'more', history: 'more'
};

function navigateTo(tab) {
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
  const role = state.user?.role;
  // Show/hide nav items based on role
  const fundsNav = document.getElementById('nav-funds');
  const fpNav = document.getElementById('nav-familypass');

  if (role === 'MERCHANT') {
    // Merchant: hide funds and familypass nav
    if (fundsNav) fundsNav.style.display = 'none';
    if (fpNav) fpNav.style.display = 'none';
  } else if (role === 'MEMBER') {
    // Member: show familypass but no fund creation
    if (fundsNav) fundsNav.style.display = 'none';
  }

  // Role badge on profile
  const roleBadge = document.getElementById('profileRoleBadge');
  if (roleBadge) {
    const labels = { CUSTOMER: '👤 Customer', MEMBER: '👥 FamilyPass Member', MERCHANT: '🏪 Merchant', ADMIN: '🔑 Admin' };
    roleBadge.textContent = labels[role] || role;
  }

  // FamilyPass view switching
  if (role === 'MEMBER') {
    const ov = document.getElementById('fpOwnerView');
    const mv = document.getElementById('fpMemberView');
    if (ov) ov.style.display = 'none';
    if (mv) mv.style.display = 'block';
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

function renderRecentTxns(txns) {
  const el = document.getElementById('recentTxns');
  if (!txns || txns.length === 0) {
    el.innerHTML = '<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-title">No transactions yet</div></div>';
    return;
  }
  el.innerHTML = txns.slice(0, 6).map(t => {
    const isCredit = t.transaction_type === 'CASH_IN';
    const icon = isCredit ? '⬆️' : (TXN_TYPE_LABELS[t.transaction_type] ? '⬇️' : '💳');
    const label = t.merchant_name || t.receiver_name || TXN_TYPE_LABELS[t.transaction_type] || t.transaction_type;
    const statusBadge = t.status === 'REJECTED' ? `<span class="pill pill-red" style="font-size:9px;">REJECTED</span>` : '';
    return `<div class="txn-item">
      <div class="txn-icon ${isCredit ? 'credit' : 'debit'}">${CATEGORY_ICONS[t.category] || (isCredit ? '💚' : '💸')}</div>
      <div class="txn-info">
        <div class="txn-name">${label} ${statusBadge}</div>
        <div class="txn-meta">${TXN_TYPE_LABELS[t.transaction_type] || t.transaction_type} • ${timeAgo(t.timestamp)}</div>
      </div>
      <div class="txn-amount ${isCredit ? 'credit' : 'debit'}">${isCredit ? '+' : '-'}৳${fmt(t.amount)}</div>
    </div>`;
  }).join('');
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
    return `<div class="fund-card" style="border-left-color:${color};">
      <div class="fund-header">
        <div class="fund-name-row">
          <div class="fund-icon" style="background:${color}22;">${icon}</div>
          <div>
            <div class="fund-name">${f.name}</div>
            <div class="fund-category">${f.category} • ${pct.toFixed(0)}% used</div>
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
    html += `<div class="source-option" onclick="selectSource(this,'FAMILY_PASS',${fp.id})">
      <span class="source-radio"></span>
      <div class="source-info">
        <div class="source-name">👨‍👩‍👧 FamilyPass from ${fp.owner_name || 'Owner'}</div>
        <div class="source-balance">Remaining: ৳${fmt(fp.remaining_limit)}</div>
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
// FAMILYPASS
// ============================================================
async function loadFamilyPass() {
  const data = await apiGet('/api/family-pass/');
  if (!data) return;
  state.familyPasses = { issued: data.issued_passes || [], received: data.received_passes || [] };
  renderFamilyPass();
}

function renderFamilyPass() {
  const role = state.user?.role;
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
    return `<div class="fp-card">
      <div class="fp-header">
        <div class="fp-member">
          <div class="fp-avatar">${initials}</div>
          <div>
            <div class="fp-member-name">${fp.member_name || fp.member_username}</div>
            <div class="fp-member-phone">${fp.purpose_label || 'Family Spending'}</div>
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
          <span class="fp-meta-value">${fp.allowed_action || 'Pay'}</span>
          <span class="fp-meta-label">Action</span>
        </div>
      </div>
      ${fp.status === 'ACTIVE' ? `<div class="fp-actions">
        <button class="fp-action-btn fp-action-revoke" onclick="revokeFP(${fp.id})">🚫 Revoke</button>
        <button class="fp-action-btn fp-action-view" onclick="viewFPActivity(${fp.id})">📋 View Activity</button>
      </div>` : ''}
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
    return `<div class="received-fp-card">
      <div class="rfp-owner">From: ${fp.owner_name || fp.owner_username}</div>
      <div class="rfp-limit">৳${fmt(limit)}</div>
      <div class="rfp-limit-label">Total Spending Limit</div>
      <div class="rfp-remaining">৳${fmt(rem)} remaining</div>
      <div class="rfp-expiry">Expires: ${fp.expiry_date || '---'} • ${fp.purpose_label || 'General'}</div>
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
        <div class="report-stat-val">${stats.savings_rate ? (stats.savings_rate * 100).toFixed(1) + '%' : 'N/A'}</div>
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
    loadDashboard();
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
    loadDashboard();
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
    loadDashboard();
  } else {
    showToast('error', r.data.error || 'Transaction failed');
  }
}

async function doCreateFund() {
  const name = document.getElementById('fundName').value.trim();
  const category = document.getElementById('fundCategory').value;
  const allocation = document.getElementById('fundAllocation').value;
  const budget = document.getElementById('fundBudget').value;
  if (!name) { showToast('error', 'Enter a fund name'); return; }
  if (!category) { showToast('error', 'Select a category'); return; }
  const r = await apiPost('/api/funds/', {
    name, category,
    allocated_amount: allocation || '0',
    monthly_budget: budget || allocation || '0'
  });
  if (!r) return;
  if (r.ok) {
    showToast('success', `✅ ${name} Fund created!`);
    closeModal('createFundModal');
    document.getElementById('fundName').value = '';
    document.getElementById('fundCategory').value = '';
    document.getElementById('fundAllocation').value = '';
    document.getElementById('fundBudget').value = '';
    loadFunds();
    loadDashboard();
  } else {
    showToast('error', r.data.error || 'Failed to create fund');
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
    loadFunds();
  } else {
    showToast('error', r.data.error || 'Transfer failed');
  }
}

async function doPayMerchant() {
  const amount = document.getElementById('payAmount').value;
  const selector = document.getElementById('paySourceSelector');
  const source = selector.dataset.source || 'NORMAL_WALLET';
  const fundId = selector.dataset.fundId;
  const fpId = selector.dataset.fpId;
  const merchant = state.selectedMerchant;
  if (!merchant) { showToast('error', 'No merchant selected'); return; }
  if (!amount || amount <= 0) { showToast('error', 'Enter a valid amount'); return; }

  const payload = {
    merchant_id: merchant.id,
    amount,
    payment_source: source,
    ...(fundId ? { purpose_fund_id: fundId } : {}),
    ...(fpId ? { family_pass_id: fpId } : {})
  };

  const r = await apiPost('/api/pay/', payload);
  if (!r) return;
  if (r.ok) {
    showToast('success', r.data.message || 'Payment successful!');
    closeModal('payMerchantModal');
    document.getElementById('payAmount').value = '';
    loadDashboard();
    if (state.currentTab === 'funds') loadFunds();
  } else {
    const err = r.data;
    if (err.is_category_mismatch) {
      showToast('error', `🚫 Category Restriction: Cannot pay ${merchant.category} merchant using this fund`, 6000);
    } else if (err.is_family_pass_error) {
      showToast('error', `🚫 FamilyPass Error: ${err.error}`, 6000);
    } else {
      showToast('error', err.error || 'Payment failed');
    }
  }
}

async function doCreateFamilyPass() {
  const member = document.getElementById('fpMember').value;
  const limit = document.getElementById('fpLimit').value;
  const duration = document.getElementById('fpDuration').value;
  const purpose = document.getElementById('fpPurpose').value;
  if (!member) { showToast('error', 'Enter member phone or username'); return; }
  if (!limit || limit <= 0) { showToast('error', 'Enter a valid spending limit'); return; }
  const r = await apiPost('/api/family-pass/', {
    member, limit_amount: limit, duration_days: duration,
    purpose_label: purpose || 'Family Spending'
  });
  if (!r) return;
  if (r.ok) {
    showToast('success', `✅ FamilyPass granted to ${member}!`);
    closeModal('createFPModal');
    document.getElementById('fpMember').value = '';
    document.getElementById('fpLimit').value = '';
    document.getElementById('fpPurpose').value = '';
    loadFamilyPass();
  } else {
    showToast('error', r.data.error || 'Failed to create FamilyPass');
  }
}

async function revokeFP(id) {
  if (!confirm('Revoke this FamilyPass? This cannot be undone.')) return;
  const r = await apiPost(`/api/family-pass/${id}/revoke/`, {});
  if (!r) return;
  if (r.ok) {
    showToast('success', 'FamilyPass revoked successfully');
    loadFamilyPass();
  } else {
    showToast('error', r.data.error || 'Failed to revoke');
  }
}

async function viewFPActivity(id) {
  const data = await apiGet(`/api/family-pass/${id}/activity/`);
  if (!data) return;
  const fp = data.family_pass;
  const activities = data.activities || [];
  showToast('info', `📋 ${fp.member_name || 'Member'}: ${activities.length} transaction(s) recorded`);
}

// ============================================================
// FAMILYPASS MEMBER PAYMENT
// ============================================================
function openFPMemberPay(fpId, ownerName, remaining) {
  state.selectedFamilyPass = { id: fpId, ownerName, remaining };
  document.getElementById('fpMemberPaySub').textContent = `Using FamilyPass from: ${ownerName}`;
  document.getElementById('fpPayLimitInfo').innerHTML = `<div style="font-size:12px;color:var(--primary-dark);">Remaining limit: <strong>৳${fmt(remaining)}</strong></div>`;
  populateFPMerchantSelect();
  openModal('fpMemberPayModal');
}

function populateFPMerchantSelect() {
  const el = document.getElementById('fpMerchantSelect');
  if (!el) return;
  const merchants = allMerchants.length > 0 ? allMerchants : state.merchants;
  el.innerHTML = merchants.map(m => `<option value="${m.id}">${CATEGORY_ICONS[m.category]||'🏪'} ${m.business_name} (${m.category})</option>`).join('');
}

async function doFPMemberPay() {
  const merchantId = document.getElementById('fpMerchantSelect').value;
  const amount = document.getElementById('fpPayAmount').value;
  if (!merchantId) { showToast('error', 'Select a merchant'); return; }
  if (!amount || amount <= 0) { showToast('error', 'Enter a valid amount'); return; }
  if (!state.selectedFamilyPass) { showToast('error', 'No FamilyPass selected'); return; }
  const r = await apiPost('/api/pay/', {
    merchant_id: merchantId,
    amount,
    payment_source: 'FAMILY_PASS',
    family_pass_id: state.selectedFamilyPass.id
  });
  if (!r) return;
  if (r.ok) {
    showToast('success', r.data.message || 'FamilyPass payment successful!');
    closeModal('fpMemberPayModal');
    document.getElementById('fpPayAmount').value = '';
    loadFamilyPass();
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
// INIT ON DOM READY
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  initApp();
});
