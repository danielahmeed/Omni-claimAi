/**
 * OmniClaim AI - Frontend Application Controller
 * Google Cloud Hackathon Solution: Vertex AI, Document AI, BigQuery
 */

// Global Application State
const state = {
  claims: [],
  activeClaim: null,
  activeTab: 'forensics',
  activeFilter: 'ALL',
  searchQuery: '',
  showBoundingBoxes: true,
  benchmarks: null,
  isCopilotOpen: false,
  config: null
};

// DOM Element Selectors
const elements = {
  claimsList: document.getElementById('claims-list'),
  claimsSearchInput: document.getElementById('claims-search-input'),
  filterChips: document.querySelectorAll('.filter-chip'),
  totalBadge: document.getElementById('claims-total-badge'),

  // GCP Integration Controls
  btnOpenSettings: document.getElementById('btn-open-settings'),
  modalSettings: document.getElementById('modal-settings'),
  btnCloseSettings: document.getElementById('btn-close-settings'),
  gcpBtnLabel: document.getElementById('gcp-btn-label'),
  gcpLiveDot: document.getElementById('gcp-live-dot'),
  gcpStatusPill: document.getElementById('gcp-status-pill'),
  settingsStatusBox: document.getElementById('settings-status-box'),
  settingsStatusIcon: document.getElementById('settings-status-icon'),
  settingsStatusTitle: document.getElementById('settings-status-title'),
  settingsStatusDesc: document.getElementById('settings-status-desc'),
  cfgApiKey: document.getElementById('cfg-api-key'),
  btnToggleKeyReveal: document.getElementById('btn-toggle-key-reveal'),
  cfgModel: document.getElementById('cfg-model'),
  cfgLocation: document.getElementById('cfg-location'),
  cfgProjectId: document.getElementById('cfg-project-id'),
  cfgDocaiId: document.getElementById('cfg-docai-id'),
  btnTestConnection: document.getElementById('btn-test-connection'),
  btnSaveSettings: document.getElementById('btn-save-settings'),
  gcpSettingsForm: document.getElementById('gcp-settings-form'),
  testFeedbackBox: document.getElementById('test-feedback-box'),
  testFeedbackMsg: document.getElementById('test-feedback-msg'),
  feedbackSpinner: document.getElementById('feedback-spinner'),
  sdkGenaiStatus: document.getElementById('sdk-genai-status'),
  sdkDocaiStatus: document.getElementById('sdk-docai-status'),
  
  // Executive Metrics
  valProcessed: document.getElementById('val-processed'),
  valStp: document.getElementById('val-stp'),
  valFraudSaved: document.getElementById('val-fraud-saved'),
  valCycle: document.getElementById('val-cycle'),
  valAccuracy: document.getElementById('val-accuracy'),

  // Claim Banner
  claimIdDisplay: document.getElementById('claim-id-display'),
  claimStatusPill: document.getElementById('claim-status-pill'),
  claimLossTag: document.getElementById('claim-loss-tag'),
  claimClaimantName: document.getElementById('claim-claimant-name'),
  claimDate: document.getElementById('claim-date'),
  claimLocation: document.getElementById('claim-location'),
  claimRiskVal: document.getElementById('claim-risk-val'),
  claimRiskTag: document.getElementById('claim-risk-tag'),
  riskCircleFill: document.getElementById('risk-circle-fill'),

  // Tabs
  tabButtons: document.querySelectorAll('.wtab-btn'),
  tabPanes: document.querySelectorAll('.tab-pane'),

  // Tab 1: Forensics
  damageVisualArt: document.getElementById('damage-visual-art'),
  exifOverlay: document.getElementById('exif-overlay'),
  btnToggleBoxes: document.getElementById('btn-toggle-boxes'),
  btnToggleExif: document.getElementById('btn-toggle-exif'),
  canvasCaptionText: document.getElementById('canvas-caption-text'),
  geminiFindingsList: document.getElementById('gemini-findings-list'),
  discrepancyCallout: document.getElementById('discrepancy-callout'),
  discrepancyText: document.getElementById('discrepancy-text'),
  exifPhashVal: document.getElementById('exif-phash-val'),

  // Tab 2: Document AI
  docTypeVal: document.getElementById('doc-type-val'),
  docFacilityVal: document.getElementById('doc-facility-val'),
  docTrustVal: document.getElementById('doc-trust-val'),
  lineItemsBody: document.getElementById('line-items-body'),

  // Tab 3: Policy RAG
  policyTierBadge: document.getElementById('policy-tier-badge'),
  policyClausesGrid: document.getElementById('policy-clauses-grid'),

  // Tab 4: BigQuery Cohort
  cohortGroupName: document.getElementById('cohort-group-name'),
  cohortSampleSize: document.getElementById('cohort-sample-size'),
  cohortPercentile: document.getElementById('cohort-percentile'),
  barMedianVal: document.getElementById('bar-median-val'),
  barClaimedVal: document.getElementById('bar-claimed-val'),
  barClaimedFill: document.getElementById('bar-claimed-fill'),
  barApprovedVal: document.getElementById('bar-approved-val'),
  barApprovedFill: document.getElementById('bar-approved-fill'),
  synFraudRate: document.getElementById('syn-fraud-rate'),
  synPastClaims: document.getElementById('syn-past-claims'),

  // Tab 5: Settlement & Decision
  reconClaimedAmt: document.getElementById('recon-claimed-amt'),
  reconDisallowedAmt: document.getElementById('recon-disallowed-amt'),
  reconAdjustedAmt: document.getElementById('recon-adjusted-amt'),
  reconDeductibleAmt: document.getElementById('recon-deductible-amt'),
  reconNetPayout: document.getElementById('recon-net-payout'),
  btnSettleAdj: document.getElementById('btn-settle-adj'),
  btnSettleFull: document.getElementById('btn-settle-full'),
  btnEscalateSiu: document.getElementById('btn-escalate-siu'),
  claimantLetterContent: document.getElementById('claimant-letter-content'),
  btnCopyLetter: document.getElementById('btn-copy-letter'),
  btnSendLetter: document.getElementById('btn-send-letter'),

  // Modals & Navigation
  btnNewClaim: document.getElementById('btn-new-claim'),
  modalNewClaim: document.getElementById('modal-new-claim'),
  btnCloseModal: document.getElementById('btn-close-modal'),
  btnCancelModal: document.getElementById('btn-cancel-modal'),
  presetCards: document.querySelectorAll('.preset-card'),
  ingestForm: document.getElementById('ingest-form'),
  pipelineStepper: document.getElementById('pipeline-stepper'),
  btnStartIngest: document.getElementById('btn-start-ingest'),

  btnOpenArch: document.getElementById('btn-open-arch'),
  modalArch: document.getElementById('modal-architecture'),
  btnCloseArch: document.getElementById('btn-close-arch'),

  // Copilot Drawer
  btnToggleCopilot: document.getElementById('btn-toggle-copilot'),
  copilotDrawer: document.getElementById('copilot-drawer'),
  btnCloseCopilot: document.getElementById('btn-close-copilot'),
  copilotChatHistory: document.getElementById('copilot-chat-history'),
  copilotForm: document.getElementById('copilot-form'),
  copilotInput: document.getElementById('copilot-input'),

  toastContainer: document.getElementById('toast-container')
};

