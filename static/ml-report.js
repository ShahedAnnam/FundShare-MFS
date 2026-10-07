// Loaded only in authenticated ADMIN pages; the API independently enforces access.
let mlPage = 1;
let mlRequestVersion = 0;
const mlMetric = value => typeof value === 'number' ? value.toFixed(3) : 'N/A';

function openMLReport() {
  document.getElementById('evalSection')?.scrollIntoView({behavior: 'smooth', block: 'start'});
}

async function loadMLReport(page = 1) {
  if (state.user?.role !== 'ADMIN' || !document.getElementById('mlReport')) return;
  const version = ++mlRequestVersion;
  const report = document.getElementById('mlReport');
  const previous = document.getElementById('mlPrev');
  const next = document.getElementById('mlNext');
  previous.disabled = next.disabled = true;
  renderLoading('mlReport', 'Loading transaction predictions');
  const params = new URLSearchParams({page, prediction: document.getElementById('mlPrediction').value,
    type: document.getElementById('mlType').value, search: document.getElementById('mlSearch').value.trim()});
  const data = await apiGet(`/api/admin/ml/transactions/?${params}`);
  if (version !== mlRequestVersion) return;
  report.removeAttribute('aria-busy');
  if (!data || !Array.isArray(data.results)) {
    document.getElementById('mlPageLabel').textContent = 'Report unavailable';
    renderLoadError('mlReport', `loadMLReport(${page})`);
    return;
  }
  mlPage = page;
  const model = data.model || {};
  const summary = data.summary || {};
  document.getElementById('evalMetrics').innerHTML = [
    ['Precision', model.precision], ['Recall', model.recall], ['F1-score', model.f1], ['ROC-AUC', model.roc_auc]
  ].map(([label, value]) => `<div class="metric-card"><div class="metric-value">${mlMetric(value)}</div><div class="metric-label">${label}</div><div class="metric-sub">Held-out evaluation</div></div>`).join('');
  document.getElementById('evalDetailsCard').innerHTML = model.available ? `
    <div class="ml-model-title"><i data-lucide="scan-line"></i><strong>${escapeHtml(model.algorithm)}</strong><code>${escapeHtml(model.model_version)}</code></div>
    <p>${model.train_size} training / ${model.test_size} evaluation transactions &middot; ${model.sample_size} dataset rows</p>
    <p class="ml-caution">${escapeHtml(model.limitations)}</p>
    <details><summary>Evaluation details</summary><dl class="ml-details-grid">
      <dt>Split</dt><dd>${escapeHtml(model.split)}</dd><dt>Training ends</dt><dd>${escapeHtml(model.training_end)}</dd>
      <dt>Evaluation period</dt><dd>${escapeHtml(model.test_start)} to ${escapeHtml(model.test_end)}</dd>
      <dt>Labels</dt><dd>${escapeHtml(model.label_usage)}</dd><dt>Scoring</dt><dd>${escapeHtml(model.score_definition)}</dd>
      <dt>Confusion matrix</dt><dd>${escapeHtml(JSON.stringify(model.confusion_matrix))} (rows: actual 0/1; columns: predicted 0/1)</dd>
      <dt>Configuration</dt><dd>Contamination ${model.contamination}; seed ${model.random_state}; scikit-learn ${escapeHtml(model.sklearn_version)}</dd>
      <dt>Dataset SHA-256</dt><dd><code>${escapeHtml(model.dataset_sha256)}</code></dd>
    </dl></details>` : `<p class="ml-caution">${escapeHtml(model.message || 'Model unavailable. Predictions require backfill after recovery.')}</p>`;
  document.getElementById('mlSummary').innerHTML = `<span><strong>${summary.total ?? 0}</strong> Transactions</span><span class="ml-normal"><strong>${summary.normal ?? 0}</strong> Normal</span><span class="ml-anomaly"><strong>${summary.anomaly ?? 0}</strong> Anomaly</span><span><strong>${summary.unscored ?? 0}</strong> Unscored</span>`;
  const typeSelect = document.getElementById('mlType');
  if (typeSelect.options.length === 1) {
    (data.transaction_types || []).forEach(type => typeSelect.add(new Option(type.replaceAll('_', ' '), type)));
  }
  if (!data.results.length) {
    report.innerHTML = '<div class="ml-empty"><i data-lucide="receipt-text"></i><strong>No matching transactions</strong></div>';
  } else {
    report.innerHTML = `<table class="ml-table"><thead><tr><th>Transaction</th><th>Account / Payee</th><th>Amount</th><th>Prediction</th><th>Severity</th><th>Details</th></tr></thead><tbody>${data.results.map(row => {
      const t = row.transaction;
      const a = row.analysis;
      const labelClass = row.prediction === 1 ? 'ml-anomaly' : row.prediction === 0 ? 'ml-normal' : 'ml-unscored';
      return `<tr><td><strong>${escapeHtml(t.transaction_type.replaceAll('_', ' '))}</strong><small>${escapeHtml(t.transaction_id)}</small><small>${escapeHtml(new Date(t.timestamp).toLocaleString())} &middot; ${escapeHtml(t.status)}</small></td>
        <td>${escapeHtml(t.sender_name || t.sender_username || 'Deleted / system account')}<small>${escapeHtml(t.merchant_name || t.receiver_name || t.purpose_fund_name || 'Wallet')}</small><small>${escapeHtml(t.payment_source.replaceAll('_', ' '))}</small></td>
        <td class="ml-amount" data-label="Amount">BDT ${fmt(t.amount)}</td><td data-label="Prediction"><span class="ml-badge ${labelClass}">${escapeHtml(row.label)}${row.prediction === null ? '' : ` (${row.prediction})`}</span></td>
        <td data-label="Severity">${a ? `${(a.anomaly_score * 100).toFixed(1)} percentile` : 'N/A'}${a && !a.features_summary.in_training_domain ? '<small class="ml-caution">Outside training domain</small>' : ''}</td>
        <td>${a ? `<details><summary title="Prediction details">Review</summary><div class="ml-row-details"><p>${escapeHtml(a.reason)}</p><code>${escapeHtml(a.model_version)}</code><dl>${Object.entries(a.features_summary).map(([key, value]) => `<dt>${escapeHtml(key.replaceAll('_', ' '))}</dt><dd>${escapeHtml(typeof value === 'number' ? Number(value.toFixed(4)) : String(value))}</dd>`).join('')}</dl></div></details>` : '<small>Model unavailable or backfill required</small>'}</td></tr>`;
    }).join('')}</tbody></table>`;
  }
  previous.disabled = !data.previous;
  next.disabled = !data.next;
  document.getElementById('mlPageLabel').textContent = `${data.count} matches · Page ${page} of ${Math.max(1, Math.ceil(data.count / 20))}`;
  if (window.lucide) lucide.createIcons();
}
