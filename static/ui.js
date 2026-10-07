const receiptTransactions = new Map();
const modalReturnFocus = new Map();
let balanceHidden = false;
let latestWalletSummary = null;
let historyMode = 'details';
const categoryIconNames = { Grocery: 'shopping-basket', Medicine: 'pill', Treatment: 'hospital', Education: 'graduation-cap', Electricity: 'zap', 'Restaurant/Food': 'utensils', Transport: 'car', Rent: 'house', Shopping: 'shopping-bag', Other: 'package' };

function iconElement(name, attributes = {}) {
  const key = name.replace(/(^|-)([a-z0-9])/g, (_, __, letter) => letter.toUpperCase());
  const node = lucide.icons[key] || lucide.icons.Circle;
  return lucide.createElement(node, { class: 'lucide', 'aria-hidden': 'true', ...attributes });
}

function iconMarkup(name) { return iconElement(name).outerHTML; }

function refreshUIIcons() {
  document.querySelectorAll('i[data-lucide]').forEach(node => {
    const icon = iconElement(node.dataset.lucide);
    if (node.className) icon.setAttribute('class', 'lucide ' + node.className);
    node.replaceWith(icon);
  });
  const prefix = /^(?:[\p{Extended_Pictographic}\u200d\ufe0f\u20e3]|[⇄➤➕✕✏⚠✅❌→›])+\s*/u;
  const names = [
    ['👨', 'users-round'], ['👥', 'users-round'], ['📤', 'send'], ['📲', 'send'],
    ['📱', 'smartphone'], ['💳', 'credit-card'], ['💡', 'lightbulb'], ['🏧', 'banknote'],
    ['📋', 'receipt-text'], ['📖', 'contact-round'], ['🎯', 'target'], ['📊', 'chart-no-axes-combined'],
    ['🛒', 'shopping-basket'], ['💊', 'pill'], ['🏥', 'hospital'], ['🎓', 'graduation-cap'],
    ['⚡', 'zap'], ['🍽', 'utensils'], ['🚗', 'car'], ['🏠', 'house'], ['🛍', 'shopping-bag'],
    ['📦', 'package'], ['🏪', 'store'], ['🔔', 'bell'], ['🤖', 'sparkles'], ['👤', 'user-round'], ['🎁', 'users-round'], ['💰', 'wallet'], ['📚', 'graduation-cap'], ['🚌', 'bus'],
    ['🔍', 'search'], ['🔑', 'lock-keyhole'], ['🔒', 'lock-keyhole'], ['✏', 'pencil'],
    ['🗑', 'trash-2'], ['📅', 'calendar-days'], ['📆', 'calendar-days'], ['🔄', 'refresh-cw'],
    ['🛡', 'shield-check'], ['⚠', 'circle-alert'], ['🚫', 'ban'], ['✅', 'circle-check'],
    ['❌', 'circle-x'], ['ℹ', 'info'], ['↑', 'arrow-down-left'], ['⬆', 'arrow-down-left'],
    ['⇄', 'arrow-right-left'], ['➕', 'plus'], ['➤', 'send'], ['✕', 'x'], ['→', 'arrow-right'], ['›', 'chevron-right'],
  ];
  const selector = '.empty-icon,.fund-icon,.txn-icon,.source-name,.modal-title,.settings-item-icon,.ai-prompt-chip,.fund-action-btn,.fp-action-btn,.fp-purpose-badge,.checkout-item-del-btn,.card-title,.contact-btn,.input-action-btn,.btn-primary,.btn-secondary,.notif-panel-close,.chat-send-btn,.pill,.bar-label';
  document.querySelectorAll(selector).forEach(element => {
    const text = [...element.childNodes].find(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
    if (!text) return;
    const value = text.textContent.trimStart();
    const match = value.match(prefix);
    if (!match) return;
    const name = names.find(([symbol]) => match[0].includes(symbol))?.[1] || 'circle';
    const remainder = value.slice(match[0].length);
    text.textContent = remainder ? ' ' + remainder : '';
    element.insertBefore(iconElement(name), text);
  });
  document.querySelectorAll('select option').forEach(option => {
    const clean = option.textContent.replace(prefix, '');
    if (clean !== option.textContent) option.textContent = clean;
  });
  document.querySelectorAll('.source-selector').forEach(group => {
    group.setAttribute('role', 'radiogroup');
    group.setAttribute('aria-label', 'Payment source');
    group.querySelectorAll('.source-option').forEach(option => {
      const enabled = option.hasAttribute('onclick');
      const selected = option.classList.contains('selected');
      option.setAttribute('role', 'radio');
      option.setAttribute('aria-checked', String(selected));
      option.setAttribute('aria-disabled', String(!enabled));
      option.tabIndex = enabled && selected ? 0 : -1;
    });
  });
}

function renderLoading(id, label = 'Loading') {
  const element = document.getElementById(id);
  if (element) {
    element.setAttribute('aria-busy', 'true');
    element.innerHTML = `<div class="loading-state" role="status"><span class="spinner"></span>${escapeHtml(label)}</div>`;
  }
}

function renderLoadError(id, retry) {
  const element = document.getElementById(id);
  if (element) {
    element.removeAttribute('aria-busy');
    element.innerHTML = `<div class="load-error" role="alert">Unable to load this information.<br><button class="btn-secondary" onclick="${retry}">${iconMarkup('refresh-cw')} Try Again</button></div>`;
  }
}

function renderAccountIdentity() {
  const user = state.user;
  if (!user) return;
  const name = user.full_name || user.username || 'Customer';
  document.getElementById('profileName').textContent = name;
  document.getElementById('profilePhone').textContent = user.phone || 'No phone number';
  document.getElementById('profileAvatar').textContent = name.slice(0, 2).toUpperCase();
  document.getElementById('headerPhone').textContent = user.phone || 'FundShare Account';
}

function renderWalletOverview(data) {
  latestWalletSummary = data;
  const amount = value => balanceHidden ? '••••' : '৳' + fmt(value);
  document.getElementById('walletBalance').textContent = balanceHidden ? '••••' : fmt(data.wallet_balance);
  document.getElementById('balanceSub').textContent = balanceHidden ? 'Balance is hidden' : `Wallet & funds: ৳${fmt(data.total_liquid_wealth)}`;
  document.getElementById('overviewFunds').textContent = amount(data.funds_total_balance);
  document.getElementById('overviewWealth').textContent = amount(data.total_liquid_wealth);
  document.getElementById('accountWalletBalance').textContent = amount(data.wallet_balance);
  document.getElementById('accountFundsBalance').textContent = amount(data.funds_total_balance);
}

function toggleBalanceVisibility() {
  balanceHidden = !balanceHidden;
  const button = document.getElementById('balanceVisibility');
  button.setAttribute('aria-pressed', String(balanceHidden));
  button.title = balanceHidden ? 'Show balance' : 'Hide balance';
  button.setAttribute('aria-label', button.title);
  button.innerHTML = iconMarkup(balanceHidden ? 'eye-off' : 'eye');
  if (latestWalletSummary) renderWalletOverview(latestWalletSummary);
}

async function loadAccount() {
  renderAccountIdentity();
  if (state.user?.effective_role !== 'MERCHANT') {
    await Promise.all([loadDashboard(), loadReport('monthly')]);
  }
}

function setHistoryMode(mode) {
  historyMode = mode;
  document.getElementById('historyDetailsButton').classList.toggle('active', mode === 'details');
  document.getElementById('historySummaryButton').classList.toggle('active', mode === 'summary');
  document.getElementById('fullTxnList').hidden = mode === 'summary';
  document.getElementById('historySummary').hidden = mode !== 'summary';
  renderHistorySummary();
}

function renderHistorySummary() {
  const transactions = state.historyTransactions || [];
  let received = 0, spent = 0, passSpending = 0;
  transactions.filter(txn => txn.status === 'COMPLETED').forEach(txn => {
    if (txn.transaction_type === 'FUND_TRANSFER') return;
    const value = Number(txn.amount) || 0;
    const incoming = txn.transaction_type === 'CASH_IN' || (txn.receiver === state.user?.id && txn.sender !== state.user?.id);
    const usingPass = txn.payment_source === 'FAMILY_PASS' && txn.sender === state.user?.id;
    if (usingPass) passSpending += value;
    else if (incoming) received += value;
    else spent += value;
  });
  document.getElementById('historySummary').innerHTML = `<div class="history-summary-grid"><div class="history-summary-stat">Money Received<strong>৳${fmt(received)}</strong></div><div class="history-summary-stat">Money Spent / Allocated<strong>৳${fmt(spent)}</strong></div><div class="history-summary-stat">Received FamilyPass Spending<strong>৳${fmt(passSpending)}</strong></div></div><p class="history-summary-note">${transactions.length} loaded transactions in this filter. Successful transactions only; received FamilyPass spending is separate from your own wallet. This is not a full account statement.</p>`;
}

function openTransactionDetails(id) {
  const txn = receiptTransactions.get(id);
  if (!txn) return;
  const source = txn.payment_source === 'FAMILY_PASS' ? 'FamilyPass' : txn.purpose_fund_name || 'Primary Wallet';
  const fields = [
    ['Transaction ID', txn.transaction_id], ['Status', txn.status],
    ['Type', TXN_TYPE_LABELS[txn.transaction_type] || txn.transaction_type],
    ['Date & Time', fmtDate(txn.timestamp)], ['Payment Source', source],
    ['Merchant / Recipient', txn.merchant_name || txn.receiver_name], ['Reference', txn.reference],
  ].filter(([, value]) => value);
  const items = txn.items || [];
  document.getElementById('transactionDetailsContent').innerHTML = `<div class="receipt-total">৳${fmt(txn.amount)}</div><dl class="receipt-list">${fields.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join('')}</dl>${txn.rejection_reason ? `<div class="load-error">${escapeHtml(txn.rejection_reason)}</div>` : ''}${items.length ? `<h3 class="receipt-items-heading">Purchased Items</h3><table class="fp-items-table"><thead><tr><th>Item</th><th>Qty</th><th>Total</th></tr></thead><tbody>${items.map(item => `<tr><td>${escapeHtml(item.name || item.item_name)}</td><td>${escapeHtml(item.quantity)}</td><td>৳${fmt(item.line_total)}</td></tr>`).join('')}</tbody></table>` : ''}`;
  openModal('transactionDetailsModal');
}

function initializePresentation() {
  refreshUIIcons();
  document.querySelectorAll('.input-action-btn').forEach(button => button.setAttribute('aria-label', button.title || 'Choose Contact'));
  const sendButton = document.getElementById('sendBtn');
  sendButton.title = 'Send Message';
  sendButton.setAttribute('aria-label', 'Send Message');
  document.getElementById('chatInput').setAttribute('aria-label', 'Financial question');
  let scheduled = false;
  new MutationObserver(() => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => { scheduled = false; refreshUIIcons(); });
  }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
  document.querySelectorAll('.form-label').forEach(label => {
    const field = label.parentElement.querySelector('input[id],select[id]');
    if (field && !label.htmlFor) label.htmlFor = field.id;
  });
  document.querySelectorAll('.modal-overlay').forEach(modal => {
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    const title = modal.querySelector('.modal-title');
    if (title) {
      title.id ||= modal.id + 'Title';
      modal.setAttribute('aria-labelledby', title.id);
    }
    const close = document.createElement('button');
    close.className = 'modal-dismiss';
    close.type = 'button';
    close.title = 'Close';
    close.setAttribute('aria-label', 'Close');
    close.innerHTML = iconMarkup('x');
    close.addEventListener('click', () => modal.id === 'contactPickerModal' ? closeContactPicker() : closeModal(modal.id));
    modal.querySelector('.modal-sheet')?.appendChild(close);
  });
  document.addEventListener('keydown', event => {
    if (document.getElementById('transactionPinDialog').open) return;
    const source = event.target.closest('.source-option[role="radio"][aria-disabled="false"]');
    if (source && ['Enter', ' ', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(event.key)) {
      event.preventDefault();
      let next = source;
      if (event.key.startsWith('Arrow')) {
        const options = [...source.parentElement.querySelectorAll('.source-option[aria-disabled="false"]')];
        const direction = ['ArrowUp', 'ArrowLeft'].includes(event.key) ? -1 : 1;
        next = options[(options.indexOf(source) + direction + options.length) % options.length];
      }
      next.click();
      next.focus();
      return;
    }
    const notifications = document.getElementById('notifPanel');
    const modal = notifications.classList.contains('open') ? notifications : [...document.querySelectorAll('.modal-overlay.show')].at(-1);
    if (!modal) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      if (modal.id === 'notifPanel') closeNotifications();
      else modal.id === 'contactPickerModal' ? closeContactPicker() : closeModal(modal.id);
    } else if (event.key === 'Tab') {
      const focusable = [...modal.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),a[href],[tabindex="0"]')].filter(node => node.getClientRects().length);
      const first = focusable[0], last = focusable.at(-1);
      if (event.shiftKey && (document.activeElement === first || !modal.contains(document.activeElement))) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !modal.contains(document.activeElement))) { event.preventDefault(); first?.focus(); }
    }
  });
}

document.addEventListener('DOMContentLoaded', initializePresentation);