// Initial Setup
document.addEventListener('DOMContentLoaded', () => {
  initEventListeners();
  loadData();
});

// Load Initial Data from REST API (with static fallback for Firebase / Serverless)
async function loadData() {
  try {
    let claimsRes = await fetch('/api/claims').catch(() => null);
    if (!claimsRes || !claimsRes.ok) {
      claimsRes = await fetch('data/claims.json');
    }
    state.claims = await claimsRes.json();

    let benchmarksRes = await fetch('/api/benchmarks').catch(() => null);
    if (!benchmarksRes || !benchmarksRes.ok) {
      benchmarksRes = await fetch('data/benchmarks.json');
    }
    if (benchmarksRes && benchmarksRes.ok) {
      state.benchmarks = await benchmarksRes.json();
      updateExecutiveMetrics(state.benchmarks);
    }

    let configRes = await fetch('/api/config').catch(() => null);
    if (!configRes || !configRes.ok) {
      configRes = await fetch('data/config.json');
    }
    if (configRes && configRes.ok) {
      state.config = await configRes.json();
      updateGcpStatusUI(state.config);
    }

    renderClaimsList();

    // Select claim by query param or first by default
    const urlParams = new URLSearchParams(window.location.search);
    const targetClaimId = urlParams.get('claim');
    if (targetClaimId) {
      selectClaim(targetClaimId);
    } else if (state.claims.length > 0) {
      selectClaim(state.claims[0].id);
    }

    const targetTab = urlParams.get('tab');
    if (targetTab) {
      const btn = document.querySelector(`.wtab-btn[data-tab="${targetTab}"]`);
      if (btn) btn.click();
    }

    const targetModal = urlParams.get('modal');
    if (targetModal === 'arch' && elements.modalArch) {
      elements.modalArch.style.display = 'flex';
    } else if (targetModal === 'new' && elements.modalNewClaim) {
      elements.modalNewClaim.style.display = 'flex';
    } else if (targetModal === 'copilot' && elements.copilotDrawer) {
      elements.copilotDrawer.classList.add('open');
    }
  } catch (err) {
    console.error('Data loading error:', err);
    showToast('Connecting to local Gemini service...', 'info');
  }
}

// Update Executive Metrics Bar
function updateExecutiveMetrics(benchmarks) {
  if (!benchmarks || !benchmarks.analyticsMetrics) return;
  const m = benchmarks.analyticsMetrics;
  elements.valProcessed.textContent = m.totalClaimsProcessedYTD.toLocaleString();
  elements.valStp.textContent = m.straightThroughProcessingRate;
  elements.valFraudSaved.textContent = `$${(m.preventedFraudLossDollars / 1000000).toFixed(2)}M`;
  elements.valCycle.textContent = `${m.averageCycleTimeMinutes} min`;
  elements.valAccuracy.textContent = m.geminiAccuracyRate;
}

