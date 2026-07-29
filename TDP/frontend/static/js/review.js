(function () {
  'use strict';

  const state = {
    rxNumber: (window.__INITIAL_RX__ || '').trim(),
    prescriptions: [],
    prescriptionIndex: {},
    data: null,
    selectedIndex: 0,
    reasons: [],
    selectedReasons: new Set(),
  };

  let confirmModalResolver = null;

  function enforceProviderAccess() {
    const token = localStorage.getItem('token');
    const role = (localStorage.getItem('role') || '').toLowerCase();
    if (!token || (role !== 'doctor' && role !== 'provider')) {
      window.location.href = '/';
      return false;
    }
    return true;
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (!enforceProviderAccess()) {
      return;
    }
    bindStaticEvents();
    resetFlipCards();
    if (state.rxNumber) {
      loadReviewCase(state.rxNumber, false);
    } else {
      renderEmptyState('Enter a prescription Rx number to begin review.');
    }
  });

  function bindStaticEvents() {
    const providerToggle = document.getElementById('provider-toggle-btn');
    const providerCard = document.getElementById('provider-card');
    const providerLogout = document.getElementById('provider-logout-btn');

    bindDualFlipToggle();
    bindDecisionConfirmModal();

    if (providerToggle && providerCard) {
      providerToggle.addEventListener('click', (event) => {
        event.stopPropagation();
        providerCard.classList.toggle('is-open');
      });

      document.addEventListener('click', (event) => {
        if (!providerCard.contains(event.target) && event.target !== providerToggle) {
          providerCard.classList.remove('is-open');
        }
      });
    }

        if (providerLogout) {
      providerLogout.addEventListener('click', () => {
        fetch('/api/logout', { method: 'POST' }).catch(() => {});
        localStorage.removeItem('token');
        localStorage.removeItem('role');
        localStorage.removeItem('username');
        window.location.href = '/';
      });
    }

    const loadBtn = document.getElementById('review-load-btn');
    const input = document.getElementById('review-rx-input');
    if (loadBtn) {
      loadBtn.addEventListener('click', () => {
        const rxNumber = (input && input.value ? input.value : '').trim();
        if (!rxNumber) {
          renderEmptyState('Please enter an Rx number.');
          return;
        }
        loadReviewCase(rxNumber, true);
      });
    }
    if (input) {
      input.addEventListener('keypress', (event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          loadBtn && loadBtn.click();
        }
      });
    }

    const downloadBtn = document.getElementById('review-download-btn');
    if (downloadBtn) {
      downloadBtn.addEventListener('click', downloadPdf);
    }

    const acceptBtn = document.getElementById('accept-btn');
    if (acceptBtn) {
      acceptBtn.addEventListener('click', () => submitDecision('ACCEPTED'));
    }

    const rejectBtn = document.getElementById('reject-btn');
    if (rejectBtn) {
      rejectBtn.addEventListener('click', () => {
        const rejectPanel = document.getElementById('reject-panel');
        if (rejectPanel) {
          const isHidden = rejectPanel.hasAttribute('hidden');
          if (isHidden) {
            rejectPanel.removeAttribute('hidden');
            loadReasonList();
          } else {
            rejectPanel.setAttribute('hidden', 'hidden');
          }
        }
      });
    }

    const submitRejectBtn = document.getElementById('submit-reject-btn');
    if (submitRejectBtn) {
      submitRejectBtn.addEventListener('click', () => submitDecision('REJECTED'));
    }

    const reasonSearch = document.getElementById('reason-search');
    if (reasonSearch) {
      reasonSearch.addEventListener('input', filterReasonList);
    }

    window.addEventListener('resize', syncAllFlipCardHeights);
  }

  function authFetch(url, options = {}) {
    const token = localStorage.getItem('token');
    const headers = Object.assign({}, options.headers || {});
    if (token && !headers.Authorization) {
      headers.Authorization = `Bearer ${token}`;
    }
    return fetch(url, Object.assign({}, options, { headers }));
  }

  async function loadReviewCase(rxNumber, pushHistory) {
    setLoadingState(`Loading results for ${rxNumber}...`);

    try {
      const prescriptionsResponse = await authFetch('/api/prescriptions');
      const prescriptions = prescriptionsResponse.ok ? await prescriptionsResponse.json() : [];

      state.prescriptions = Array.isArray(prescriptions) ? prescriptions : [];
      state.prescriptionIndex = state.prescriptions.reduce((map, item) => {
        map[String(item.rx_number || '').trim()] = item;
        return map;
      }, {});

      const resolvedRxNumber = resolveRxNumber(rxNumber, state.prescriptions);
      const resultResponse = await authFetch(`/api/prescription/${encodeURIComponent(resolvedRxNumber)}/result`);
      const resultData = resultResponse.ok ? await resultResponse.json() : null;

      if (!resultResponse.ok) {
        if (resultResponse.status === 403) {
          renderEmptyState('You do not have access to this prescription. Select one from your Overview list.');
          return;
        }
        if (resultResponse.status === 404) {
          renderEmptyState('Prescription not found. Check the Rx number and try again.');
          return;
        }
        renderEmptyState('Prescription data could not be loaded.');
        return;
      }

      if (!resultData || !resultData.pbm) {
        renderEmptyState('PBM results are not available yet for this prescription.');
        return;
      }

      state.rxNumber = resolvedRxNumber;
      state.data = resultData;
      state.selectedIndex = selectInitialAlternative(resultData.alternatives || []);
      state.selectedReasons = new Set();
      state.reasons = [];
      updateRxInputValue(resolvedRxNumber);

      renderCase();
      if (pushHistory) {
        window.history.pushState({}, '', `/review/${encodeURIComponent(resolvedRxNumber)}`);
      }
    } catch (error) {
      renderEmptyState('Unable to load this prescription.');
    }
  }

  function resolveRxNumber(value, prescriptions) {
    const raw = String(value || '').trim();
    if (!raw) return '';

    const rows = Array.isArray(prescriptions) ? prescriptions : [];
    if (!rows.length) return raw;

    const exact = rows.find((item) => String(item.rx_number || '').trim().toUpperCase() === raw.toUpperCase());
    if (exact && exact.rx_number) {
      return String(exact.rx_number).trim();
    }

    const upperRaw = raw.toUpperCase();
    const suffixMatch = upperRaw.match(/(\d{1,5})$/);
    if (!suffixMatch) {
      return raw;
    }

    const suffix = suffixMatch[1].padStart(5, '0');
    const bySuffix = rows.find((item) => String(item.rx_number || '').trim().toUpperCase().endsWith(`-${suffix}`));
    if (bySuffix && bySuffix.rx_number) {
      return String(bySuffix.rx_number).trim();
    }

    const legacyNumeric = String(parseInt(suffix, 10));
    if (legacyNumeric !== 'NaN') {
      const byLegacyNumeric = rows.find((item) => String(item.rx_number || '').trim() === legacyNumeric);
      if (byLegacyNumeric && byLegacyNumeric.rx_number) {
        return String(byLegacyNumeric.rx_number).trim();
      }
    }

    return raw;
  }

  function updateRxInputValue(rxNumber) {
    const input = document.getElementById('review-rx-input');
    if (!input) return;
    input.value = rxNumber || '';
  }

  function selectInitialAlternative(alternatives) {
    if (!Array.isArray(alternatives) || !alternatives.length) return 0;
    const selectedIndex = alternatives.findIndex((item) => item && item.is_selected);
    return selectedIndex >= 0 ? selectedIndex : 0;
  }

  function getActiveAlternative() {
    const alternatives = (state.data && Array.isArray(state.data.alternatives)) ? state.data.alternatives : [];
    return alternatives[state.selectedIndex] || alternatives[0] || null;
  }

  function hasMeaningfulValue(value) {
    if (value === null || value === undefined) return false;
    if (typeof value === 'string') return value.trim() !== '';
    return true;
  }

  function applySummaryCardOverrides(activeAlternative, baseCost, basePolicy) {
    const cost = { ...(baseCost || {}) };
    const policy = { ...(basePolicy || {}) };

    const cards = (activeAlternative && activeAlternative.orchestrator_summary_cards) || {};
    const financial = cards.financial_agent || {};
    const insurance = cards.insurance_context || {};
    const policyCard = cards.policy_agent || {};

    const assignIfMeaningful = (target, key, value) => {
      if (hasMeaningfulValue(value)) {
        target[key] = value;
      }
    };

    // Cost analysis values from financial summary card.
    assignIfMeaningful(cost, 'original_tier', financial.original_tier);
    assignIfMeaningful(cost, 'alternative_tier', financial.alternative_tier);
    assignIfMeaningful(cost, 'original_total_cost', financial.original_total_price);
    assignIfMeaningful(cost, 'alternative_total_cost', financial.alternative_total_price);
    assignIfMeaningful(cost, 'original_price', financial.original_total_price);
    assignIfMeaningful(cost, 'alternative_price', financial.alternative_total_price);
    assignIfMeaningful(cost, 'original_copay', financial.original_copay);
    assignIfMeaningful(cost, 'alternative_copay', financial.alternative_copay);
    assignIfMeaningful(cost, 'original_plan_paid', financial.original_plan_paid);
    assignIfMeaningful(cost, 'alternative_plan_paid', financial.alternative_plan_paid);
    assignIfMeaningful(cost, 'estimated_annual_savings', financial.annual_savings);
    assignIfMeaningful(cost, 'member_savings_percentage', financial.savings_percent);

    // Coverage details from insurance context card.
    assignIfMeaningful(cost, 'insurance_phase', insurance.insurance_phase);
    assignIfMeaningful(cost, 'ytd_oop', insurance.ytd_oop);
    assignIfMeaningful(cost, 'coinsurance_percentage', insurance.coinsurance);
    assignIfMeaningful(cost, 'deductible_cap', insurance.deductible_limit);
    assignIfMeaningful(cost, 'deductible_remaining', insurance.deductible_remaining);
    assignIfMeaningful(cost, 'oop_max_cap', insurance.oop_max);
    assignIfMeaningful(cost, 'oop_remaining', insurance.oop_remaining);

    // Policy review values from policy summary card.
    assignIfMeaningful(policy, 'original_status', policyCard.original_status);
    assignIfMeaningful(policy, 'alternative_status', policyCard.alternative_status);
    assignIfMeaningful(policy, 'policy_notes', policyCard.policy_notes);
    assignIfMeaningful(policy, 'formulary_preference', policyCard.formulary_preference);
    assignIfMeaningful(policy, 'coverage_status', policyCard.coverage_status);
    if (Array.isArray(policyCard.key_findings) && policyCard.key_findings.length) {
      policy.key_findings = policyCard.key_findings;
    }

    return { cost, policy };
  }

  function renderCase() {
    resetDecisionSummaryStyle();
    const pbm = state.data.pbm || {};
    const baseCost = state.data.cost || {};
    const basePolicy = state.data.policy || {};
    const activeAlternative = getActiveAlternative();
    const displayPayloads = applySummaryCardOverrides(activeAlternative, baseCost, basePolicy);
    const cost = displayPayloads.cost;
    const policy = displayPayloads.policy;
    const meta = state.prescriptionIndex[state.rxNumber] || {};
    const alternatives = Array.isArray(state.data.alternatives) ? state.data.alternatives : [];

    const confidence = Math.max(0, Math.min(100, Math.round(Number(activeAlternative && activeAlternative.combined_score !== undefined ? activeAlternative.combined_score : pbm.ai_confidence || 0) * 100)));
    const selectedLabel = activeAlternative ? (activeAlternative.label || activeAlternative.alternative_label || 'Alternative') : '—';

    updateText('report-rx-number', state.rxNumber);
    updateText('report-member-id', meta.member_id || meta.patient_account_id || '—');
    updateText('summary-prescribed-drug', meta.medication || meta.prod_nm || pbm.prescribed_drug || '—');
    updateText('summary-diagnosis', pbm.diagnosis_display || pbm.diagnosis || '—');
    updateText('report-alt-name', selectedLabel);
    updateText('report-tier', cost.alternative_tier || cost.original_tier || '—');
    updateText('confidence-text', `${confidence}%`);
    updateScoreRing(confidence);
    updateText('clinical-status-chip', activeAlternative ? (activeAlternative.review_status || 'Clinical Review') : 'Clinical Review');
    updateText('safety-status-chip', activeAlternative && activeAlternative.safety && activeAlternative.safety.summary ? activeAlternative.safety.summary : 'Clinically Acceptable');

    populateLists(activeAlternative, pbm);
    populateFinancialSummary(activeAlternative, cost, policy);
    populateExpandedDetails(activeAlternative, cost, policy);
    populateAlternativeList(alternatives);
    populateDecisionPanel(pbm, activeAlternative, policy);
    updateDecisionChip(meta, pbm);
    updateAgentBadges({
      confidence,
      pbm,
      activeAlternative,
      policy,
      cost,
      workflow: getWorkflowPresentation(meta, pbm)
    });
    resetFlipCards();
  }

  function setAgentBadge(id, confidencePercent) {
    const node = document.getElementById(id);
    if (!node) return;
    const percent = normalizePercent(confidencePercent);
    const good = percent >= 70;
    node.className = `review-agent-badge ${good ? 'review-agent-badge--good' : 'review-agent-badge--warn'}`;
    node.textContent = `${percent}%`;
    node.setAttribute('aria-label', `Agent confidence ${percent}%`);
  }

  function setAgentCardState(id, isGood) {
    const node = document.getElementById(id);
    if (!node) return;
    node.classList.remove('agent-card-status--good', 'agent-card-status--warn');
    node.classList.add(isGood ? 'agent-card-status--good' : 'agent-card-status--warn');
  }

  function hasIssueText(value) {
    const text = String(value || '').toLowerCase();
    if (!text) return false;
    return text.includes('not covered')
      || text.includes('reject')
      || text.includes('escalat')
      || text.includes('denied')
      || text.includes('fail');
  }

  function isNoneDetected(value) {
    const text = String(value || '').trim().toLowerCase();
    return !text
      || text === 'none'
      || text === 'none detected'
      || text === 'no'
      || text === 'n/a';
  }

  function normalizePercent(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return 0;
    const scaled = numeric <= 1 ? numeric * 100 : numeric;
    return Math.max(0, Math.min(100, Math.round(scaled)));
  }

  function resolveAgentConfidence(activeAlternative, key, fallbackPercent) {
    const fallback = normalizePercent(fallbackPercent);
    if (!activeAlternative) return fallback;

    const direct = activeAlternative.agent_confidence || {};
    if (direct[key] !== undefined && direct[key] !== null && direct[key] !== '') {
      return normalizePercent(direct[key]);
    }

    const breakdown = activeAlternative.agent_breakdown || {};
    if (breakdown[key] !== undefined && breakdown[key] !== null && breakdown[key] !== '') {
      return normalizePercent(breakdown[key]);
    }

    return fallback;
  }

  function resolvePastDecisionGoodState(activeAlternative, workflow) {
    const cards = (activeAlternative && activeAlternative.orchestrator_summary_cards) || {};
    const pastCard = cards.past_decision_agent || {};
    const status = String(pastCard.status || '').trim().toUpperCase();
    const supportFlag = pastCard.recommendation_supported;

    if (status) {
      if (['RECOMMENDED', 'APPROVED', 'SUPPORTED', 'PASS'].includes(status)) return true;
      if (['NOT_RECOMMENDED', 'REJECTED', 'DENIED', 'FAIL'].includes(status)) return false;
    }
    if (supportFlag === true) return true;
    if (supportFlag === false) return false;

    const workflowLabel = String((workflow && workflow.label) || '').toLowerCase();
    return !workflowLabel.includes('rejected') && !workflowLabel.includes('under review') && !workflowLabel.includes('pending');
  }

  function updateAgentBadges({ confidence, pbm, activeAlternative, policy, cost, workflow }) {
    const reviewStatus = String((activeAlternative && activeAlternative.review_status) || pbm.status || '').toUpperCase();
    const safety = (activeAlternative && activeAlternative.safety) || {};
    const policyPayload = policy || {};
    const costPayload = cost || {};

    const clinicalGood = confidence >= 80 && !['ESCALATED', 'REJECTED', 'PENDING_REVIEW'].includes(reviewStatus);
    const safetyGood = isNoneDetected(safety.contraindications) && isNoneDetected(safety.interactions);
    const policyGood = !hasIssueText(policyPayload.original_status)
      && !hasIssueText(policyPayload.alternative_status)
      && !hasIssueText(policyPayload.policy_state);
    const financialGood = Number(costPayload.estimated_annual_savings || costPayload.savings || 0) > 0;
    const pastGood = resolvePastDecisionGoodState(activeAlternative, workflow);

    const clinicalPct = resolveAgentConfidence(activeAlternative, 'clinical', confidence);
    const safetyPct = resolveAgentConfidence(activeAlternative, 'clinical', safetyGood ? 88 : 42);
    const policyPct = resolveAgentConfidence(activeAlternative, 'policy', policyGood ? 88 : 46);
    const financialPct = resolveAgentConfidence(activeAlternative, 'financial', financialGood ? 82 : 45);
    const pastPct = resolveAgentConfidence(activeAlternative, 'past', pastGood ? 80 : 40);

    setAgentBadge('agent-badge-clinical', clinicalPct);
    setAgentBadge('agent-badge-safety', safetyPct);
    setAgentBadge('agent-badge-policy', policyPct);
    setAgentBadge('agent-badge-financial', financialPct);
    setAgentBadge('agent-badge-past', pastPct);

    setAgentCardState('card-clinical', clinicalPct >= 60 && safetyPct >= 60);
    setAgentCardState('policy-card', policyPct >= 70);
    setAgentCardState('financial-card', financialPct >= 70);
    setAgentCardState('card-past', pastPct >= 70);
  }

  function populateLists(activeAlternative, pbm) {
    const safety = (activeAlternative && activeAlternative.safety) || {};
    const policy = (activeAlternative && activeAlternative.policy) || {};
    const clinicalLines = (activeAlternative && Array.isArray(activeAlternative.clinical_summary_lines)) ? activeAlternative.clinical_summary_lines : [];
    const safetyLines = (activeAlternative && Array.isArray(activeAlternative.safety_summary_lines)) ? activeAlternative.safety_summary_lines : [];
    const policyFindings = Array.isArray(policy.key_findings) ? policy.key_findings : [];

    const clinicalList = clinicalLines.length ? clinicalLines : [
      safety.summary || pbm.safety_summary || 'Reviewed by AI',
      safety.contraindications ? `Contraindications: ${safety.contraindications}` : 'Contraindications: None detected',
      safety.interactions ? `Interactions: ${safety.interactions}` : 'Interactions: None detected',
      safety.monitoring ? `Monitoring: ${safety.monitoring}` : 'Monitoring: Standard follow-up'
    ];

    const safetyList = safetyLines.length ? safetyLines : [
      policy.original_status || 'Original drug status reviewed',
      policy.alternative_status || 'Alternative is clinically acceptable',
      activeAlternative && activeAlternative.policy && activeAlternative.policy.policy_state ? `Policy state: ${activeAlternative.policy.policy_state}` : 'Policy state: review'
    ];

    if (policyFindings.length) {
      policyFindings.forEach((finding) => {
        safetyList.push(`Finding: ${finding}`);
      });
    }

    updateList('clinical-list', clinicalList);
    updateList('safety-list', safetyList);
  }

  function populateFinancialSummary(activeAlternative, cost, policy) {
    const selectedCost = cost || {};
    updateText('financial-save-annual', `${formatMoney(selectedCost.estimated_annual_savings || selectedCost.savings || 0)} per month`);
    updateText('financial-save-note', buildSavingsNote(activeAlternative, selectedCost));
    updateText('original-total-cost', formatMoney(selectedCost.original_total_cost));
    updateText('alternative-total-cost', formatMoney(selectedCost.alternative_total_cost));
    updateText('patient-copay', formatMoney(selectedCost.alternative_copay));
    updateText('savings-percent', formatPercent(selectedCost.member_savings_percentage));
  }

  function populateExpandedDetails(activeAlternative, cost, policy) {
    const selectedCost = cost || {};
    updateText('original-tier', selectedCost.original_tier || '—');
    updateText('alternative-tier', selectedCost.alternative_tier || '—');
    updateText('original-price', formatMoney(selectedCost.original_price));
    updateText('alternative-price', formatMoney(selectedCost.alternative_price));
    updateText('original-copay', formatMoney(selectedCost.original_copay));
    updateText('alternative-copay', formatMoney(selectedCost.alternative_copay));
    updateText('plan-paid-amount', formatMoney(selectedCost.original_plan_paid) + ' → ' + formatMoney(selectedCost.alternative_plan_paid));
    updateText('total-cost', formatMoney(selectedCost.original_total_cost) + ' → ' + formatMoney(selectedCost.alternative_total_cost));
    updateText('insurance-phase', formatPhase(selectedCost.insurance_phase));
    updateText('ytd-oop', formatMoney(selectedCost.ytd_oop));
    updateText('deductible-cap', formatMoney(selectedCost.deductible_cap));
    updateText('oop-max-cap', formatMoney(selectedCost.oop_max_cap));
    updateText('deductible-remaining', formatMoney(selectedCost.deductible_remaining));
    updateText('oop-remaining', formatMoney(selectedCost.oop_remaining));
    updateText('policy-original', policy.original_status || '—');
    updateText('policy-alternative', policy.alternative_status || '—');
    updateText('policy-state', policy.policy_notes || policy.policy_state || '—');

    // Populate Policy card Coverage Details (for View more expansion)
    updateText('policy-insurance-phase', formatPhase(selectedCost.insurance_phase));
    updateText('policy-ytd-oop', formatMoney(selectedCost.ytd_oop));
    updateText('policy-coinsurance', formatPercent(selectedCost.coinsurance_percentage));
    updateText('policy-deductible-met', (selectedCost.deductible_remaining ? 'Deductible' : 'Deductible') + ' stage');
    updateText('policy-deductible-remaining', formatMoney(selectedCost.deductible_remaining) + ' remaining');
    updateText('policy-oop-met', (selectedCost.oop_remaining ? 'In Progress' : 'In Progress') + ' stage');
    updateText('policy-oop-remaining', formatMoney(selectedCost.oop_remaining) + ' remaining');
    updateText('policy-deductible-cap', formatMoney(selectedCost.deductible_cap));
    updateText('policy-oop-max-cap', formatMoney(selectedCost.oop_max_cap));

    // Update progress bars
    const deductiblePercent = selectedCost.deductible_cap ? (Math.max(0, selectedCost.deductible_cap - selectedCost.deductible_remaining) / selectedCost.deductible_cap * 100) : 0;
    const oopPercent = selectedCost.oop_max_cap ? (Math.max(0, selectedCost.oop_max_cap - selectedCost.oop_remaining) / selectedCost.oop_max_cap * 100) : 0;
    const deductibleBar = document.getElementById('policy-deductible-bar');
    const oopBar = document.getElementById('policy-oop-bar');
    if (deductibleBar) deductibleBar.style.width = deductiblePercent + '%';
    if (oopBar) oopBar.style.width = oopPercent + '%';

    // Populate Financial Cost Analysis table (for View more expansion)
    const meta = state.data && state.data.pbm ? state.data.pbm : {};
    const selectedIndex = state.selectedIndex || 0;
    const alternative = state.data && state.data.alternatives && state.data.alternatives[selectedIndex] ? state.data.alternatives[selectedIndex] : {};
    
    updateText('financial-drug-original', meta.prescribed_drug || meta.prod_nm || 'Original Drug');
    updateText('financial-drug-alternative', alternative.drug_name || alternative.prod_nm || 'Alternative Drug');
    updateText('financial-tier-original', selectedCost.original_tier || '—');
    updateText('financial-tier-alternative', selectedCost.alternative_tier || '—');
    updateText('financial-price-original', formatMoney(selectedCost.original_price));
    updateText('financial-price-alternative', formatMoney(selectedCost.alternative_price));
    updateText('financial-copay-original', formatMoney(selectedCost.original_copay));
    updateText('financial-copay-alternative', formatMoney(selectedCost.alternative_copay));
    updateText('financial-plan-original', formatMoney(selectedCost.original_plan_paid));
    updateText('financial-plan-alternative', formatMoney(selectedCost.alternative_plan_paid));
    updateText('financial-total-original', formatMoney(selectedCost.original_total_cost));
    updateText('financial-total-alternative', formatMoney(selectedCost.alternative_total_cost));
    updateText('financial-detailed-savings', `${formatMoney(selectedCost.estimated_annual_savings || selectedCost.savings || 0)} per month`);
    updateText('financial-detailed-savings-note', buildSavingsNote(activeAlternative, selectedCost));
  }

  function populateAlternativeList(alternatives) {
    const container = document.getElementById('alternative-list');
    if (!container) return;
    if (!Array.isArray(alternatives) || !alternatives.length) {
      container.innerHTML = '<div class="loading-text">No alternatives found for this case.</div>';
      return;
    }

    container.innerHTML = alternatives.map((alt, index) => {
      const active = index === state.selectedIndex;
      const score = Math.max(0, Math.min(100, Math.round(Number(alt.combined_score || 0) * 100)));
      return `
        <button type="button" class="alternative-btn ${active ? 'is-active' : ''}" data-alt-index="${index}">
          <span class="alt-left">
            <span class="alt-main">
              <span class="alt-rank">Alternative ${index + 1}</span>
              <span class="alt-name">${escapeHtml(alt.label || `Alternative ${index + 1}`)}</span>
            </span>
          </span>
          <span class="alt-score">${score}%</span>
        </button>
      `;
    }).join('');

    container.querySelectorAll('[data-alt-index]').forEach((button) => {
      button.addEventListener('click', () => {
        state.selectedIndex = Number(button.getAttribute('data-alt-index') || 0);
        renderCase();
      });
    });
  }

  function populateDecisionPanel(pbm, activeAlternative, policy) {
    if (activeAlternative && activeAlternative.past_decision_summary) {
      updateText('past-decision-summary', activeAlternative.past_decision_summary);
    } else {
      updateText('past-decision-summary', 'Historical evidence generally supports the recommendation because similar past cases were accepted by doctors.');
    }
    updateDecisionActionsVisibility(pbm);
  }

  function updateDecisionActionsVisibility(pbm) {
    const existingDecision = state.data && state.data.doctor_decision;
    const actions = document.getElementById('decision-actions');
    const rejectPanel = document.getElementById('reject-panel');
    const recorded = document.getElementById('decision-recorded');
    const autoApprovedBanner = document.getElementById('decision-auto-approved');
    if (!actions) return;

    const pbmStatus = String((pbm && pbm.status) || '').toUpperCase();
    const isAutoApproved = pbmStatus === 'APPROVED';

    if (isAutoApproved && !(existingDecision && existingDecision.status)) {
      actions.setAttribute('hidden', 'hidden');
      if (rejectPanel) rejectPanel.setAttribute('hidden', 'hidden');
      if (recorded) recorded.setAttribute('hidden', 'hidden');
      if (autoApprovedBanner) autoApprovedBanner.removeAttribute('hidden');
      return;
    }

    if (autoApprovedBanner) autoApprovedBanner.setAttribute('hidden', 'hidden');

    if (existingDecision && existingDecision.status) {
      actions.setAttribute('hidden', 'hidden');
      if (rejectPanel) rejectPanel.setAttribute('hidden', 'hidden');
      if (recorded) {
        const status = String(existingDecision.status || '').toUpperCase();
        const statusLabel = status === 'ACCEPTED' ? 'Accepted' : status === 'REJECTED' ? 'DAW' : status === 'MODIFIED' ? 'DAW' : status;
        const recordedAt = existingDecision.created_at ? new Date(existingDecision.created_at).toLocaleString() : '';
        const reasonText = (existingDecision.reasons && existingDecision.reasons.length)
          ? existingDecision.reasons.map((item) => item.reason_text).join(', ')
          : (existingDecision.reason || '');
        recorded.innerHTML = `
          <span class="badge badge-${status.toLowerCase()}">${escapeHtml(statusLabel)}</span>
          ${recordedAt ? `<span class="decision-recorded-meta">Recorded on ${escapeHtml(recordedAt)}</span>` : ''}
          ${reasonText ? `<div class="decision-recorded-reason"><strong>Reason:</strong> ${escapeHtml(reasonText)}</div>` : ''}
          ${existingDecision.comment ? `<div class="decision-recorded-comment">${escapeHtml(existingDecision.comment)}</div>` : ''}
        `;
        recorded.removeAttribute('hidden');
      }
    } else {
      actions.removeAttribute('hidden');
      if (recorded) recorded.setAttribute('hidden', 'hidden');
    }
  }

  function getWorkflowPresentation(meta, pbmPayload) {
    const decisionStatus = String(
      (meta && meta.decision_status) ||
      (state.data && state.data.doctor_decision && state.data.doctor_decision.status) ||
      ''
    ).toUpperCase();
    const pbmStatus = String(
      (meta && meta.pbm_status) ||
      (pbmPayload && pbmPayload.status) ||
      (state.data && state.data.pbm && state.data.pbm.status) ||
      ''
    ).toUpperCase();

    if (pbmStatus === 'APPROVED') {
      return { label: 'Auto Approve', chipClass: 'workflow-chip workflow-auto-approve', summaryClass: 'summary-col summary-col-accept workflow-auto-approve-accent' };
    }
    if (decisionStatus === 'ACCEPTED') {
      return { label: 'Accept', chipClass: 'workflow-chip workflow-accept', summaryClass: 'summary-col summary-col-accept workflow-accept-accent' };
    }
    if (decisionStatus === 'REJECTED') {
      return { label: 'DAW', chipClass: 'workflow-chip workflow-daw', summaryClass: 'summary-col summary-col-accept workflow-daw-accent' };
    }
    if (decisionStatus === 'MODIFIED') {
      return { label: 'DAW', chipClass: 'workflow-chip workflow-daw', summaryClass: 'summary-col summary-col-accept workflow-daw-accent' };
    }
    if (pbmStatus === 'KEEP_ORIGINAL') {
      return { label: 'DAW', chipClass: 'workflow-chip workflow-daw', summaryClass: 'summary-col summary-col-accept workflow-daw-accent' };
    }
    if (pbmStatus === 'ESCALATED') {
      return { label: 'Under Review', chipClass: 'workflow-chip workflow-under-review', summaryClass: 'summary-col summary-col-accept workflow-under-review-accent' };
    }
    if (pbmStatus === 'IN_PROGRESS') {
      return { label: 'In Progress', chipClass: 'workflow-chip workflow-in-progress', summaryClass: 'summary-col summary-col-accept workflow-in-progress-accent' };
    }
    return { label: 'Pending', chipClass: 'workflow-chip workflow-pending', summaryClass: 'summary-col summary-col-accept workflow-pending-accent' };
  }

  function updateDecisionChip(meta, pbmPayload) {
    const chip = document.getElementById('decision-status-chip');
    const summaryStrip = document.getElementById('summary-strip-card');
    if (!chip) return;

    const workflow = getWorkflowPresentation(meta, pbmPayload);
    chip.textContent = workflow.label;
    chip.className = workflow.chipClass;

    if (summaryStrip) {
      const accentClass = workflow.summaryClass.split(' ').find(c => c.includes('-accent')) || 'workflow-pending-accent';
      summaryStrip.className = 'review-card summary-strip-card ' + accentClass;
    }
  }

  function bindDualFlipToggle() {
    const toggleButton = document.getElementById('dual-view-toggle-btn');
    if (!toggleButton) return;
    toggleButton.addEventListener('click', toggleAllFlipCards);
    syncDualFlipToggle(false);
  }

  function getFlipCards() {
    return Array.from(document.querySelectorAll('.flip-card'));
  }

  function toggleAllFlipCards() {
    const cards = getFlipCards();
    if (!cards.length) return;
    const shouldFlip = !cards.every((card) => card.classList.contains('is-flipped'));
    cards.forEach((card) => setFlipCardState(card, shouldFlip));
    syncDualFlipToggle(shouldFlip);
  }

  function setFlipCardState(card, flipped) {
    if (!card) return;
    card.classList.toggle('is-flipped', Boolean(flipped));
    syncFlipCardHeight(card);
  }

  function syncDualFlipToggle(forcedState) {
    const toggleButton = document.getElementById('dual-view-toggle-btn');
    if (!toggleButton) return;
    const isExpanded = typeof forcedState === 'boolean'
      ? forcedState
      : getFlipCards().length > 0 && getFlipCards().every((card) => card.classList.contains('is-flipped'));
    toggleButton.textContent = isExpanded ? 'View less' : 'View more';
    toggleButton.setAttribute('aria-expanded', String(isExpanded));
  }

  function resetFlipCards() {
    getFlipCards().forEach((card) => {
      card.classList.remove('is-flipped');
      syncFlipCardHeight(card);
    });
    syncDualFlipToggle(false);
  }

  function syncFlipCardHeight(card) {
    if (!card) return;
    syncAllFlipCardHeights();
  }

  function syncAllFlipCardHeights() {
    const cards = getFlipCards();
    if (!cards.length) return;

    const heights = cards.map((card) => {
      const activeFace = card.querySelector(card.classList.contains('is-flipped') ? '.flip-card-back' : '.flip-card-front');
      return activeFace ? activeFace.scrollHeight : 0;
    });

    const targetHeight = Math.max(...heights);
    cards.forEach((card) => {
      card.style.height = `${targetHeight}px`;
    });
  }

  async function loadReasonList(forceReload = false) {
    const list = document.getElementById('reason-list');
    if (!list) return;
    if (state.reasons.length && !forceReload) {
      renderReasonList();
      return;
    }

    list.innerHTML = '<div class="loading-text">Loading reasons...</div>';
    try {
      const response = await authFetch('/api/decision-reasons');
      const data = response.ok ? await response.json() : [];
      state.reasons = Array.isArray(data) ? data : [];
      renderReasonList();
    } catch (error) {
      list.innerHTML = '<div class="error-text">Unable to load rejection reasons.</div>';
    }
  }

  function renderReasonList() {
    const list = document.getElementById('reason-list');
    if (!list) return;
    const query = (document.getElementById('reason-search') || {}).value ? document.getElementById('reason-search').value.trim().toLowerCase() : '';
    const reasons = state.reasons.filter((item) => {
      if (!query) return true;
      return (`${item.code} ${item.label}`).toLowerCase().includes(query);
    });

    if (!reasons.length) {
      list.innerHTML = '<div class="loading-text">No reasons match your search.</div>';
      return;
    }

    list.innerHTML = reasons.map((item) => {
      const checked = state.selectedReasons.has(item.code) ? 'checked' : '';
      return `
        <label class="reason-item">
          <input type="checkbox" data-reason-code="${escapeHtml(item.code)}" ${checked}>
          <span>
            <span class="reason-code">${escapeHtml(item.code)}</span><br>
            <span class="reason-label">${escapeHtml(item.label)}</span>
          </span>
        </label>
      `;
    }).join('');

    list.querySelectorAll('[data-reason-code]').forEach((checkbox) => {
      checkbox.addEventListener('change', () => {
        const code = checkbox.getAttribute('data-reason-code');
        if (!code) return;
        if (checkbox.checked) {
          state.selectedReasons.add(code);
        } else {
          state.selectedReasons.delete(code);
        }
      });
    });
  }

  function filterReasonList() {
    renderReasonList();
  }

  function getDecisionConfirmationMessage(status) {
    if (status === 'ACCEPTED') {
      return 'Are you sure you want to accept this recommendation?';
    }
    if (status === 'REJECTED') {
      return 'Are you sure you want to reject this recommendation?';
    }
    return 'Are you sure you want to submit this decision?';
  }

  function getDecisionConfirmationTitle(status) {
    if (status === 'ACCEPTED') {
      return 'Confirm Accept';
    }
    if (status === 'REJECTED') {
      return 'Confirm Reject';
    }
    return 'Confirm Decision';
  }

  function closeDecisionConfirmModal(confirmed) {
    const modal = document.getElementById('decision-confirm-modal');
    if (modal) {
      modal.setAttribute('hidden', 'hidden');
    }
    const resolver = confirmModalResolver;
    confirmModalResolver = null;
    if (resolver) {
      resolver(Boolean(confirmed));
    }
  }

  function openDecisionConfirmModal(status) {
    const modal = document.getElementById('decision-confirm-modal');
    const title = document.getElementById('decision-confirm-title');
    const message = document.getElementById('decision-confirm-message');
    const proceedBtn = document.getElementById('decision-confirm-proceed');
    const cancelBtn = document.getElementById('decision-confirm-cancel');
    if (!modal || !title || !message || !proceedBtn || !cancelBtn) {
      return Promise.resolve(window.confirm(getDecisionConfirmationMessage(status)));
    }

    title.textContent = getDecisionConfirmationTitle(status);
    message.textContent = getDecisionConfirmationMessage(status);
    proceedBtn.className = 'review-button review-button-primary';

    if (status === 'ACCEPTED') {
      proceedBtn.textContent = 'Yes, Accept';
    } else if (status === 'REJECTED') {
      proceedBtn.textContent = 'Yes, Reject';
    } else {
      proceedBtn.textContent = 'Confirm';
    }

    modal.removeAttribute('hidden');
    cancelBtn.focus();

    return new Promise((resolve) => {
      confirmModalResolver = resolve;
    });
  }

  function bindDecisionConfirmModal() {
    const modal = document.getElementById('decision-confirm-modal');
    const proceedBtn = document.getElementById('decision-confirm-proceed');
    const cancelBtn = document.getElementById('decision-confirm-cancel');
    if (!modal || !proceedBtn || !cancelBtn) return;

    proceedBtn.addEventListener('click', () => closeDecisionConfirmModal(true));
    cancelBtn.addEventListener('click', () => closeDecisionConfirmModal(false));
    modal.addEventListener('click', (event) => {
      const target = event.target;
      if (target && target.hasAttribute('data-confirm-close')) {
        closeDecisionConfirmModal(false);
      }
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && !modal.hasAttribute('hidden')) {
        closeDecisionConfirmModal(false);
      }
    });
  }

  async function submitDecision(status) {
    if (!state.rxNumber || !state.data) return;

    const payload = { status };
    const activeAlternative = getActiveAlternative();
    if (activeAlternative && activeAlternative.index !== undefined) {
      payload.alternative_index = activeAlternative.index;
    } else if (state.selectedIndex !== undefined) {
      payload.alternative_index = state.selectedIndex;
    }

    if (status === 'REJECTED') {
      const reasonCodes = Array.from(state.selectedReasons);
      if (!reasonCodes.length) {
        showInlineError('Please select at least one rejection reason.');
        return;
      }
      payload.reason_codes = reasonCodes;
      const comment = (document.getElementById('reject-comment') || {}).value || '';
      payload.comment = comment.trim();
    }

    const confirmed = await openDecisionConfirmModal(status);
    if (!confirmed) {
      return;
    }

    try {
      const response = await authFetch(`/api/prescription/${encodeURIComponent(state.rxNumber)}/decision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) {
        showInlineError(data.error || 'Unable to save decision.');
        return;
      }
      window.location.href = '/provider';
    } catch (error) {
      showInlineError('Unable to save decision.');
    }
  }

  async function downloadPdf() {
    const element = document.getElementById('review-pdf-area');
    if (!element || typeof html2pdf === 'undefined') return;
    const filename = `PBM_Report_${state.rxNumber || 'review'}`;
    element.classList.add('pdf-export-mode');

    try {
      const width = Math.max(element.scrollWidth, element.offsetWidth);
      const height = Math.max(element.scrollHeight, element.offsetHeight);
      const orientation = width >= height ? 'landscape' : 'portrait';

      await html2pdf().set({
        margin: 0,
        filename,
        image: { type: 'jpeg', quality: 0.98 },
        html2canvas: {
          scale: 2,
          useCORS: true,
          backgroundColor: '#faf8f2',
          windowWidth: width,
          windowHeight: height,
          scrollX: 0,
          scrollY: 0,
        },
        jsPDF: { unit: 'px', format: [width, height], orientation }
      }).from(element).save();
    } finally {
      element.classList.remove('pdf-export-mode');
    }
  }

  function renderEmptyState(message) {
    resetDecisionSummaryStyle();
    updateText('report-rx-number', 'Rx-');
    updateText('report-member-id', '—');
    updateText('summary-prescribed-drug', '—');
    updateText('summary-diagnosis', '—');
    updateText('report-alt-name', '—');
    updateText('report-tier', '—');
    updateText('confidence-text', '0%');
    updateScoreRing(0);
    updateText('decision-summary', message);
    updateText('financial-save-annual', '—');
    updateText('financial-save-note', message);
    updateText('alternative-list', `<div class="loading-text">${escapeHtml(message)}</div>`);
    updateText('clinical-list', `<li>${escapeHtml(message)}</li>`);
    updateText('safety-list', `<li>${escapeHtml(message)}</li>`);
    updateDecisionChip({});
    syncAllFlipCardHeights();
  }

  function setLoadingState(message) {
    resetDecisionSummaryStyle();
    updateText('decision-summary', message);
    updateText('alternative-list', `<div class="loading-text">${escapeHtml(message)}</div>`);
  }

  function showInlineError(message) {
    const summary = document.getElementById('decision-summary');
    if (summary) {
      summary.textContent = message;
      summary.style.borderColor = '#e8b1b1';
      summary.style.background = '#fff8f8';
      summary.style.color = '#8b1f1f';
    }
  }

  function resetDecisionSummaryStyle() {
    const summary = document.getElementById('decision-summary');
    if (!summary) return;
    summary.style.borderColor = '#E3E6EC';
    summary.style.background = '#F8F9FA';
    summary.style.color = '#374151';
  }

  function updateScoreRing(percent) {
    const ring = document.getElementById('confidence-ring');
    if (!ring) return;
    const value = Math.max(0, Math.min(100, Number(percent) || 0));
    ring.style.setProperty('--pct', value);
  }

  function updateText(id, value) {
    const node = document.getElementById(id);
    if (!node) return;
    if (typeof value === 'string' && value.includes('<')) {
      node.innerHTML = value;
    } else {
      node.textContent = value === null || value === undefined || value === '' ? '—' : String(value);
    }
  }

  function updateList(id, items) {
    const node = document.getElementById(id);
    if (!node) return;
    node.innerHTML = (Array.isArray(items) ? items : []).map((item) => `<li>${escapeHtml(item)}</li>`).join('');
  }

  function formatMoney(value) {
    if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) return '—';
    return `$${Number(value).toFixed(2)}`;
  }

  function formatPercent(value) {
    if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) return '—';
    return `${Number(value).toFixed(2)}%`;
  }

  function formatPhase(phase) {
    if (!phase) return '—';
    const mapping = {
      DEDUCTIBLE: 'Deductible Stage',
      INITIAL_COVERAGE: 'Standard Coverage',
      CATASTROPHIC: 'OOP Max Reached',
    };
    return mapping[phase] || phase;
  }

  function buildSavingsNote(activeAlternative, selectedCost) {
    const savingsPercent = Number(selectedCost.member_savings_percentage);
    if (!Number.isNaN(savingsPercent) && selectedCost.member_savings_percentage !== null && selectedCost.member_savings_percentage !== undefined && selectedCost.member_savings_percentage !== '') {
      const normalizedPercent = Math.abs(savingsPercent) <= 1 ? savingsPercent * 100 : savingsPercent;
      return `${normalizedPercent.toFixed(1)}% lower than original drug`;
    }
    return `Selected alternative: ${activeAlternative ? (activeAlternative.label || '—') : '—'}`;
  }

  function escapeHtml(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
})();


