/**
 * OmniClaim AI - frontend.
 *
 * Plain JavaScript, no build step. Every piece of text that comes from the
 * API (claimant input, AI output) is escaped with esc() before it is inserted
 * into the page.
 */
'use strict';

const $ = (id) => document.getElementById(id);

const state = {
  claims: [],
  active: null,
  filter: 'ALL',
  search: '',
  view: 'boxes',
  status: null,
  config: null,
  presets: [],
  activePreset: null,
  files: { photo: null, document: null },
  chats: {},
  submitting: false,
  deciding: false,
};

const STATUS = {
  AUTO_APPROVED: { label: 'Auto-approved', tone: 'success' },
  ADJUSTER_REVIEW: { label: 'Adjuster review', tone: 'warning' },
  SIU_ESCALATED: { label: 'SIU referral', tone: 'danger' },
  APPROVED: { label: 'Approved', tone: 'success' },
  DENIED: { label: 'Denied', tone: 'danger' },
};
const TONE = {
  success: 'var(--emerald-success)',
  warning: 'var(--amber-warning)',
  danger: 'var(--crimson-fraud)',
  neutral: 'var(--text-muted)',
  info: 'var(--gcp-blue)',
};
const EVIDENCE = {
  SUPPORTED: ['Supported by photo', 'success'],
  NOT_SUPPORTED: ['Not supported by photo', 'danger'],
  NOT_VISIBLE: ['Not visible in photo', 'warning'],
  NOT_APPLICABLE: ['Not applicable', 'neutral'],
  NOT_CHECKED: ['Not checked against a photo', 'neutral'],
};
const RECOMMENDATION = {
  ALLOW: ['Allow', 'tbl-pill-allow'],
  REDUCE: ['Reduce', 'tbl-pill-reduce'],
  DISALLOW: ['Disallow', 'tbl-pill-disallow'],
  REVIEW: ['Review', 'tbl-pill-review'],
};
const VERDICT = {
  APPLIES: ['Applies', 'neutral'],
  SATISFIED: ['Satisfied', 'success'],
  NOT_MET: ['Not met', 'danger'],
  EXCLUSION_TRIGGERED: ['Exclusion applies', 'danger'],
};
const COVERAGE = {
  COVERED: ['Covered', 'success'],
  PARTIALLY_COVERED: ['Partly covered', 'warning'],
  NOT_COVERED: ['Not covered', 'danger'],
  NEEDS_REVIEW: ['Coverage needs review', 'warning'],
};
const SOURCE = {
  'photo-check': 'Photo check',
  'document-check': 'Document check',
  'policy-check': 'Policy check',
  benchmark: 'Cost benchmark',
  'amount-check': 'Amount check',
  gemini: 'Gemini',
  'recorded-demo': 'Recorded demo',
  sample: 'Sample data',
  demo: 'Demo mode',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function money(value, digits = 2) {
  const n = Number(value || 0);
  return '$' + n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function moneyShort(value) {
  const n = Number(value || 0);
  if (n >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M';
  if (n >= 1e4) return '$' + (n / 1e3).toFixed(1) + 'k';
  return money(n, 0);
}

function fmtDate(iso) {
  if (!iso) return '-';
  const d = new Date(iso.length === 10 ? iso + 'T00:00:00' : iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

function fmtDateTime(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function fmtMs(ms) {
  if (ms === null || ms === undefined) return '-';
  if (ms < 1) return '<1 ms';
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function humanize(code) {
  const text = String(code || '').replace(/_/g, ' ').toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function lozenge(text, tone) {
  return `<span class="lozenge lozenge-${tone}">${esc(text)}</span>`;
}

function inlineMarkdown(escaped) {
  return escaped.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
}

/** Small, safe Markdown subset for copilot answers: bold, code, bullets, paragraphs. */
function renderMarkdown(text) {
  const lines = esc(text).split(/\r?\n/);
  let html = '';
  let inList = false;
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (/^\s*```/.test(line)) continue;
    const bullet = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)$/);
    if (bullet) {
      if (!inList) { html += '<ul>'; inList = true; }
      html += `<li>${inlineMarkdown(bullet[1])}</li>`;
      continue;
    }
    if (inList) { html += '</ul>'; inList = false; }
    if (!line.trim()) continue;
    const heading = line.match(/^#{1,4}\s+(.*)$/);
    html += heading ? `<p><strong>${inlineMarkdown(heading[1])}</strong></p>` : `<p>${inlineMarkdown(line)}</p>`;
  }
  if (inList) html += '</ul>';
  return html;
}

async function api(path, options = {}) {
  const opts = { method: options.method || 'GET', headers: {} };
  if (options.body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(options.body);
  }
  let response;
  try {
    response = await fetch(path, opts);
  } catch (err) {
    throw new Error('Cannot reach the server. Check that it is running.');
  }
  let data = null;
  try {
    data = await response.json();
  } catch (err) {
    data = null;
  }
  if (!response.ok) {
    const error = new Error((data && data.error) || `Request failed (${response.status}).`);
    error.field = data && data.field;
    error.status = response.status;
    throw error;
  }
  return data;
}

function showToast(message, tone = 'info') {
  const toast = document.createElement('div');
  toast.className = `toast toast-${tone}`;
  toast.innerHTML = `<span class="toast-dot"></span><span>${esc(message)}</span>`;
  const container = $('toast-container');
  container.appendChild(toast);
  while (container.children.length > 3) container.firstElementChild.remove();
  setTimeout(() => {
    toast.classList.add('toast-leaving');
    setTimeout(() => toast.remove(), 300);
  }, 4500);
}

// ---------------------------------------------------------------------------
// Start-up
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', init);

async function init() {
  bindEvents();
  await Promise.all([loadStatus(), loadConfig(), loadPresets()]);
  await loadClaims();
  applyUrlParams();
}

async function loadStatus() {
  try {
    state.status = await api('/api/status');
    renderAiIndicators();
  } catch (err) {
    showToast(`Could not load server status: ${err.message}`, 'danger');
  }
}

async function loadConfig() {
  try {
    state.config = await api('/api/config');
  } catch (err) {
    state.config = null;
  }
}

async function loadPresets() {
  try {
    const data = await api('/samples/presets.json');
    state.presets = data.presets || [];
  } catch (err) {
    state.presets = [];
  }
  renderPresets();
}

async function loadClaims(selectId) {
  try {
    state.claims = await api('/api/claims');
  } catch (err) {
    $('claims-list').innerHTML = `<div class="empty-list-notice">Could not load claims: ${esc(err.message)}</div>`;
    return;
  }
  renderMetrics();
  renderClaimList();
  const target = selectId || (state.active && state.active.id) || (state.claims[0] && state.claims[0].id);
  if (target) {
    await selectClaim(target);
  } else {
    $('claim-view').hidden = true;
    $('workbench-empty').hidden = false;
  }
}

function applyUrlParams() {
  const params = new URLSearchParams(window.location.search);
  const claimId = params.get('claim');
  const finish = () => {
    const tab = params.get('tab');
    if (tab) activateTab(tab);
    const modal = params.get('modal');
    if (modal === 'new') openNewClaim();
    if (modal === 'arch') openArchitecture();
    if (modal === 'settings') openSettings();
    if (params.get('copilot') === '1') setCopilot(true);
  };
  if (claimId) selectClaim(claimId.toUpperCase()).then(finish);
  else finish();
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

function bindEvents() {
  $('claims-search').addEventListener('input', (e) => {
    state.search = e.target.value.trim().toLowerCase();
    renderClaimList();
  });
  document.querySelectorAll('.filter-chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('.filter-chip').forEach((c) => c.classList.remove('active'));
      chip.classList.add('active');
      state.filter = chip.dataset.filter;
      renderClaimList();
    });
  });
  const list = $('claims-list');
  list.addEventListener('click', (e) => {
    const card = e.target.closest('.claim-queue-card');
    if (card) {
      selectClaim(card.dataset.id);
      revealWorkbenchOnMobile();
    }
  });
  list.addEventListener('keydown', (e) => {
    const card = e.target.closest('.claim-queue-card');
    if (card && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      selectClaim(card.dataset.id);
      revealWorkbenchOnMobile();
    }
  });

  document.querySelectorAll('.wtab-btn').forEach((btn) => btn.addEventListener('click', () => activateTab(btn.dataset.tab)));

  $('btn-view-boxes').addEventListener('click', () => setPhotoView('boxes'));
  $('btn-view-meta').addEventListener('click', () => setPhotoView('meta'));
  if (window.ResizeObserver) new ResizeObserver(() => layoutOverlay()).observe($('photo-stage'));

  document.querySelectorAll('.adjudication-action-buttons [data-action]').forEach((btn) => {
    btn.addEventListener('click', () => decide(btn.dataset.action));
  });
  $('btn-copy-letter').addEventListener('click', copyLetter);

  $('btn-new-claim').addEventListener('click', openNewClaim);
  $('btn-open-arch').addEventListener('click', openArchitecture);
  $('btn-open-settings').addEventListener('click', openSettings);
  $('btn-toggle-copilot').addEventListener('click', () => setCopilot(!$('copilot-drawer').classList.contains('open')));
  $('btn-close-copilot').addEventListener('click', () => setCopilot(false));
  $('copilot-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const question = $('copilot-input').value.trim();
    if (!question) return;
    $('copilot-input').value = '';
    askCopilot(question);
  });
  $('copilot-history').addEventListener('click', (e) => {
    const chip = e.target.closest('.chip-prompt');
    if (chip) askCopilot(chip.dataset.query);
  });

  document.querySelectorAll('[data-close]').forEach((btn) => btn.addEventListener('click', () => closeModal(btn.dataset.close)));
  document.querySelectorAll('.modal-backdrop').forEach((backdrop) => {
    backdrop.addEventListener('mousedown', (e) => {
      if (e.target === backdrop) closeModal(backdrop.id);
    });
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const open = Array.from(document.querySelectorAll('.modal-backdrop')).find((m) => !m.hidden);
    if (open) closeModal(open.id);
    else setCopilot(false);
  });

  $('claim-form').addEventListener('submit', submitClaim);
  setupUpload('photo', $('f-photo'), $('upload-photo'));
  setupUpload('document', $('f-document'), $('upload-document'));
  $('claim-form').addEventListener('input', (e) => {
    if (e.target.classList) e.target.classList.remove('invalid');
  });

  $('settings-form').addEventListener('submit', saveSettings);
  $('settings-form').addEventListener('change', (e) => {
    if (e.target.name === 'backend') updateBackendFields();
  });
  $('btn-test-connection').addEventListener('click', testConnection);
  $('btn-reveal-key').addEventListener('click', () => {
    const input = $('cfg-api-key');
    const hidden = input.type === 'password';
    input.type = hidden ? 'text' : 'password';
    $('btn-reveal-key').textContent = hidden ? 'Hide' : 'Show';
  });
  $('btn-reset-data').addEventListener('click', resetData);
}

function revealWorkbenchOnMobile() {
  if (window.matchMedia('(max-width: 900px)').matches) {
    $('workbench-main').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function activateTab(tab) {
  const button = document.querySelector(`.wtab-btn[data-tab="${tab}"]`);
  if (!button) return;
  document.querySelectorAll('.wtab-btn').forEach((b) => {
    b.classList.toggle('active', b === button);
    b.setAttribute('aria-selected', b === button ? 'true' : 'false');
  });
  document.querySelectorAll('.tab-pane').forEach((p) => p.classList.toggle('active', p.id === `pane-${tab}`));
  if (tab === 'forensics') requestAnimationFrame(layoutOverlay);
}

// ---------------------------------------------------------------------------
// AI status indicators
// ---------------------------------------------------------------------------

function aiSummary() {
  const ai = state.status && state.status.ai;
  if (!ai) return { text: 'Status unknown', tone: 'neutral', state: 'unknown' };
  const where = ai.backend === 'vertex' ? 'Vertex AI' : 'Gemini API';
  if (ai.state === 'live') return { text: `Gemini live (${where})`, tone: 'success', state: 'live', model: ai.model };
  if (ai.state === 'configured') return { text: `Gemini ready (${where})`, tone: 'info', state: 'configured', model: ai.model };
  if (ai.state === 'error') return { text: 'Gemini error', tone: 'danger', state: 'error', model: ai.model };
  return { text: 'Demo mode', tone: 'neutral', state: 'not_configured' };
}

function renderAiIndicators() {
  const summary = aiSummary();
  $('ai-pill-text').textContent = summary.text;
  $('ai-pill-model').textContent = summary.model || '';
  $('ai-pill-model').hidden = !summary.model;
  $('ai-pill-dot').style.background = TONE[summary.tone];
  $('ai-live-dot').style.background = TONE[summary.tone];
  $('ai-pill').title = state.status && state.status.ai && state.status.ai.lastError ? state.status.ai.lastError : summary.text;
  $('copilot-status').textContent = summary.state === 'live' || summary.state === 'configured'
    ? `Gemini ${summary.model}` : summary.state === 'error' ? 'Gemini error: template answers' : 'Demo mode: template answers';
  const note = summary.state === 'live' || summary.state === 'configured'
    ? `Analysis by Gemini (${summary.model})`
    : summary.state === 'error' ? 'Gemini is failing; demo mode will be used' : 'Demo mode: Gemini is not configured';
  $('engine-note').textContent = note;
}

// ---------------------------------------------------------------------------
// Workspace summary and queue
// ---------------------------------------------------------------------------

function renderMetrics() {
  const claims = state.claims;
  const total = claims.length;
  const samples = claims.filter((c) => c.isSample).length;
  $('metric-total').textContent = total;
  $('metric-total-sub').textContent = `${total - samples} new, ${samples} sample`;

  const auto = claims.filter((c) => c.status === 'AUTO_APPROVED').length;
  $('metric-auto').textContent = total ? `${Math.round((auto / total) * 100)}%` : '0%';
  $('metric-auto-sub').textContent = `${auto} of ${total} claims`;

  let flagged = 0;
  let flaggedClaims = 0;
  claims.forEach((c) => {
    const amount = (c.lineItems || [])
      .filter((i) => i.recommendation === 'DISALLOW' || i.recommendation === 'REDUCE')
      .reduce((sum, i) => sum + (i.billedAmount - i.allowedAmount), 0);
    if (amount > 0) { flagged += amount; flaggedClaims += 1; }
  });
  $('metric-disallowed').textContent = moneyShort(flagged);
  $('metric-disallowed-sub').textContent = `on ${flaggedClaims} claim${flaggedClaims === 1 ? '' : 's'}`;

  const times = claims.filter((c) => c.analysis && c.analysis.engine === 'gemini' && c.analysis.durationMs)
    .map((c) => c.analysis.durationMs).sort((a, b) => a - b);
  if (times.length) {
    const mid = Math.floor(times.length / 2);
    const median = times.length % 2 ? times[mid] : Math.round((times[mid - 1] + times[mid]) / 2);
    $('metric-speed').textContent = fmtMs(median);
    $('metric-speed-sub').textContent = `over ${times.length} Gemini analys${times.length === 1 ? 'is' : 'es'}`;
  } else {
    $('metric-speed').textContent = '-';
    $('metric-speed-sub').textContent = 'No Gemini analyses yet';
  }

  const siu = claims.filter((c) => c.status === 'SIU_ESCALATED').length;
  $('metric-siu').textContent = siu;
  $('metric-siu-sub').textContent = 'risk 80+ or reused evidence';
}

function riskTone(score) {
  if (score >= 80) return 'danger';
  if (score >= 20) return 'warning';
  return 'success';
}

function renderClaimList() {
  const q = state.search;
  const filtered = state.claims.filter((c) => {
    const matchesFilter = state.filter === 'ALL' || c.status === state.filter;
    const haystack = `${c.id} ${c.claimantName} ${c.policyNumber} ${c.lossType}`.toLowerCase();
    return matchesFilter && (!q || haystack.includes(q));
  });
  $('claims-count').textContent = `${filtered.length} claim${filtered.length === 1 ? '' : 's'}`;
  if (!filtered.length) {
    $('claims-list').innerHTML = '<div class="empty-list-notice">No claims match.</div>';
    return;
  }
  $('claims-list').innerHTML = filtered.map((c) => {
    const status = STATUS[c.status] || { label: humanize(c.status), tone: 'neutral' };
    const active = state.active && state.active.id === c.id;
    return `
      <div class="claim-queue-card${active ? ' active' : ''}" data-id="${esc(c.id)}" role="listitem" tabindex="0" aria-current="${active}">
        <div class="card-top-row">
          <span class="card-claim-id">${esc(c.id)}${c.isSample ? ' <span class="card-sample">sample</span>' : ''}</span>
          <span class="risk-pill risk-${riskTone(c.riskScore)}"><span>${esc(c.riskScore)}</span><span>risk</span></span>
        </div>
        <div class="card-claimant-name">${esc(c.claimantName)}</div>
        <div class="card-loss-summary">${esc(c.lossType)}</div>
        <div class="card-bottom-row">
          <span class="card-amt">${money(c.claimedAmount)}</span>
          <span class="card-status-label" style="color:${TONE[status.tone]}">${esc(status.label)}</span>
        </div>
      </div>`;
  }).join('');
}

// ---------------------------------------------------------------------------
// Claim detail
// ---------------------------------------------------------------------------

async function selectClaim(id) {
  let claim;
  try {
    claim = await api(`/api/claims/${encodeURIComponent(id)}`);
  } catch (err) {
    showToast(err.message, 'danger');
    return;
  }
  const previous = state.active && state.active.id;
  state.active = claim;
  const index = state.claims.findIndex((c) => c.id === claim.id);
  if (index >= 0) state.claims[index] = claim;
  renderClaimList();
  renderClaim(claim);
  if (previous && previous !== claim.id) noteCopilotClaimChange(claim);
}

function renderClaim(c) {
  $('workbench-empty').hidden = true;
  $('claim-view').hidden = false;

  const status = STATUS[c.status] || { label: humanize(c.status), tone: 'neutral' };
  $('claim-id').textContent = c.id;
  $('claim-status').textContent = status.label;
  $('claim-status').style.color = TONE[status.tone];
  $('claim-sample-tag').hidden = !c.isSample;
  $('claim-loss').textContent = c.lossType;
  $('claim-claimant').textContent = c.claimantName;
  $('claim-date').textContent = fmtDate(c.incidentDate);
  $('claim-location').textContent = c.incidentLocation || 'Location not given';
  $('claim-policy').textContent = c.policyNumber;

  const a = c.analysis || {};
  let engine = esc(a.label || '');
  if (a.engine === 'gemini') engine = `Analyzed by Gemini <code>${esc(a.model)}</code> via ${a.backend === 'vertex' ? 'Vertex AI' : 'the Gemini API'}`;
  $('claim-engine').innerHTML = `${engine}${a.durationMs ? ` &middot; ${esc(fmtMs(a.durationMs))}` : ''} &middot; ${esc(fmtDateTime(c.createdAt))}`;

  const tone = riskTone(c.riskScore);
  $('claim-risk').textContent = c.riskScore;
  $('claim-risk-level').textContent = `${humanize(c.riskLevel)} risk`;
  $('claim-risk-level').style.color = TONE[tone];
  $('risk-circle').setAttribute('stroke-dasharray', `${c.riskScore}, 100`);
  $('risk-circle').style.stroke = TONE[tone];

  const notice = $('claim-notice');
  notice.hidden = !a.notice;
  notice.textContent = a.notice || '';

  renderPhoto(c);
  renderFindings(c);
  renderSteps(c);
  renderDocument(c);
  renderPolicy(c);
  renderBenchmark(c);
  renderDecision(c);
}

// -- Photo ----------------------------------------------------------------------

function renderPhoto(c) {
  const img = $('photo-img');
  const overlay = $('damage-overlay');
  overlay.innerHTML = '';
  img.hidden = true;
  img.removeAttribute('src');
  $('photo-illustration').hidden = true;
  $('photo-empty').hidden = true;

  const regions = c.damageRegions || [];
  if (c.photo && c.photo.file) {
    img.onload = () => { layoutOverlay(); drawBoxes(regions); };
    img.src = `/api/claims/${encodeURIComponent(c.id)}/photo?h=${encodeURIComponent(c.photo.dhash)}`;
    img.hidden = false;
    const who = { gemini: 'Gemini', 'recorded-demo': 'the recorded demo result', sample: 'the sample assessment' }[c.analysis.engine];
    $('photo-subtitle').textContent = regions.length && who
      ? `${regions.length} damage area${regions.length === 1 ? '' : 's'} marked by ${who}`
      : `${c.photo.width} x ${c.photo.height} px`;
  } else if (c.illustration && ILLUSTRATIONS[c.illustration]) {
    $('photo-illustration').innerHTML = ILLUSTRATIONS[c.illustration];
    $('photo-illustration').hidden = false;
    $('photo-subtitle').textContent = 'Illustration for this sample scenario (no photo stored)';
  } else {
    $('photo-empty').hidden = false;
    $('photo-subtitle').textContent = 'No photo submitted';
  }
  $('photo-caption').textContent = c.damageSummary || '';
  renderPhotoMeta(c);
  setPhotoView(state.view);
}

function layoutOverlay() {
  const img = $('photo-img');
  const overlay = $('damage-overlay');
  const stage = $('photo-stage');
  if (img.hidden || !img.naturalWidth) {
    overlay.style.width = '0';
    return;
  }
  const scale = Math.min(stage.clientWidth / img.naturalWidth, stage.clientHeight / img.naturalHeight);
  const width = img.naturalWidth * scale;
  const height = img.naturalHeight * scale;
  overlay.style.width = `${width}px`;
  overlay.style.height = `${height}px`;
  overlay.style.left = `${(stage.clientWidth - width) / 2}px`;
  overlay.style.top = `${(stage.clientHeight - height) / 2}px`;
}

function drawBoxes(regions) {
  $('damage-overlay').innerHTML = regions.map((r) => {
    const [ymin, xmin, ymax, xmax] = r.box;
    const severity = String(r.severity || '').toLowerCase();
    const labelBelow = ymin < 80 ? ' label-below' : '';
    return `<div class="damage-box sev-${esc(severity)}${labelBelow}" style="top:${ymin / 10}%;left:${xmin / 10}%;width:${(xmax - xmin) / 10}%;height:${(ymax - ymin) / 10}%">
      <span class="damage-label">${esc(r.label)}</span></div>`;
  }).join('');
}

function renderPhotoMeta(c) {
  const rows = [];
  if (!c.photo) {
    rows.push(['Photo', c.illustration ? 'Sample scenario: no original photo stored' : 'No photo submitted', 'neutral']);
  } else {
    const m = c.photo.metadata || {};
    const camera = [m.cameraMake, m.cameraModel].filter(Boolean).join(' ');
    rows.push(['Camera', camera || 'Not recorded', camera ? 'neutral' : 'muted']);
    rows.push(['Taken', m.capturedAt ? fmtDateTime(m.capturedAt) : 'No capture date', m.capturedAt ? 'neutral' : 'muted']);
    rows.push(['Editing software', m.editedWith || m.software || 'None recorded', m.editedWith ? 'danger' : 'muted']);
    rows.push(['GPS', m.gps ? `${m.gps.lat}, ${m.gps.lon}` : 'Not recorded', m.gps ? 'neutral' : 'muted']);
    rows.push(['Perceptual hash', c.photo.dhash, 'mono']);
    const matches = c.photo.matches || [];
    rows.push(['Reuse check', matches.length
      ? `Matches ${matches.map((x) => `${x.claimId} (${x.distance}/64 bits differ)`).join(', ')}`
      : 'No match in earlier claims', matches.length ? 'danger' : 'success']);
    rows.push(['File', c.photo.fileName || '-', 'muted']);
  }
  $('photo-meta-rows').innerHTML = rows.map(([k, v, tone]) =>
    `<div class="exif-item"><span class="e-k">${esc(k)}</span><span class="e-v e-${tone}">${esc(v)}</span></div>`).join('');
}

function setPhotoView(view) {
  state.view = view;
  $('btn-view-boxes').classList.toggle('active', view === 'boxes');
  $('btn-view-meta').classList.toggle('active', view === 'meta');
  $('photo-meta').hidden = view !== 'meta';
  $('damage-overlay').hidden = view !== 'boxes';
  if (view === 'boxes') requestAnimationFrame(layoutOverlay);
}

// -- Findings and analysis log -----------------------------------------------------

function renderFindings(c) {
  const findings = c.findings || [];
  $('findings-list').innerHTML = findings.length ? findings.map((f) => {
    const sev = { CRITICAL: 'sev-critical', MEDIUM: 'sev-medium', INFO: 'sev-info' }[f.severity] || 'sev-info';
    return `<div class="finding-item">
      <div class="finding-header">
        <span class="finding-title">${esc(f.title)}</span>
        <span class="finding-sev ${sev}">${esc(f.severity)}</span>
      </div>
      <div class="finding-desc">${esc(f.detail)}</div>
      <div class="finding-source">${esc(SOURCE[f.source] || f.source)}</div>
    </div>`;
  }).join('') : '<div class="empty-panel">No findings.</div>';
  $('risk-rationale').textContent = c.riskRationale || '-';
  $('routing-reason').textContent = c.routingReason || '-';
}

function renderSteps(c) {
  const steps = (c.analysis && c.analysis.steps) || [];
  $('analysis-total').textContent = c.analysis && c.analysis.durationMs ? `Total ${fmtMs(c.analysis.durationMs)}` : '';
  $('analysis-steps').innerHTML = steps.map((s) => {
    const tone = s.status === 'failed' ? 'danger' : s.status === 'skipped' ? 'neutral' : 'success';
    return `<tr>
      <td><strong>${esc(s.name)}</strong></td>
      <td>${lozenge(humanize(s.status), tone)} <span class="step-detail">${esc(s.detail)}</span></td>
      <td class="num">${esc(fmtMs(s.ms))}</td>
    </tr>`;
  }).join('');
}

// -- Bill ---------------------------------------------------------------------------

function renderDocument(c) {
  const doc = c.document;
  $('doc-type').textContent = doc ? (doc.type || 'Document') : 'None provided';
  const docAi = doc && doc.documentAi;
  $('doc-sub').textContent = docAi
    ? [docAi.invoiceId && `Invoice ${docAi.invoiceId}`, docAi.invoiceDate && fmtDate(docAi.invoiceDate),
      `${docAi.lineItems.length} lines read by Document AI`].filter(Boolean).join(' · ')
    : '';
  $('doc-vendor').textContent = (doc && doc.vendor) || '-';
  $('doc-total').textContent = doc && doc.total !== null && doc.total !== undefined ? money(doc.total) : '-';
  $('doc-reader').textContent = doc ? (doc.extractedBy || 'Not read (Gemini not configured)') : '-';
  const open = $('doc-open');
  if (doc && doc.file) {
    open.href = `/api/claims/${encodeURIComponent(c.id)}/document`;
    open.hidden = false;
  } else {
    open.hidden = true;
  }

  const items = c.lineItems || [];
  $('line-items-wrap').hidden = !items.length;
  $('line-items-empty').hidden = !!items.length;
  if (!items.length) {
    $('line-items-empty').textContent = !doc
      ? 'No repair bill was submitted with this claim.'
      : 'The document was not read because Gemini is not configured on this server.';
    $('line-items-body').innerHTML = '';
    $('line-items-foot').innerHTML = '';
    return;
  }
  $('line-items-body').innerHTML = items.map((i) => {
    const [evidence, eTone] = EVIDENCE[i.photoEvidence] || [humanize(i.photoEvidence), 'neutral'];
    const [rec, recClass] = RECOMMENDATION[i.recommendation] || [humanize(i.recommendation), 'tbl-pill-review'];
    return `<tr>
      <td><strong>${esc(i.description)}</strong></td>
      <td class="tbl-amt num">${money(i.billedAmount)}</td>
      <td><span style="color:${TONE[eTone]}">${esc(evidence)}</span></td>
      <td><span class="${recClass}">${esc(rec)}</span></td>
      <td class="tbl-amt num">${money(i.allowedAmount)}</td>
      <td class="reason-cell">${esc(i.reason)}</td>
    </tr>`;
  }).join('');
  const billed = items.reduce((s, i) => s + i.billedAmount, 0);
  const allowed = items.reduce((s, i) => s + i.allowedAmount, 0);
  const held = items.filter((i) => i.recommendation === 'REVIEW').reduce((s, i) => s + i.billedAmount, 0);
  $('line-items-foot').innerHTML = `<tr>
    <td><strong>Total</strong>${held ? `<div class="step-detail">${money(held)} held for adjuster review</div>` : ''}</td>
    <td class="tbl-amt num">${money(billed)}</td><td></td><td></td>
    <td class="tbl-amt num">${money(allowed)}</td><td></td></tr>`;
}

// -- Policy ---------------------------------------------------------------------------

function renderPolicy(c) {
  const p = c.policy || {};
  const facts = [`<span>Policy <strong>${esc(c.policyNumber)}</strong></span>`];
  if (p.found) {
    facts.push(`<span>Holder <strong>${esc(p.holder)}</strong></span>`);
    facts.push(`<span>Period <strong>${esc(fmtDate(p.effectiveDate))} to ${esc(fmtDate(p.expirationDate))}</strong></span>`);
    if (p.daysSincePolicyStart !== null && p.daysSincePolicyStart !== undefined) {
      facts.push(`<span>Loss <strong>${esc(p.daysSincePolicyStart)} days</strong> after policy start</span>`);
    }
  } else {
    facts.push('<span>Not found in the policy register</span>');
  }
  facts.push(`<span>Wording <strong>${esc((c.coverage && c.coverage.form) || '-')}</strong></span>`);
  $('policy-facts').innerHTML = facts.join('');

  const [coverageText, coverageTone] = COVERAGE[c.coverage.decision] || [humanize(c.coverage.decision), 'neutral'];
  $('coverage-decision').innerHTML = lozenge(coverageText, coverageTone);

  const clauses = c.coverage.clauses || [];
  $('clauses-empty').hidden = !!clauses.length;
  $('clauses-grid').innerHTML = clauses.map((cl) => {
    const [verdict, tone] = VERDICT[cl.verdict] || [humanize(cl.verdict), 'neutral'];
    return `<div class="clause-card">
      <div class="clause-header">
        <div class="clause-title-cluster"><span class="clause-id">${esc(cl.clauseId)}</span><span class="clause-title">${esc(cl.title)}</span></div>
        ${lozenge(verdict, tone)}
      </div>
      <p class="clause-explanation">${esc(cl.explanation)}</p>
      <div class="clause-text">${esc(cl.text)}</div>
    </div>`;
  }).join('');
}

// -- Benchmark ------------------------------------------------------------------------

function renderBenchmark(c) {
  const b = c.benchmark || {};
  $('bench-cohort').textContent = b.categoryLabel || '-';
  $('bench-size').textContent = b.sampleSize ? b.sampleSize.toLocaleString('en-US') : '-';
  const pct = b.claimPercentile;
  const pctEl = $('bench-percentile');
  pctEl.textContent = pct === null || pct === undefined ? '-' : `${Math.round(pct)}th percentile`;
  pctEl.style.color = pct >= 95 ? TONE.danger : pct >= 75 ? TONE.warning : TONE.success;

  const rows = [
    ['Median of similar claims', b.median, 'bar-standard'],
    ['75th percentile', b.p75, 'bar-standard'],
    ['95th percentile', b.p95, 'bar-moderate'],
    ['This claim (claimed)', c.claimedAmount, pct >= 95 ? 'bar-outlier' : 'bar-claim'],
    ['Recommended for payment', c.settlement.recommended, 'bar-approved'],
  ];
  const max = Math.max(...rows.map((r) => Number(r[1]) || 0), 1) * 1.04;
  $('bench-bars').innerHTML = rows.map(([label, value, cls]) => `
    <div class="bar-row">
      <span class="bar-label">${esc(label)}</span>
      <div class="bar-track"><div class="bar-fill ${cls}" style="width:${Math.max(0.5, (Number(value) || 0) / max * 100)}%"></div></div>
      <span class="bar-val">${money(value, 0)}</span>
    </div>`).join('');
  $('bench-source').textContent = b.dataset
    ? `Source: ${b.dataset}${b.source === 'bigquery' ? ' (queried in BigQuery)' : ' (computed on the server)'}.`
    : '';

  const related = c.related || {};
  $('sig-claimant').textContent = related.sameClaimant ?? 0;
  $('sig-vendor').textContent = related.sameVendor ?? 0;
  $('sig-photo').textContent = related.photoMatches ?? 0;
  $('sig-photo').style.color = related.photoMatches ? TONE.danger : '';
  $('sig-vendor').style.color = related.sameVendor ? TONE.warning : '';
}

// -- Decision ---------------------------------------------------------------------------

function renderDecision(c) {
  const s = c.settlement;
  const lines = [['Amount claimed', money(s.claimed), '']];
  if (s.disallowed) lines.push([c.coverage.decision === 'NOT_COVERED' ? 'Not covered by the policy' : 'Not supported by the evidence', '-' + money(s.disallowed), 'recon-deduct']);
  if (s.held) lines.push(['Held for adjuster review', money(s.held), 'recon-held']);
  lines.push(['Recommended amount', money(s.recommended), '']);
  if (s.approved !== null && s.approved !== undefined && s.basis === 'approved') lines.push(['Approved amount', money(s.approved), '']);
  lines.push(['Deductible', '-' + money(s.deductible), 'recon-deduct']);
  const netLabel = {
    approved: 'Payment',
    recommended: 'Payment if approved as recommended',
    'on-hold': 'Payment on hold (SIU review)',
    denied: 'No payment (denied)',
  }[s.basis] || 'Payment';
  $('ledger').innerHTML = lines.map(([k, v, cls]) => `<div class="recon-line ${cls}"><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('')
    + `<div class="recon-divider"></div><div class="recon-line recon-net"><span>${esc(netLabel)}</span><strong class="${s.net > 0 ? 'text-emerald' : ''}">${money(s.net)}</strong></div>`;

  const d = c.decision;
  $('decision-status').innerHTML = d
    ? `<strong>${esc(d.label)}</strong> by ${esc(d.by)} on ${esc(fmtDateTime(d.at))}${d.notes ? `. ${esc(d.notes)}` : ''}`
    : `<strong>Recommendation:</strong> ${esc(humanize(c.recommendedAction))}. ${esc(c.routingReason || '')}`;

  const payRecommended = Math.max(0, s.recommended - s.deductible);
  const payFull = Math.max(0, s.claimed - s.deductible);
  $('btn-approve-recommended').querySelector('span').textContent = `Approve recommended: pay ${money(payRecommended)}`;
  $('btn-approve-full').querySelector('span').textContent = `Approve full amount: pay ${money(payFull)}`;
  const current = d ? d.action : null;
  document.querySelectorAll('.adjudication-action-buttons [data-action]').forEach((btn) => {
    btn.disabled = state.deciding || btn.dataset.action === current;
  });

  $('letter').value = c.letter || '';
  const draft = !d && (c.status === 'ADJUSTER_REVIEW' || c.status === 'SIU_ESCALATED');
  $('letter-subtitle').textContent = draft ? 'Draft: updates when the adjuster decides' : 'Matches the current decision';
}

async function decide(action) {
  if (!state.active || state.deciding) return;
  state.deciding = true;
  renderDecision(state.active);
  try {
    const updated = await api(`/api/claims/${encodeURIComponent(state.active.id)}/decision`, { method: 'POST', body: { action } });
    state.active = updated;
    const index = state.claims.findIndex((c) => c.id === updated.id);
    if (index >= 0) state.claims[index] = updated;
    showToast(`${updated.id}: ${updated.decision.label.toLowerCase()}. Payment ${money(updated.settlement.net)}.`, 'success');
  } catch (err) {
    showToast(`Decision failed: ${err.message}`, 'danger');
  } finally {
    state.deciding = false;
    renderMetrics();
    renderClaimList();
    if (state.active) renderClaim(state.active);
  }
}

async function copyLetter() {
  const text = $('letter').value;
  try {
    await navigator.clipboard.writeText(text);
    showToast('Letter copied to the clipboard.', 'success');
  } catch (err) {
    $('letter').select();
    showToast('Select the letter text and press Ctrl+C to copy.', 'info');
  }
}

// ---------------------------------------------------------------------------
// Copilot
// ---------------------------------------------------------------------------

function setCopilot(open) {
  $('copilot-drawer').classList.toggle('open', open);
  if (open) $('copilot-input').focus();
}

function appendChat(html, who, extraClass = '') {
  const msg = document.createElement('div');
  msg.className = `chat-msg ${who}-msg ${extraClass}`.trim();
  msg.innerHTML = `<div class="msg-avatar">${who === 'ai' ? 'AI' : 'You'}</div><div class="msg-bubble">${html}</div>`;
  $('copilot-history').appendChild(msg);
  $('copilot-history').scrollTop = $('copilot-history').scrollHeight;
  return msg;
}

function noteCopilotClaimChange(claim) {
  if (!$('copilot-history').querySelector('.user-msg')) return;
  const note = document.createElement('div');
  note.className = 'chat-divider';
  note.textContent = `Now discussing ${claim.id} (${claim.claimantName})`;
  $('copilot-history').appendChild(note);
}

async function askCopilot(question) {
  if (!state.active) return;
  setCopilot(true);
  const claimId = state.active.id;
  const history = state.chats[claimId] || (state.chats[claimId] = []);
  appendChat(`<p>${esc(question)}</p>`, 'user');
  const pending = appendChat('<p class="typing">Thinking</p>', 'ai', 'pending');
  try {
    const result = await api(`/api/claims/${encodeURIComponent(claimId)}/copilot`, {
      method: 'POST', body: { question, history: history.slice(-6) },
    });
    const meta = result.engine === 'gemini'
      ? `Gemini ${esc(result.model)} &middot; ${esc(fmtMs(result.latencyMs))}`
      : 'Template answer (demo mode)';
    const notice = result.notice ? `<p class="chat-notice">${esc(result.notice)}</p>` : '';
    pending.querySelector('.msg-bubble').innerHTML = `${renderMarkdown(result.answer)}${notice}<div class="chat-meta">${meta}</div>`;
    pending.classList.remove('pending');
    history.push({ role: 'user', text: question }, { role: 'model', text: result.answer });
  } catch (err) {
    pending.querySelector('.msg-bubble').innerHTML = `<p class="chat-notice">${esc(err.message)}</p>`;
    pending.classList.remove('pending');
  }
  $('copilot-history').scrollTop = $('copilot-history').scrollHeight;
}

// ---------------------------------------------------------------------------
// Modals
// ---------------------------------------------------------------------------

function openModal(id) {
  $(id).hidden = false;
  const focusable = $(id).querySelector('input, select, textarea, button:not([data-close])');
  if (focusable) setTimeout(() => focusable.focus(), 30);
}

function closeModal(id) {
  if (id === 'modal-new-claim' && state.submitting) return;
  $(id).hidden = true;
}

// -- New claim ---------------------------------------------------------------------------

function renderPresets() {
  const cards = state.presets.map((p) => `
    <button type="button" class="preset-card" data-preset="${esc(p.id)}">
      <span class="preset-badge badge-${esc(p.expectedKind)}">Expected: ${esc(p.expected)}</span>
      <h4>${esc(p.title)}</h4>
      <p>${esc(p.summary)}</p>
    </button>`).join('');
  $('presets-row').innerHTML = cards + `
    <button type="button" class="preset-card preset-blank" data-preset="">
      <span class="preset-badge badge-neutral">Your files</span>
      <h4>Blank claim</h4>
      <p>Fill in the form and upload your own photo and bill.</p>
    </button>`;
  $('presets-row').querySelectorAll('.preset-card').forEach((card) => {
    card.addEventListener('click', () => applyPreset(card.dataset.preset));
  });
}

function openNewClaim() {
  $('claim-form-error').hidden = true;
  $('analyzing-panel').hidden = true;
  if (!$('f-date').value) $('f-date').value = new Date().toISOString().slice(0, 10);
  $('f-date').max = new Date().toISOString().slice(0, 10);
  openModal('modal-new-claim');
}

async function applyPreset(id) {
  const preset = state.presets.find((p) => p.id === id);
  state.activePreset = preset ? preset.id : null;
  $('presets-row').querySelectorAll('.preset-card').forEach((c) => c.classList.toggle('active', c.dataset.preset === (id || '')));
  const form = $('claim-form');
  form.querySelectorAll('.invalid').forEach((el) => el.classList.remove('invalid'));
  $('claim-form-error').hidden = true;
  const values = preset ? preset.form : {
    claimantName: '', policyNumber: '', product: 'auto', lossType: '', incidentDate: new Date().toISOString().slice(0, 10),
    incidentLocation: '', claimedAmount: '', deductible: '', description: '',
  };
  Object.entries(values).forEach(([name, value]) => {
    const field = form.elements[name];
    if (field) field.value = value ?? '';
  });
  setUploadFile('photo', null);
  setUploadFile('document', null);
  if (!preset) return;
  try {
    const [photo, doc] = await Promise.all([fetchAsFile(preset.photo), fetchAsFile(preset.document)]);
    setUploadFile('photo', photo);
    setUploadFile('document', doc);
  } catch (err) {
    showToast(`Could not load the sample files: ${err.message}`, 'danger');
  }
}

async function fetchAsFile(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} (${response.status})`);
  const blob = await response.blob();
  return new File([blob], url.split('/').pop(), { type: blob.type });
}

const uploads = {};

function setupUpload(kind, input, box) {
  uploads[kind] = { input, box, url: null };
  input.addEventListener('change', () => setUploadFile(kind, input.files[0] || null, true));
  const zone = box.querySelector('.dropzone');
  ['dragenter', 'dragover'].forEach((type) => zone.addEventListener(type, (e) => {
    e.preventDefault();
    zone.classList.add('dragging');
  }));
  ['dragleave', 'drop'].forEach((type) => zone.addEventListener(type, () => zone.classList.remove('dragging')));
  zone.addEventListener('drop', (e) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) setUploadFile(kind, file, true);
  });
  box.querySelector('.upload-clear').addEventListener('click', () => setUploadFile(kind, null));
}

function setUploadFile(kind, file, fromUser = false) {
  const u = uploads[kind];
  const maxMb = (state.status && state.status.rules && state.status.rules.maxUploadMb) || 10;
  const allowed = kind === 'photo' ? ['image/jpeg', 'image/png', 'image/webp'] : ['image/jpeg', 'image/png', 'image/webp', 'application/pdf'];
  if (file && file.type && !allowed.includes(file.type)) {
    showToast(kind === 'photo' ? 'The photo must be a JPEG, PNG or WebP image.' : 'The document must be an image or a PDF.', 'danger');
    file = null;
  }
  if (file && file.size > maxMb * 1024 * 1024) {
    showToast(`${file.name} is larger than ${maxMb} MB.`, 'danger');
    file = null;
  }
  if (fromUser && file) {
    state.activePreset = null;
    $('presets-row').querySelectorAll('.preset-card').forEach((c) => c.classList.remove('active'));
  }
  state.files[kind] = file;
  if (u.url) URL.revokeObjectURL(u.url);
  u.url = null;
  const preview = u.box.querySelector('.upload-preview');
  const text = u.box.querySelector('.dropzone-text');
  if (file && file.type.startsWith('image/')) {
    u.url = URL.createObjectURL(file);
    preview.src = u.url;
    preview.hidden = false;
    text.hidden = true;
  } else {
    preview.hidden = true;
    preview.removeAttribute('src');
    text.hidden = false;
    text.textContent = file ? 'PDF document' : (kind === 'photo' ? 'Choose or drop a photo' : 'Choose or drop a bill');
  }
  u.box.querySelector('.upload-name').textContent = file ? `${file.name} (${(file.size / 1024).toFixed(0)} KB)` : '';
  u.box.querySelector('.upload-clear').hidden = !file;
  u.box.classList.toggle('has-file', !!file);
  if (!file) u.input.value = '';
}

function readAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1] || '');
    reader.onerror = () => reject(new Error(`Could not read ${file.name}.`));
    reader.readAsDataURL(file);
  });
}

async function submitClaim(e) {
  e.preventDefault();
  if (state.submitting) return;
  const form = $('claim-form');
  const errorBox = $('claim-form-error');
  errorBox.hidden = true;
  form.querySelectorAll('.invalid').forEach((el) => el.classList.remove('invalid'));

  const required = ['claimantName', 'policyNumber', 'lossType', 'incidentDate', 'claimedAmount', 'description'];
  const missing = required.filter((name) => !String(form.elements[name].value).trim());
  if (missing.length) {
    missing.forEach((name) => form.elements[name].classList.add('invalid'));
    errorBox.textContent = 'Please fill in the highlighted fields.';
    errorBox.hidden = false;
    return;
  }

  const payload = {};
  ['claimantName', 'policyNumber', 'product', 'lossType', 'incidentDate', 'incidentLocation', 'claimedAmount', 'deductible', 'description']
    .forEach((name) => { payload[name] = form.elements[name].value; });
  payload.preset = state.activePreset;

  state.submitting = true;
  $('btn-submit-claim').disabled = true;
  const panel = $('analyzing-panel');
  panel.hidden = false;
  const summary = aiSummary();
  const usingGemini = summary.state === 'live' || summary.state === 'configured';
  $('analyzing-title').textContent = usingGemini ? 'Gemini is analyzing the claim' : 'Analyzing the claim (demo mode)';
  const started = Date.now();
  const tick = () => {
    const seconds = Math.round((Date.now() - started) / 1000);
    $('analyzing-detail').textContent = usingGemini
      ? `Reading the photo and the bill, checking each line against the policy. Usually 5 to 25 seconds. (${seconds} s)`
      : `Running the photo, policy and cost checks. (${seconds} s)`;
  };
  tick();
  const timer = setInterval(tick, 1000);

  try {
    if (state.files.photo) payload.photo = { name: state.files.photo.name, type: state.files.photo.type, data: await readAsBase64(state.files.photo) };
    if (state.files.document) payload.document = { name: state.files.document.name, type: state.files.document.type, data: await readAsBase64(state.files.document) };
    const claim = await api('/api/claims', { method: 'POST', body: payload });
    state.claims.unshift(claim);
    state.submitting = false;
    closeModal('modal-new-claim');
    renderMetrics();
    await selectClaim(claim.id);
    activateTab('forensics');
    const status = STATUS[claim.status] || { label: claim.status, tone: 'info' };
    showToast(`${claim.id}: ${status.label} (risk ${claim.riskScore}).`, status.tone === 'danger' ? 'danger' : 'success');
    if (claim.analysis.notice) showToast(claim.analysis.notice, 'danger');
    loadStatus();
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.hidden = false;
    if (err.field && form.elements[err.field]) form.elements[err.field].classList.add('invalid');
    if (err.field === 'photo' || err.field === 'document') uploads[err.field].box.classList.add('invalid');
  } finally {
    clearInterval(timer);
    state.submitting = false;
    $('btn-submit-claim').disabled = false;
    panel.hidden = true;
  }
}

// -- How it works -------------------------------------------------------------------------

const STATE_LABELS = {
  active: ['Active', 'success'],
  configured: ['Configured', 'info'],
  error: ['Error', 'danger'],
  not_configured: ['Not configured', 'neutral'],
  local: ['Local', 'neutral'],
  planned: ['Roadmap', 'neutral'],
};

async function openArchitecture() {
  openModal('modal-architecture');
  await loadStatus();
  const s = state.status;
  if (!s) return;
  $('integrations-grid').innerHTML = s.integrations.map((i) => {
    const [label, tone] = STATE_LABELS[i.state] || [humanize(i.state), 'neutral'];
    return `<div class="arch-node-card${i.state === 'active' ? ' arch-card-featured' : ''}">
      <div class="arch-node-top"><h4>${esc(i.name)}</h4>${lozenge(label, tone)}</div>
      <p>${esc(i.role)}</p>
      <p class="node-detail">${esc(i.detail)}</p>
    </div>`;
  }).join('');
  const r = s.rules;
  $('rules-list').innerHTML = [
    `Risk 0 to ${r.autoApproveMaxRisk}, coverage confirmed, every billed line supported and no review findings: paid automatically.`,
    `Risk ${r.siuMinRisk} or higher, or a photo or document already used in another claim: referred to the Special Investigations Unit.`,
    'Everything else goes to an adjuster with a recommended amount.',
    `A photo counts as reused when at most ${r.duplicatePhotoMaxDistance} of its 64 perceptual-hash bits differ from an earlier claim's photo.`,
    `Losses within ${r.newPolicyAlertDays} days of the policy start are flagged.`,
    'Payment = approved amount minus the deductible, never negative. Nothing is paid while a claim is with SIU or denied.',
  ].map((t) => `<li>${esc(t)}</li>`).join('');
}

// -- Settings --------------------------------------------------------------------------------

async function openSettings() {
  openModal('modal-settings');
  $('test-feedback').hidden = true;
  await Promise.all([loadStatus(), loadConfig()]);
  renderSettings();
}

function renderSettings() {
  const cfg = state.config;
  const s = state.status;
  if (!cfg || !s) return;
  const ai = s.ai;
  const box = $('settings-status-box');
  const icon = $('settings-status-icon');
  box.className = 'settings-status-box';
  if (ai.state === 'live') {
    box.classList.add('status-live');
    icon.textContent = '✓';
    $('settings-status-title').textContent = `Connected: ${ai.model}`;
    $('settings-status-detail').textContent = `${ai.backend === 'vertex' ? `Vertex AI, project ${ai.project}, location ${ai.location}` : 'Gemini Developer API'}. Last call ${fmtMs(ai.lastLatencyMs)} at ${fmtDateTime(ai.lastCheckedAt)}.`;
  } else if (ai.state === 'configured') {
    box.classList.add('status-info');
    icon.textContent = 'i';
    $('settings-status-title').textContent = `Configured: ${ai.model}`;
    $('settings-status-detail').textContent = 'Not called yet. Use "Test connection" to check it.';
  } else if (ai.state === 'error') {
    box.classList.add('status-error');
    icon.textContent = '!';
    $('settings-status-title').textContent = 'The last Gemini call failed';
    $('settings-status-detail').textContent = ai.lastError || '';
  } else {
    icon.textContent = '!';
    $('settings-status-title').textContent = 'Demo mode: Gemini is not configured';
    $('settings-status-detail').textContent = ai.hint || 'Claims are analyzed with recorded demo results and rules.';
  }

  const form = $('settings-form');
  form.querySelectorAll('input[name="backend"]').forEach((r) => { r.checked = r.value === cfg.backend; });
  $('cfg-project').value = cfg.project || '';
  $('cfg-location').value = cfg.location || 'global';
  $('cfg-api-key').value = '';
  $('cfg-api-key').placeholder = cfg.apiKeySet ? `Key in use ${cfg.apiKeyMasked}. Paste a new key to replace it.` : 'Paste a key';
  const models = Array.from(new Set([...(cfg.supportedModels || []), cfg.model].filter(Boolean)));
  $('cfg-model').innerHTML = models.map((m) => `<option value="${esc(m)}">${esc(m)}${m === 'gemini-3.8-flash' ? ' (recommended)' : ''}</option>`).join('');
  $('cfg-model').value = cfg.model;
  $('cfg-thinking').value = cfg.thinkingLevel || 'LOW';

  const writable = cfg.writable;
  form.querySelectorAll('input, select').forEach((el) => { el.disabled = !writable; });
  $('btn-reveal-key').disabled = !writable;
  $('btn-save-settings').hidden = !writable;
  $('settings-readonly').hidden = writable;
  $('btn-reset-data').hidden = !(s.settings && s.settings.dataResetAllowed);
  updateBackendFields();
}

function updateBackendFields() {
  const checked = $('settings-form').querySelector('input[name="backend"]:checked');
  const backend = checked ? checked.value : 'none';
  $('vertex-fields').hidden = backend !== 'vertex';
  $('apikey-fields').hidden = backend !== 'api-key';
}

async function saveSettings(e) {
  e.preventDefault();
  const checked = $('settings-form').querySelector('input[name="backend"]:checked');
  const body = {
    backend: checked ? checked.value : 'none',
    project: $('cfg-project').value.trim(),
    location: $('cfg-location').value.trim() || 'global',
    model: $('cfg-model').value,
    thinkingLevel: $('cfg-thinking').value,
  };
  const key = $('cfg-api-key').value.trim();
  if (key) body.apiKey = key;
  try {
    state.config = await api('/api/config', { method: 'POST', body });
    await loadStatus();
    renderSettings();
    showToast('Settings saved. Use "Test connection" to check them.', 'success');
  } catch (err) {
    showToast(`Could not save settings: ${err.message}`, 'danger');
  }
}

async function testConnection() {
  const feedback = $('test-feedback');
  feedback.hidden = false;
  feedback.className = 'test-feedback-box';
  $('test-spinner').hidden = false;
  $('test-message').textContent = 'Calling Gemini...';
  try {
    const result = await api('/api/config/test', { method: 'POST', body: {} });
    $('test-spinner').hidden = true;
    const configured = state.status && state.status.ai && state.status.ai.configured;
    if (result.ok) feedback.classList.add('feedback-ok');
    else if (configured) feedback.classList.add('feedback-error');
    $('test-message').textContent = result.ok
      ? `Gemini answered "${result.message}" in ${fmtMs(result.latencyMs)} (${result.model}).`
      : result.message;
  } catch (err) {
    $('test-spinner').hidden = true;
    feedback.classList.add('feedback-error');
    $('test-message').textContent = err.message;
  }
  await loadStatus();
  renderSettings();
  feedback.hidden = false;
}

let resetArmed = false;
async function resetData() {
  const button = $('btn-reset-data');
  if (!resetArmed) {
    resetArmed = true;
    button.textContent = 'Click again to delete new claims';
    setTimeout(() => { resetArmed = false; button.textContent = 'Reset demo data'; }, 4000);
    return;
  }
  resetArmed = false;
  button.textContent = 'Reset demo data';
  try {
    await api('/api/admin/reset', { method: 'POST', body: {} });
    state.active = null;
    state.chats = {};
    closeModal('modal-settings');
    await loadClaims();
    showToast('Demo data restored to the sample claims.', 'success');
  } catch (err) {
    showToast(`Reset failed: ${err.message}`, 'danger');
  }
}

// ---------------------------------------------------------------------------
// Illustrations for sample claims that have no stored photo
// ---------------------------------------------------------------------------

const ILLUSTRATIONS = {
  car_bumper: `
    <svg class="visual-svg-canvas" viewBox="0 0 600 320" role="img" aria-label="Illustration of a car rear bumper with a light scrape">
      <rect width="600" height="320" fill="#1b2130"/>
      <path d="M 120 240 Q 120 180 180 150 L 220 120 L 380 120 L 420 150 Q 480 180 480 240 Z" fill="#2a3346" stroke="#4b5872" stroke-width="2"/>
      <path d="M 100 240 L 500 240 L 480 280 L 120 280 Z" fill="#323c52" stroke="#5c6a86" stroke-width="2"/>
      <rect x="135" y="180" width="70" height="25" rx="4" fill="#b84a4a"/>
      <rect x="395" y="180" width="70" height="25" rx="4" fill="#b84a4a"/>
      <ellipse cx="160" cy="285" rx="12" ry="6" fill="#7c8698"/>
      <ellipse cx="440" cy="285" rx="12" ry="6" fill="#7c8698"/>
      <g transform="translate(190, 250)" stroke="#e8b04a" stroke-linecap="round"><line x1="0" y1="0" x2="45" y2="12" stroke-width="3"/><line x1="8" y1="8" x2="38" y2="18" stroke-width="2.5"/></g>
      <text x="16" y="304" fill="#8a93a3" font-family="IBM Plex Sans, sans-serif" font-size="12">Illustration</text>
    </svg>`,
  water_ceiling: `
    <svg class="visual-svg-canvas" viewBox="0 0 600 320" role="img" aria-label="Illustration of a water-stained ceiling below a pipe">
      <defs><radialGradient id="stain" cx="45%" cy="40%" r="50%"><stop offset="0%" stop-color="#b08a4e" stop-opacity="0.85"/><stop offset="70%" stop-color="#8a6a3c" stop-opacity="0.35"/><stop offset="100%" stop-color="#8a6a3c" stop-opacity="0"/></radialGradient></defs>
      <rect width="600" height="320" fill="#d9d6cf"/>
      <line x1="80" y1="70" x2="520" y2="70" stroke="#a8743c" stroke-width="10" stroke-linecap="round"/>
      <circle cx="270" cy="70" r="9" fill="#7a4f25"/>
      <ellipse cx="270" cy="160" rx="170" ry="95" fill="url(#stain)"/>
      <text x="16" y="304" fill="#5d6779" font-family="IBM Plex Sans, sans-serif" font-size="12">Illustration</text>
    </svg>`,
  subaru_glass: `
    <svg class="visual-svg-canvas" viewBox="0 0 600 320" role="img" aria-label="Illustration of a windshield with a star-shaped crack">
      <rect width="600" height="320" fill="#1b2130"/>
      <polygon points="120,60 480,60 520,250 80,250" fill="#3c5a7a" stroke="#7fa3c8" stroke-width="2"/>
      <g transform="translate(300, 160)" stroke="#ffffff" stroke-width="2"><circle cx="0" cy="0" r="5" fill="#ffffff"/><line x1="0" y1="0" x2="-55" y2="-30"/><line x1="0" y1="0" x2="60" y2="-25"/><line x1="0" y1="0" x2="-20" y2="55"/><line x1="0" y1="0" x2="45" y2="40"/><line x1="0" y1="0" x2="-70" y2="15"/></g>
      <text x="16" y="304" fill="#8a93a3" font-family="IBM Plex Sans, sans-serif" font-size="12">Illustration</text>
    </svg>`,
  camry_side: `
    <svg class="visual-svg-canvas" viewBox="0 0 600 320" role="img" aria-label="Illustration of a sedan with a creased passenger door">
      <rect width="600" height="320" fill="#1b2130"/>
      <path d="M 70 220 L 110 160 L 210 120 L 390 120 L 470 165 L 530 180 L 535 225 Z" fill="#8f9bb0" stroke="#c4cddb" stroke-width="2"/>
      <path d="M 220 128 L 300 128 L 300 165 L 190 165 Z M 310 128 L 385 128 L 440 165 L 310 165 Z" fill="#3c4a5e"/>
      <line x1="300" y1="128" x2="300" y2="222" stroke="#5c6a86" stroke-width="2"/>
      <path d="M 320 185 Q 360 200 420 188" stroke="#e8b04a" stroke-width="4" fill="none" stroke-linecap="round"/>
      <circle cx="150" cy="228" r="30" fill="#2a3346" stroke="#c4cddb" stroke-width="3"/>
      <circle cx="450" cy="228" r="30" fill="#2a3346" stroke="#c4cddb" stroke-width="3"/>
      <text x="16" y="304" fill="#8a93a3" font-family="IBM Plex Sans, sans-serif" font-size="12">Illustration</text>
    </svg>`,
};