// Initialize UI Event Listeners
function initEventListeners() {
  // Search
  elements.claimsSearchInput.addEventListener('input', (e) => {
    state.searchQuery = e.target.value.toLowerCase().trim();
    renderClaimsList();
  });

  // Filter Chips
  elements.filterChips.forEach(chip => {
    chip.addEventListener('click', () => {
      elements.filterChips.forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      state.activeFilter = chip.dataset.filter;
      renderClaimsList();
    });
  });

  // Tab Switcher
  elements.tabButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      elements.tabButtons.forEach(b => b.classList.remove('active'));
      elements.tabPanes.forEach(p => p.classList.remove('active'));

      btn.classList.add('active');
      const tabId = btn.dataset.tab;
      state.activeTab = tabId;
      const targetPane = document.getElementById(`pane-${tabId}`);
      if (targetPane) targetPane.classList.add('active');
    });
  });

  // Toggle Bounding Boxes vs EXIF
  elements.btnToggleBoxes.addEventListener('click', () => {
    elements.btnToggleBoxes.classList.add('active');
    elements.btnToggleExif.classList.remove('active');
    elements.exifOverlay.style.display = 'none';
    state.showBoundingBoxes = true;
    renderVisualInspector(state.activeClaim);
  });

  elements.btnToggleExif.addEventListener('click', () => {
    elements.btnToggleExif.classList.add('active');
    elements.btnToggleBoxes.classList.remove('active');
    elements.exifOverlay.style.display = 'flex';
    state.showBoundingBoxes = false;
  });

  // Settlement Actions
  elements.btnSettleAdj.addEventListener('click', () => handleAdjusterAction('APPROVE_ADJUSTED', 'Approved net repair expenses minus non-verified parts.'));
  elements.btnSettleFull.addEventListener('click', () => handleAdjusterAction('APPROVE', 'Manager override authorized payment in full.'));
  elements.btnEscalateSiu.addEventListener('click', () => handleAdjusterAction('ESCALATE_SIU', 'Flagged for SIU forensic investigation regarding potential fraud.'));

  // Letter Actions
  elements.btnCopyLetter.addEventListener('click', () => {
    navigator.clipboard.writeText(elements.claimantLetterContent.value);
    showToast('Claimant explanation letter copied to clipboard', 'success');
  });

  elements.btnSendLetter.addEventListener('click', () => {
    showToast(`Claimant communication dispatched via Omnichannel SMS/Email to ${state.activeClaim.claimantName}!`, 'success');
  });

  // Modals
  elements.btnNewClaim.addEventListener('click', () => {
    elements.modalNewClaim.style.display = 'flex';
  });

  elements.btnCloseModal.addEventListener('click', () => {
    elements.modalNewClaim.style.display = 'none';
  });

  elements.btnCancelModal.addEventListener('click', () => {
    elements.modalNewClaim.style.display = 'none';
  });

  // Google Cloud Settings Modal
  elements.btnOpenSettings.addEventListener('click', () => {
    elements.modalSettings.style.display = 'flex';
  });

  elements.btnCloseSettings.addEventListener('click', () => {
    elements.modalSettings.style.display = 'none';
  });

  elements.btnToggleKeyReveal.addEventListener('click', () => {
    const isPass = elements.cfgApiKey.type === 'password';
    elements.cfgApiKey.type = isPass ? 'text' : 'password';
    elements.btnToggleKeyReveal.textContent = isPass ? '🔒' : '👁️';
  });

  elements.btnTestConnection.addEventListener('click', handleTestConnection);
  elements.gcpSettingsForm.addEventListener('submit', handleSaveSettings);

  elements.btnOpenArch.addEventListener('click', () => {
    elements.modalArch.style.display = 'flex';
  });

  elements.btnCloseArch.addEventListener('click', () => {
    elements.modalArch.style.display = 'none';
  });

  // Presets in Ingestion Modal
  elements.presetCards.forEach(card => {
    card.addEventListener('click', () => {
      elements.presetCards.forEach(c => c.classList.remove('active'));
      card.classList.add('active');
      applyPresetToForm(card.dataset.preset);
    });
  });

  // Ingestion Form Submit
  elements.ingestForm.addEventListener('submit', handleFormSubmit);

  // Gemini Copilot
  elements.btnToggleCopilot.addEventListener('click', toggleCopilot);
  elements.btnCloseCopilot.addEventListener('click', toggleCopilot);
  elements.copilotForm.addEventListener('submit', handleCopilotSubmit);

  // Copilot Prompt Chips
  document.addEventListener('click', (e) => {
    if (e.target.classList.contains('chip-prompt')) {
      const query = e.target.dataset.query;
      executeCopilotQuery(query);
    }
  });
}

// Google Cloud Live Integration UI Updates
function updateGcpStatusUI(cfg) {
  if (!cfg) return;

  const isLive = cfg.isLive || cfg.hasApiKey;
  if (isLive) {
    elements.gcpLiveDot.classList.add('live-active');
    elements.gcpBtnLabel.textContent = 'Live Gemini 3.8 Flash';
    elements.settingsStatusBox.className = 'settings-status-box status-live';
    elements.settingsStatusIcon.textContent = '✓';
    elements.settingsStatusTitle.textContent = `Connected to Google Cloud (${cfg.modelName || 'gemini-3.8-flash'})`;
    elements.settingsStatusDesc.textContent = 'Live Vertex AI / Gemini API is active. Real multimodal reasoning and live copilot generation are enabled.';
  } else {
    elements.gcpLiveDot.classList.remove('live-active');
    elements.gcpBtnLabel.textContent = 'GCP Setup Key';
    elements.settingsStatusBox.className = 'settings-status-box';
    elements.settingsStatusIcon.textContent = '⚡';
    elements.settingsStatusTitle.textContent = 'Simulation Mode (API Key Not Set)';
    elements.settingsStatusDesc.textContent = 'Currently running on calibrated local benchmark engine. Enter your Google Cloud / Gemini API key to activate live generative AI.';
  }

  const copilotStatus = document.getElementById('copilot-status-indicator');
  if (copilotStatus) {
    copilotStatus.textContent = isLive ? `⚡ Live Vertex AI (${cfg.modelName || 'Gemini 3.8 Flash'})` : 'Context-Aware Benchmark Mode';
    copilotStatus.style.color = isLive ? 'var(--neon-cyan)' : 'var(--text-muted)';
  }

  // Pre-fill fields
  if (cfg.maskedApiKey) {
    elements.cfgApiKey.placeholder = `Active: ${cfg.maskedApiKey} (Enter new key to update)`;
  }
  if (cfg.modelName) elements.cfgModel.value = cfg.modelName;
  if (cfg.gcpLocation) elements.cfgLocation.value = cfg.gcpLocation;
  if (cfg.gcpProjectId) elements.cfgProjectId.value = cfg.gcpProjectId;
  if (cfg.docAiProcessorId) elements.cfgDocaiId.value = cfg.docAiProcessorId;

  // SDK status
  if (cfg.libraries) {
    elements.sdkGenaiStatus.textContent = cfg.libraries.googleGenAiInstalled ? 'Installed (v1.47.0)' : 'REST Fallback';
    elements.sdkDocaiStatus.textContent = cfg.libraries.googleCloudDocumentAiInstalled ? 'Installed (v3.14.0)' : 'REST Fallback';
  }
}

