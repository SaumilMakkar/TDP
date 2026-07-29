(function () {
  'use strict';

  var STEP_IDS = [
    'spm-c1','spm-c2','spm-c3',
    'spm-p1','spm-p2',
    'spm-f1','spm-f2',
    'spm-d1','spm-d2','spm-d3','spm-d4'
  ];
  var AGENT_IDS = ['spm-policy-header','spm-financial-header','spm-past-header'];

  function byId(id) {
    return document.getElementById(id);
  }

  function setStep(id, state) {
    var el = byId(id);
    if (!el) return;
    el.className = 'spm-step spm-step--' + state;
  }

  function setAgent(id, state) {
    var el = byId(id);
    if (!el) return;
    el.className = 'spm-agent-header spm-agent-header--' + state;
  }

  function setStage(badgeId, state) {
    var el = byId(badgeId);
    if (!el) return;
    el.className = 'spm-stage-badge spm-stage-badge--' + state;
  }

  function setFlowState(activeStep) {
    var stepIds = ['spm-flow-1', 'spm-flow-2', 'spm-flow-3', 'spm-flow-4', 'spm-flow-5'];
    var connectorIds = ['spm-flow-c1', 'spm-flow-c2', 'spm-flow-c3', 'spm-flow-c4'];

    stepIds.forEach(function (id, idx) {
      var el = byId(id);
      if (!el) return;
      var stepNum = idx + 1;
      var state = 'pending';
      if (stepNum < activeStep) state = 'done';
      else if (stepNum === activeStep) state = 'current';
      el.className = 'spm-flow-step spm-flow-step--' + state;
    });

    connectorIds.forEach(function (id, idx) {
      var el = byId(id);
      if (!el) return;
      var leftStepNum = idx + 1;
      el.className = leftStepNum < activeStep
        ? 'spm-flow-connector spm-flow-connector--done'
        : 'spm-flow-connector';
    });
  }

  function setPercent(pct, label) {
    var fill = byId('submission-progress-fill');
    var value = byId('submission-progress-value');
    var track = byId('submission-progress-track');
    var p = Math.max(0, Math.min(100, pct));

    if (fill) fill.style.width = p + '%';
    if (value) value.textContent = Math.round(p) + '% - ' + label;
    if (track) track.setAttribute('aria-valuenow', String(Math.round(p)));
  }

  function setStageCollapsed(stageId, collapsed) {
    var stage = byId(stageId);
    if (!stage) return;

    stage.classList.toggle('spm-stage--collapsed', Boolean(collapsed));

    var toggle = byId(stageId + '-toggle');
    if (toggle) {
      toggle.setAttribute('aria-expanded', String(!collapsed));
      toggle.textContent = collapsed ? 'Show' : 'Hide';
    }
  }

  function initStageToggle(stageId) {
    var toggle = byId(stageId + '-toggle');
    if (!toggle || toggle.dataset.bound === '1') return;

    toggle.addEventListener('click', function () {
      var stage = byId(stageId);
      if (!stage) return;
      setStageCollapsed(stageId, !stage.classList.contains('spm-stage--collapsed'));
    });

    toggle.dataset.bound = '1';
  }

  function resetModalBase() {
    var title = byId('submission-progress-title');
    var successState = byId('spm-success-state');
    var progressContent = byId('spm-progress-content');

    if (title) title.textContent = 'Workflow Status';
    if (progressContent) progressContent.hidden = false;
    if (successState) successState.hidden = true;

    STEP_IDS.forEach(function (id) { setStep(id, 'pending'); });
    AGENT_IDS.forEach(function (id) { setAgent(id, 'pending'); });

    setStage('spm-s1-badge', 'pending');
    setStage('spm-s2-badge', 'pending');

    var stage2 = byId('spm-stage2');
    if (stage2) stage2.classList.remove('spm-stage--active');

    setStageCollapsed('spm-stage1', false);
    setStageCollapsed('spm-stage2', false);
  }

  function setCaseContext(row) {
    var rx = String(row.getAttribute('data-rx-number') || '').trim();
    var status = row.querySelector('.status-pill') ? String(row.querySelector('.status-pill').textContent || '').trim() : '-';

    var successRx = byId('submission-success-rx-number');
    if (successRx) successRx.textContent = rx || '';

    return {
      rx: rx,
      status: status,
      normalizedStatus: String(row.getAttribute('data-status') || '').toLowerCase()
    };
  }

  function showCompletedState(caseInfo) {
    var successState = byId('spm-success-state');
    var title = byId('submission-progress-title');
    var desc = document.querySelector('.spm-success-description');
    var successTitle = document.querySelector('.spm-success-title');

    STEP_IDS.forEach(function (id) { setStep(id, 'done'); });
    AGENT_IDS.forEach(function (id) { setAgent(id, 'done'); });
    setStage('spm-s1-badge', 'done');
    setStage('spm-s2-badge', 'done');
    setFlowState(4);
    setPercent(100, 'Workflow complete');

    if (title) title.textContent = 'Workflow Status';
    if (successTitle) successTitle.textContent = 'Processes Completed';
    if (desc) {
      var suffix = caseInfo.status ? ' Current status: ' + caseInfo.status + '.' : '';
      desc.textContent = 'All processing stages are complete for this prescription.' + suffix;
    }
    if (successState) successState.hidden = false;

    setStageCollapsed('spm-stage1', true);
    setStageCollapsed('spm-stage2', true);
  }

  function showWorkflowOverviewState(caseInfo) {
    var successState = byId('spm-success-state');
    var title = byId('submission-progress-title');

    STEP_IDS.forEach(function (id) { setStep(id, 'done'); });
    AGENT_IDS.forEach(function (id) { setAgent(id, 'done'); });
    setStage('spm-s1-badge', 'done');
    setStage('spm-s2-badge', 'done');
    setFlowState(4);
    setPercent(100, 'Workflow complete');

    if (title) title.textContent = 'Workflow Status';
    if (successState) successState.hidden = true;

    setStageCollapsed('spm-stage1', false);
    setStageCollapsed('spm-stage2', false);
  }

  function openFromRow(row) {
    var modal = byId('submission-progress-modal');
    if (!modal || !row) return;

    resetModalBase();
    var caseInfo = setCaseContext(row);

    showWorkflowOverviewState(caseInfo);

    modal.classList.add('show');
  }

  function closeModal() {
    var modal = byId('submission-progress-modal');
    if (!modal) return;
    modal.classList.remove('show');
  }

  function copyRxNumber() {
    var rxNumber = (byId('submission-success-rx-number')?.textContent || '').trim();
    if (!rxNumber) return;
    
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(rxNumber).then(function () {
        if (typeof window.showToast === 'function') {
          window.showToast('RX Number copied to clipboard');
        }
      });
    }
  }

  function goToResultsFromModal() {
    var rxNumber = (byId('submission-success-rx-number')?.textContent || '').trim();
    if (!rxNumber) return;
    closeModal();

    var role = localStorage.getItem('role') || '';
    var lowerRole = role.toLowerCase();

    if (lowerRole === 'pharmacist') {
      if (typeof window.setSelectedRxNumber === 'function') {
        window.setSelectedRxNumber(rxNumber);
      }
      var searchInput = document.getElementById('results-search');
      if (searchInput) {
        searchInput.value = rxNumber;
      }
      window.location.hash = 'results';
      if (typeof window.handleResultsSearch === 'function') {
        setTimeout(function () { window.handleResultsSearch(); }, 100);
      }
    } else if (lowerRole === 'provider' || lowerRole === 'doctor') {
      window.location.href = '/review/' + encodeURIComponent(rxNumber);
    } else if (lowerRole === 'pbm') {
      window.location.href = '/pbm/review/' + encodeURIComponent(rxNumber);
    }
  }

  function bindCloseControls() {
    var closeBtn = byId('submission-progress-close');
    var modal = byId('submission-progress-modal');

    if (closeBtn && closeBtn.dataset.bound !== '1') {
      closeBtn.addEventListener('click', closeModal);
      closeBtn.dataset.bound = '1';
    }

    if (modal && modal.dataset.bound !== '1') {
      modal.addEventListener('click', function (event) {
        if (event.target === modal) {
          closeModal();
        }
      });
      modal.dataset.bound = '1';
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (!byId('submission-progress-modal')) return;

    initStageToggle('spm-stage1');
    initStageToggle('spm-stage2');
    bindCloseControls();

    window.WorkflowStatusModal = {
      openFromRow: openFromRow,
      close: closeModal
    };

    window.closeModal = closeModal;
    window.goToResultsFromModal = goToResultsFromModal;
    window.copyRxNumber = copyRxNumber;
  });
})();