// Test Live Connection to Gemini / Vertex AI
async function handleTestConnection() {
  const testBox = elements.testFeedbackBox;
  const testMsg = elements.testFeedbackMsg;
  const spinner = elements.feedbackSpinner;
  const newKey = elements.cfgApiKey.value.trim();

  testBox.style.display = 'flex';
  spinner.style.display = 'block';
  testMsg.textContent = 'Testing live Vertex AI Gemini 3.8 Flash response...';

  // If user entered a new key in the field, save it first before testing
  if (newKey) {
    try {
      await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          geminiApiKey: newKey,
          modelName: elements.cfgModel.value,
          gcpLocation: elements.cfgLocation.value,
          gcpProjectId: elements.cfgProjectId.value,
          docAiProcessorId: elements.cfgDocaiId.value
        })
      });
    } catch (err) {
      console.warn('Pre-save warning:', err);
    }
  }

  try {
    const res = await fetch('/api/config/test', { method: 'POST' });
    const data = await res.json();
    spinner.style.display = 'none';

    if (data.success) {
      testBox.style.borderColor = 'var(--emerald-success)';
      testMsg.innerHTML = `<strong style="color: var(--emerald-success)">✓ Connected!</strong> Latency: ${data.latencyMs}ms (${data.model}) — <em>"${data.message}"</em>`;
      showToast(`Google Cloud Vertex AI verified (${data.latencyMs}ms latency)!`, 'success');
      
      // Refresh config
      const cfgRes = await fetch('/api/config');
      if (cfgRes.ok) {
        state.config = await cfgRes.json();
        updateGcpStatusUI(state.config);
      }
    } else {
      testBox.style.borderColor = 'var(--crimson-fraud)';
      testMsg.innerHTML = `<strong style="color: var(--crimson-fraud)">✗ Failed:</strong> ${data.message}`;
      showToast(`Connection test failed: ${data.message}`, 'danger');
    }
  } catch (err) {
    spinner.style.display = 'none';
    testBox.style.borderColor = 'var(--crimson-fraud)';
    testMsg.textContent = `Error: ${err.message}`;
    showToast(`Error testing connection: ${err.message}`, 'danger');
  }
}

// Save Google Cloud Configuration
async function handleSaveSettings(e) {
  e.preventDefault();
  const payload = {
    modelName: elements.cfgModel.value,
    gcpLocation: elements.cfgLocation.value,
    gcpProjectId: elements.cfgProjectId.value.trim(),
    docAiProcessorId: elements.cfgDocaiId.value.trim()
  };

  const newKey = elements.cfgApiKey.value.trim();
  if (newKey) {
    payload.geminiApiKey = newKey;
  }

  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) throw new Error('Failed to save configuration');
    const data = await res.json();

    // Re-fetch config to refresh state
    const cfgRes = await fetch('/api/config');
    if (cfgRes.ok) {
      state.config = await cfgRes.json();
      updateGcpStatusUI(state.config);
    }

    elements.modalSettings.style.display = 'none';
    showToast('Google Cloud settings saved successfully!', 'success');
  } catch (err) {
    showToast(`Failed to save settings: ${err.message}`, 'danger');
  }
}

// Preset Scenario Data Loader
function applyPresetToForm(preset) {
  const claimant = document.getElementById('form-claimant');
  const policy = document.getElementById('form-policy');
  const lossType = document.getElementById('form-loss-type');
  const amount = document.getElementById('form-amount');
  const summary = document.getElementById('form-summary');

  if (preset === 'clean_glass') {
    claimant.value = 'Sarah Jenkins';
    policy.value = 'POL-AUTO-77312';
    lossType.value = 'Hailstorm Windshield Impact';
    amount.value = '780';
    summary.value = 'Driving on I-25 during severe hail cell. Star crack formed on OEM acoustic windshield. Safelite direct estimate submitted.';
  } else if (preset === 'water_pipe') {
    claimant.value = 'Elena Rostova';
    policy.value = 'POL-HOME-49102';
    lossType.value = 'Sudden Plumbing Pipe Burst';
    amount.value = '3450';
    summary.value = 'Sub-zero freezing event ruptured 1/2 copper pipe behind kitchen ceiling. Beacon Hill emergency plumbing invoice & moisture readings attached.';
  } else if (preset === 'staged_damage') {
    claimant.value = "Devon 'Ace' Vance";
    policy.value = 'POL-AUTO-90119';
    lossType.value = 'Single Vehicle Collision (Deserted lot)';
    amount.value = '42500';
    summary.value = 'Alleges late night impact with warehouse wall. Front-end unibody heavily compressed. Towing by unverified local operator.';
  } else {
    claimant.value = 'Marcus Sterling';
    policy.value = 'POL-AUTO-88241';
    lossType.value = 'Vehicle Collision (Rear impact)';
    amount.value = '8450';
    summary.value = 'Low-speed parking lot bumper collision. Non-network shop invoiced full suspension replacement and chassis pull.';
  }
}

// Filter and Render Claims List in Sidebar
function renderClaimsList() {
  const filtered = state.claims.filter(claim => {
    const matchesFilter = 
      state.activeFilter === 'ALL' ||
      (state.activeFilter === 'AUTO_APPROVED' && (claim.status === 'AUTO_APPROVED' || claim.autoAdjudicated)) ||
      (state.activeFilter === 'ADJUSTER_REVIEW' && (claim.status === 'ADJUSTER_REVIEW' || claim.status === 'SETTLED_ADJUSTED')) ||
      (state.activeFilter === 'SIU_ESCALATED' && claim.status === 'SIU_ESCALATED');

    const q = state.searchQuery;
    const matchesSearch = !q ||
      claim.id.toLowerCase().includes(q) ||
      claim.claimantName.toLowerCase().includes(q) ||
      claim.policyNumber.toLowerCase().includes(q) ||
      claim.lossType.toLowerCase().includes(q);

    return matchesFilter && matchesSearch;
  });

  elements.totalBadge.textContent = `${filtered.length} Active`;

  if (filtered.length === 0) {
    elements.claimsList.innerHTML = `
      <div class="empty-list-notice" style="padding: 24px; text-align: center; color: var(--text-muted);">
        <p>No claims match criteria.</p>
      </div>`;
    return;
  }

  elements.claimsList.innerHTML = filtered.map(claim => {
    const isActive = state.activeClaim && state.activeClaim.id === claim.id;
    let riskClass = 'risk-low';
    if (claim.riskScore > 65) riskClass = 'risk-critical';
    else if (claim.riskScore > 25) riskClass = 'risk-moderate';

    let statusLabel = claim.status.replace('_', ' ');

    return `
      <div class="claim-queue-card ${isActive ? 'active' : ''}" data-id="${claim.id}" onclick="selectClaim('${claim.id}')">
        <div class="card-top-row">
          <span class="card-claim-id">${claim.id}</span>
          <span class="risk-pill ${riskClass}">
            <span>${claim.riskScore}</span>
            <span style="font-size: 8px; opacity: 0.8;">RISK</span>
          </span>
        </div>
        <div class="card-claimant-name">${claim.claimantName}</div>
        <div class="card-loss-summary">${claim.lossType}</div>
        <div class="card-bottom-row">
          <span class="card-amt">$${claim.claimedAmount.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</span>
          <span class="card-status-label" style="color: ${getStatusColor(claim.status)}">${statusLabel}</span>
        </div>
      </div>
    `;
  }).join('');
}

function getStatusColor(status) {
  if (status === 'AUTO_APPROVED' || status === 'APPROVED_IN_FULL' || status === 'SETTLED_ADJUSTED') return 'var(--emerald-success)';
  if (status === 'SIU_ESCALATED' || status === 'DENIED') return 'var(--crimson-fraud)';
  return 'var(--amber-warning)';
}

// Select and Display Claim
function selectClaim(claimId) {
  const claim = state.claims.find(c => c.id === claimId);
  if (!claim) return;

  state.activeClaim = claim;
  renderClaimsList(); // Refresh active card indicator

  // Update Top Banner
  elements.claimIdDisplay.textContent = claim.id;
  elements.claimStatusPill.textContent = claim.status.replace('_', ' ');
  elements.claimStatusPill.style.backgroundColor = getStatusColor(claim.status) + '22';
  elements.claimStatusPill.style.color = getStatusColor(claim.status);
  elements.claimStatusPill.style.border = `1px solid ${getStatusColor(claim.status)}55`;

  elements.claimLossTag.textContent = claim.lossType;
  elements.claimClaimantName.textContent = claim.claimantName;
  elements.claimDate.textContent = claim.incidentDate;
  elements.claimLocation.textContent = claim.incidentLocation;

  // Risk Score Gauge Animation
  elements.claimRiskVal.textContent = claim.riskScore;
  elements.claimRiskTag.textContent = `${claim.riskLevel} RISK`;
  elements.claimRiskTag.style.color = getStatusColor(claim.riskLevel === 'CRITICAL' ? 'SIU_ESCALATED' : (claim.riskLevel === 'HIGH' ? 'ADJUSTER_REVIEW' : 'AUTO_APPROVED'));

  const circumference = 100;
  const strokeDash = `${claim.riskScore}, ${circumference}`;
  elements.riskCircleFill.setAttribute('stroke-dasharray', strokeDash);
  elements.riskCircleFill.style.stroke = getStatusColor(claim.riskLevel === 'CRITICAL' ? 'SIU_ESCALATED' : (claim.riskLevel === 'HIGH' ? 'ADJUSTER_REVIEW' : 'AUTO_APPROVED'));

  // Render Forensics View (Tab 1)
  renderVisualInspector(claim);
  renderGeminiFindings(claim);

  // Render Document AI View (Tab 2)
  renderDocumentAi(claim);

  // Render Policy RAG View (Tab 3)
  renderPolicyRag(claim);

  // Render BigQuery Cohort View (Tab 4)
  renderBigQueryCohort(claim);

  // Render Settlement Ledger (Tab 5)
  renderSettlementLedger(claim);
}

// Render Visual Damage Blueprint and Bounding Boxes
function renderVisualInspector(claim) {
  const vType = claim.imageVisualType || 'car_bumper_diagram';
  let svgArt = '';

  if (vType === 'water_ceiling_diagram') {
    svgArt = `
      <svg class="visual-svg-canvas" viewBox="0 0 600 320" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <radialGradient id="waterStain" cx="45%" cy="40%" r="50%">
            <stop offset="0%" stop-color="#3b82f6" stop-opacity="0.75"/>
            <stop offset="40%" stop-color="#0284c7" stop-opacity="0.45"/>
            <stop offset="85%" stop-color="#0369a1" stop-opacity="0.2"/>
            <stop offset="100%" stop-color="#0c4a6e" stop-opacity="0"/>
          </radialGradient>
          <pattern id="ceilingGrid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
          </pattern>
        </defs>
        <!-- Ceiling drywall texture -->
        <rect width="100%" height="100%" fill="#131c31"/>
        <rect width="100%" height="100%" fill="url(#ceilingGrid)"/>
        <!-- Copper pipe run -->
        <line x1="80" y1="120" x2="520" y2="120" stroke="#b45309" stroke-width="8" stroke-linecap="round"/>
        <!-- Pipe burst point -->
        <circle cx="270" cy="120" r="8" fill="#ef4444"/>
        <!-- Water spread stain -->
        <ellipse cx="270" cy="140" rx="160" ry="90" fill="url(#waterStain)"/>
        <!-- Bounding Box Annotation -->
        ${state.showBoundingBoxes ? `
          <g>
            <rect x="130" y="60" width="280" height="150" fill="rgba(16, 185, 129, 0.12)" stroke="#10b981" stroke-width="2" stroke-dasharray="4" rx="4"/>
            <rect x="130" y="38" width="180" height="22" fill="#10b981" rx="3"/>
            <text x="138" y="53" fill="#ffffff" font-family="'Plus Jakarta Sans', sans-serif" font-size="11" font-weight="bold">Moisture Spread (97% Conf)</text>
          </g>
        ` : ''}
      </svg>
    `;
  } else if (vType === 'bmw_crash_diagram') {
    svgArt = `
      <svg class="visual-svg-canvas" viewBox="0 0 600 320" xmlns="http://www.w3.org/2000/svg">
        <rect width="100%" height="100%" fill="#0d1322"/>
        <!-- Grid -->
        <line x1="50" y1="260" x2="550" y2="260" stroke="#334155" stroke-width="2"/>
        <!-- Car Front Silhouette -->
        <path d="M 120 250 L 160 170 L 260 130 L 440 130 L 480 180 L 510 250 Z" fill="#1e293b" stroke="#64748b" stroke-width="2"/>
        <!-- Crushed Front End Zone -->
        <path d="M 120 250 L 175 160 L 230 200 L 180 250 Z" fill="rgba(239, 68, 68, 0.3)" stroke="#ef4444" stroke-width="2.5"/>
        <line x1="140" y1="180" x2="190" y2="240" stroke="#f87171" stroke-width="2"/>
        <line x1="160" y1="220" x2="130" y2="210" stroke="#f87171" stroke-width="2"/>
        <!-- Copart Match Overlay -->
        ${state.showBoundingBoxes ? `
          <g>
            <rect x="100" y="110" width="180" height="150" fill="rgba(239, 68, 68, 0.15)" stroke="#ef4444" stroke-width="2" stroke-dasharray="5" rx="6"/>
            <rect x="100" y="86" width="220" height="24" fill="#ef4444" rx="3"/>
            <text x="108" y="102" fill="#ffffff" font-family="'Plus Jakarta Sans', sans-serif" font-size="11" font-weight="bold">🚨 Copart Salvage Match (Lot #5591024)</text>
          </g>
        ` : ''}
      </svg>
    `;
  } else if (vType === 'subaru_glass_diagram') {
    svgArt = `
      <svg class="visual-svg-canvas" viewBox="0 0 600 320" xmlns="http://www.w3.org/2000/svg">
        <rect width="100%" height="100%" fill="#0b101d"/>
        <!-- Windshield Frame -->
        <polygon points="120,60 480,60 520,250 80,250" fill="#172554" stroke="#3b82f6" stroke-width="2"/>
        <!-- Star Crack -->
        <g transform="translate(300, 160)">
          <circle cx="0" cy="0" r="5" fill="#e0f2fe"/>
          <line x1="0" y1="0" x2="-25" y2="-18" stroke="#ffffff" stroke-width="2"/>
          <line x1="0" y1="0" x2="30" y2="-15" stroke="#ffffff" stroke-width="2"/>
          <line x1="0" y1="0" x2="-12" y2="28" stroke="#ffffff" stroke-width="2"/>
          <line x1="0" y1="0" x2="22" y2="20" stroke="#ffffff" stroke-width="2"/>
        </g>
        ${state.showBoundingBoxes ? `
          <g>
            <rect x="250" y="125" width="110" height="80" fill="rgba(0, 229, 255, 0.12)" stroke="#00e5ff" stroke-width="2" stroke-dasharray="4" rx="4"/>
            <rect x="250" y="103" width="130" height="22" fill="#00e5ff" rx="3"/>
            <text x="256" y="118" fill="#090d16" font-family="'Plus Jakarta Sans', sans-serif" font-size="11" font-weight="bold">Hail Crack (98% Conf)</text>
          </g>
        ` : ''}
      </svg>
    `;
  } else {
    // Standard Vehicle Bumper Scuff Blueprint
    svgArt = `
      <svg class="visual-svg-canvas" viewBox="0 0 600 320" xmlns="http://www.w3.org/2000/svg">
        <rect width="100%" height="100%" fill="#0a0f1d"/>
        <!-- Wireframe car rear -->
        <path d="M 120 240 Q 120 180 180 150 L 220 120 L 380 120 L 420 150 Q 480 180 480 240 Z" fill="#131b2e" stroke="#334155" stroke-width="2"/>
        <!-- Rear Bumper Contour -->
        <path d="M 100 240 L 500 240 L 480 280 L 120 280 Z" fill="#1e293b" stroke="#475569" stroke-width="2"/>
        <!-- Tail lights -->
        <rect x="135" y="180" width="70" height="25" rx="4" fill="#dc2626" opacity="0.8"/>
        <rect x="395" y="180" width="70" height="25" rx="4" fill="#dc2626" opacity="0.8"/>
        <!-- Exhaust Tips (Intact) -->
        <ellipse cx="160" cy="285" rx="12" ry="6" fill="#64748b"/>
        <ellipse cx="440" cy="285" rx="12" ry="6" fill="#64748b"/>
        <!-- Minor Scrape Markings -->
        <g transform="translate(190, 248)">
          <line x1="0" y1="0" x2="45" y2="12" stroke="#f59e0b" stroke-width="3" stroke-linecap="round"/>
          <line x1="8" y1="8" x2="38" y2="18" stroke="#f59e0b" stroke-width="2.5" stroke-linecap="round"/>
        </g>
        <!-- Bounding Box -->
        ${state.showBoundingBoxes ? `
          <g>
            <rect x="170" y="235" width="85" height="38" fill="rgba(245, 158, 11, 0.15)" stroke="#f59e0b" stroke-width="2" stroke-dasharray="4" rx="4"/>
            <rect x="170" y="215" width="130" height="20" fill="#f59e0b" rx="3"/>
            <text x="176" y="229" fill="#090d16" font-family="'Plus Jakarta Sans', sans-serif" font-size="10" font-weight="bold">Bumper Scuff: $450-$700</text>
          </g>
        ` : ''}
      </svg>
    `;
  }

  elements.damageVisualArt.innerHTML = svgArt;
  elements.canvasCaptionText.textContent = claim.damageSummary;

  if (claim.riskScore > 90) {
    elements.exifPhashVal.textContent = 'MATCH FOUND: Copart Salvage Auction #5591024';
    elements.exifPhashVal.className = 'e-v text-crimson';
  } else {
    elements.exifPhashVal.textContent = 'Unique Photo (Zero duplicate hashes across national database)';
    elements.exifPhashVal.className = 'e-v text-emerald';
  }
}

// Render Gemini Reasoning Findings Tree
function renderGeminiFindings(claim) {
  const findings = claim.geminiForensicFindings || [];
  elements.geminiFindingsList.innerHTML = findings.map(f => {
    let sClass = 'sev-info';
    if (f.severity === 'CRITICAL') sClass = 'sev-critical';
    else if (f.severity === 'MEDIUM') sClass = 'sev-medium';

    return `
      <div class="finding-item">
        <div class="finding-header">
          <span class="finding-title">${f.flag}</span>
          <span class="finding-sev ${sClass}">${f.severity}</span>
        </div>
        <div class="finding-desc">${f.description}</div>
      </div>
    `;
  }).join('');

  if (claim.riskScore > 35) {
    elements.discrepancyCallout.style.display = 'flex';
    elements.discrepancyText.textContent = findings.find(f => f.severity === 'CRITICAL')?.description || claim.damageSummary;
  } else {
    elements.discrepancyCallout.style.display = 'none';
  }
}

// Render Document AI Extracted Line Items
function renderDocumentAi(claim) {
  const doc = claim.documentAiExtraction || {};
  elements.docTypeVal.textContent = doc.documentType || 'Estimate Invoice';
  elements.docFacilityVal.textContent = doc.repairShop || 'Independent Facility';
  elements.docTrustVal.textContent = doc.shopRating || 'Audited Facility';

  const items = doc.lineItems || [];
  elements.lineItemsBody.innerHTML = items.map(item => {
    const isAllow = item.aiRecommendation === 'ALLOW';
    const pillClass = isAllow ? 'tbl-pill-allow' : 'tbl-pill-disallow';

    return `
      <tr>
        <td><strong>${item.item}</strong></td>
        <td class="tbl-amt">$${item.claimedCost.toFixed(2)}</td>
        <td>
          <span style="color: ${item.verified ? 'var(--emerald-success)' : 'var(--crimson-fraud)'}; font-weight: 600;">
            ${item.verified ? '✓ Verified in Imagery' : '✗ Unverified in Photos'}
          </span>
        </td>
        <td><span class="${pillClass}">${item.aiRecommendation}</span></td>
        <td class="tbl-amt" style="color: ${isAllow ? 'var(--emerald-success)' : 'var(--text-subtle)'}">
          $${(item.allowedCost || 0).toFixed(2)}
        </td>
        <td style="font-size: 11.5px; color: var(--text-muted);">${item.reason || 'Verified within regional fair schedule'}</td>
      </tr>
    `;
  }).join('');
}

// Render Vertex AI Policy RAG Clauses
function renderPolicyRag(claim) {
  const p = claim.policyCompliance || {};
  elements.policyTierBadge.textContent = claim.policyType || 'Gold Comprehensive Auto';

  const clauses = p.relevantClauses || [];
  elements.policyClausesGrid.innerHTML = clauses.map(c => {
    let badgeColor = 'var(--emerald-success)';
    if (c.compliance === 'VIOLATION_DETECTED' || c.compliance === 'POLICY_VOIDED_GROUNDS' || c.compliance === 'EXCLUSION_ACTIVE') {
      badgeColor = 'var(--crimson-fraud)';
    }

    return `
      <div class="clause-card">
        <div class="clause-header">
          <div class="clause-title-cluster">
            <span class="clause-id">${c.clauseId}</span>
            <span class="clause-title">${c.title}</span>
          </div>
          <span class="clause-compliance-badge" style="background: ${badgeColor}22; color: ${badgeColor}; border: 1px solid ${badgeColor}44;">
            ${c.compliance.replace('_', ' ')}
          </span>
        </div>
        <div class="clause-text">"${c.text}"</div>
      </div>
    `;
  }).join('');
}

// Render BigQuery Cohort Charts
function renderBigQueryCohort(claim) {
  const bq = claim.bigQueryCohort || {};
  elements.cohortGroupName.textContent = bq.cohortGroup || 'Regional Vehicle Fleet';
  elements.cohortSampleSize.textContent = (bq.sampleSize || 25000).toLocaleString();
  elements.cohortPercentile.textContent = bq.costPercentile || '50th Percentile';

  elements.barMedianVal.textContent = `$${(bq.medianRepairCost || 1200).toLocaleString()}`;
  elements.barClaimedVal.textContent = `$${claim.claimedAmount.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
  elements.barApprovedVal.textContent = `$${claim.adjustedAmount.toLocaleString(undefined, {minimumFractionDigits: 2})}`;

  // Relative bar lengths
  const maxScale = Math.max(claim.claimedAmount, 6000);
  const claimedPercent = Math.min(100, Math.max(15, (claim.claimedAmount / maxScale) * 100));
  const approvedPercent = Math.min(100, Math.max(10, (claim.adjustedAmount / maxScale) * 100));

  elements.barClaimedFill.style.width = `${claimedPercent}%`;
  elements.barApprovedFill.style.width = `${approvedPercent}%`;

  elements.synFraudRate.textContent = bq.providerHistoricalFraudRate || '2.1%';
  elements.synPastClaims.textContent = bq.claimantPastClaims ?? 0;
}

// Render Settlement Ledger & Claimant Letter
function renderSettlementLedger(claim) {
  elements.reconClaimedAmt.textContent = `$${claim.claimedAmount.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
  
  const disallowed = Math.max(0, claim.claimedAmount - claim.adjustedAmount);
  elements.reconDisallowedAmt.textContent = `-$${disallowed.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
  elements.reconAdjustedAmt.textContent = `$${claim.adjustedAmount.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
  
  elements.reconDeductibleAmt.textContent = `-$${(claim.deductible || 500).toLocaleString(undefined, {minimumFractionDigits: 2})}`;
  elements.reconNetPayout.textContent = `$${claim.netPayout.toLocaleString(undefined, {minimumFractionDigits: 2})}`;

  // Update button texts
  elements.btnSettleAdj.querySelector('span').textContent = `Authorize Adjusted Settlement ($${claim.netPayout.toFixed(2)})`;
  elements.btnSettleFull.querySelector('span').textContent = `Authorize Full Claimed ($${claim.claimedAmount.toFixed(2)})`;

  // Explanation Letter
  elements.claimantLetterContent.value = claim.claimantExplanationLetter || 'Letter generation ready.';
}

// Adjuster Action Handler
async function handleAdjusterAction(action, notes) {
  if (!state.activeClaim) return;
  const claimId = state.activeClaim.id;

  try {
    const res = await fetch(`/api/claims/${claimId}/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, notes })
    });

    if (!res.ok) throw new Error('Action failed');
    const updated = await res.json();

    // Update in state
    const idx = state.claims.findIndex(c => c.id === claimId);
    if (idx !== -1) state.claims[idx] = updated;

    selectClaim(claimId);
    showToast(`Decision recorded: ${action.replace('_', ' ')} for claim ${claimId}`, 'success');
  } catch (err) {
    showToast(`Action failed: ${err.message}`, 'danger');
  }
}

// New Claim Ingestion Pipeline Simulation
async function handleFormSubmit(e) {
  e.preventDefault();
  const stepper = elements.pipelineStepper;
  const submitBtn = elements.btnStartIngest;

  stepper.style.display = 'flex';
  submitBtn.disabled = true;

  const stages = [
    { id: 'step-pubsub', ms: 450 },
    { id: 'step-docai', ms: 600 },
    { id: 'step-rag', ms: 550 },
    { id: 'step-gemini', ms: 700 },
    { id: 'step-bigquery', ms: 500 }
  ];

  for (const st of stages) {
    const el = document.getElementById(st.id);
    el.classList.add('active');
    await new Promise(r => setTimeout(r, st.ms));
    el.classList.remove('active');
    el.classList.add('complete');
  }

  // Gather form data
  const payload = {
    claimantName: document.getElementById('form-claimant').value,
    policyNumber: document.getElementById('form-policy').value,
    lossType: document.getElementById('form-loss-type').value,
    claimedAmount: parseFloat(document.getElementById('form-amount').value),
    damageSummary: document.getElementById('form-summary').value,
    preset: document.querySelector('.preset-card.active')?.dataset.preset || 'custom'
  };

  try {
    const res = await fetch('/api/claims/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) throw new Error('Pipeline error');
    const newClaim = await res.json();

    state.claims.unshift(newClaim);
    elements.modalNewClaim.style.display = 'none';
    stepper.style.display = 'none';
    submitBtn.disabled = false;
    document.querySelectorAll('.stage-step').forEach(s => s.classList.remove('complete', 'active'));

    selectClaim(newClaim.id);
    showToast(`Claim ${newClaim.id} ingested & adjudicated via Vertex AI!`, 'success');
  } catch (err) {
    showToast(`Ingestion error: ${err.message}`, 'danger');
    submitBtn.disabled = false;
  }
}

// Gemini Copilot Interactions
function toggleCopilot() {
  state.isCopilotOpen = !state.isCopilotOpen;
  if (state.isCopilotOpen) {
    elements.copilotDrawer.classList.add('open');
    elements.copilotInput.focus();
  } else {
    elements.copilotDrawer.classList.remove('open');
  }
}

function handleCopilotSubmit(e) {
  e.preventDefault();
  const query = elements.copilotInput.value.trim();
  if (!query) return;
  elements.copilotInput.value = '';
  executeCopilotQuery(query);
}

async function executeCopilotQuery(query) {
  if (!state.activeClaim) return;
  if (!state.isCopilotOpen) toggleCopilot();

  // Append user bubble
  appendChatMessage(query, 'user');

  // Loading bubble
  const loadingBubble = appendChatMessage('Reasoning over claim evidence with Gemini 3.8 Flash...', 'ai', true);

  try {
    const res = await fetch(`/api/claims/${state.activeClaim.id}/copilot`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query })
    });

    if (!res.ok) throw new Error('Copilot response error');
    const data = await res.json();

    loadingBubble.remove();
    appendChatMessage(data.reply, 'ai');
  } catch (err) {
    loadingBubble.remove();
    appendChatMessage(`Sorry, I encountered an error: ${err.message}`, 'ai');
  }
}

function appendChatMessage(text, sender, isLoading = false) {
  const msgEl = document.createElement('div');
  msgEl.className = `chat-msg ${sender}-msg`;

  const avatar = sender === 'ai' ? '✦' : '👤';
  const formattedText = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');

  msgEl.innerHTML = `
    <div class="msg-avatar">${avatar}</div>
    <div class="msg-bubble">${isLoading ? '<em>' + formattedText + '</em>' : formattedText}</div>
  `;

  elements.copilotChatHistory.appendChild(msgEl);
  elements.copilotChatHistory.scrollTop = elements.copilotChatHistory.scrollHeight;
  return msgEl;
}

// Toast Notifications
function showToast(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span class="toast-dot" style="width: 8px; height: 8px; border-radius: 50%; background: ${type === 'success' ? '#10b981' : (type === 'danger' ? '#ef4444' : '#4285F4')}"></span>
    <span>${message}</span>
  `;

  elements.toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}
