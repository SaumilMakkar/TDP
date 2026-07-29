(function () {
  'use strict';

  var currentStatsRange = 'all';
  var recordsExpanded = false;
  var recordsActiveFilter = 'all';
  var recordsVisibleLimit = 9;

    document.addEventListener('DOMContentLoaded', function () {
    if (!enforceDoctorAccess()) {
      return;
    }

    initProviderCardToggle();
    initRecordsTabs();
    initRecordsSearch();
    initViewAllToggle();
    initStatsFilter();
    initDayTabs();
    initRowNavigation();
    syncLiveOverviewStatus();
  });

  function parseDateCell(row, cellIndex) {
    var cell = row && row.cells && row.cells.length > cellIndex ? row.cells[cellIndex] : null;
    var raw = String((cell && cell.textContent) || '').trim();
    if (!raw || raw === '-') return null;
    var parsed = new Date(raw + 'T00:00:00');
    if (Number.isNaN(parsed.getTime())) return null;
    return new Date(parsed.getFullYear(), parsed.getMonth(), parsed.getDate());
  }

  function isDateInRange(dateOnly, range) {
    if (!dateOnly) return false;
    var now = new Date();
    var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());

    if (range === 'today') {
      return dateOnly.getTime() === today.getTime();
    }

    if (range === 'week') {
      // Match Due Summary behavior: count from today through Friday.
      var weekday = today.getDay();
      if (weekday === 0 || weekday === 6) {
        return false;
      }
      var friday = new Date(today);
      var daysUntilFriday = weekday >= 1 && weekday <= 5 ? (5 - weekday) : 0;
      friday.setDate(today.getDate() + daysUntilFriday);
      return dateOnly >= today && dateOnly <= friday;
    }

    return true;
  }

  function refreshPbmStatsByFilter() {
    var rows = Array.prototype.slice.call(document.querySelectorAll('.records-row'));
    var totalCount = 0;
    var pendingCount = 0;
    var completedCount = 0;
    var autoApproveCount = 0;

    rows.forEach(function (row) {
      var status = row.getAttribute('data-status') || 'pending';
      var dueDate = parseDateCell(row, 6);

      var include = true;
      if (currentStatsRange !== 'all') {
        // Keep stats aligned with Due Summary windows and due dates.
        include = status === 'pending' && isDateInRange(dueDate, currentStatsRange);
      }

      if (!include) return;

      totalCount += 1;
      var pill = row.querySelector('.status-pill');
      var pillClass = pill ? pill.className : '';

      if (status === 'pending') {
        pendingCount += 1;
      } else {
        completedCount += 1;
      }

      if (pillClass.indexOf('status-auto-approve') !== -1) {
        autoApproveCount += 1;
      }
    });

    updatePbmStats(totalCount, autoApproveCount, completedCount, pendingCount);
  }

  function initStatsFilter() {
    var buttons = document.querySelectorAll('.pbm-stats-filter-btn');
    if (!buttons.length) return;

    buttons.forEach(function (button) {
      button.addEventListener('click', function () {
        currentStatsRange = button.getAttribute('data-range') || 'all';
        buttons.forEach(function (btn) { btn.classList.remove('is-active'); });
        button.classList.add('is-active');
        refreshPbmStatsByFilter();
      });
    });
  }

  function enforceDoctorAccess() {
    var token = localStorage.getItem('token');
    var role = (localStorage.getItem('role') || '').toLowerCase();

    if (!token || role !== 'pbm') {
      window.location.href = '/';
      return false;
    }

    return true;
  }

  function authFetch(url, options) {
    var token = localStorage.getItem('token');
    var headers = Object.assign({}, (options && options.headers) || {});
    if (token && !headers.Authorization) {
      headers.Authorization = 'Bearer ' + token;
    }
    return fetch(url, Object.assign({}, options || {}, { headers: headers }));
  }

  // ---- Provider button -> shows the small profile card (Alex / NPI) ----
  function initProviderCardToggle() {
    var toggleBtn = document.getElementById('provider-toggle-btn');
    var card = document.getElementById('provider-card');
    var logoutBtn = document.getElementById('provider-logout-btn');
    if (!toggleBtn || !card) return;

    toggleBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      card.classList.toggle('is-open');
    });

    document.addEventListener('click', function (e) {
      if (!card.contains(e.target) && e.target !== toggleBtn) {
        card.classList.remove('is-open');
      }
    });

        if (logoutBtn) {
      logoutBtn.addEventListener('click', function () {
        fetch('/api/logout', { method: 'POST' }).catch(function () {});
        localStorage.removeItem('token');
        localStorage.removeItem('role');
        localStorage.removeItem('username');
        window.location.href = '/';
      });
    }
  }

  // ---- Pending / Completed / All tabs ----
  function initRecordsTabs() {
    var tabs = document.querySelectorAll('.records-tab');

    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        tabs.forEach(function (t) { t.classList.remove('is-active'); });
        tab.classList.add('is-active');
        recordsActiveFilter = tab.getAttribute('data-filter') || 'all';
        recordsExpanded = false;
        refreshVisibleRecords();
      });
    });

    var activeTab = document.querySelector('.records-tab.is-active');
    recordsActiveFilter = activeTab ? (activeTab.getAttribute('data-filter') || 'all') : 'all';
    refreshVisibleRecords();
  }

  // ---- Search box: filters by Rx number / member id / medication ----
  function initRecordsSearch() {
    var input = document.getElementById('records-search-input');
    if (!input) return;
    input.addEventListener('input', function () {
      recordsExpanded = false;
      refreshVisibleRecords();
    });
  }

  function rowMatchesFilters(row, term) {
    var status = row.getAttribute('data-status');
    var matchesTab = recordsActiveFilter === 'all' || recordsActiveFilter === status;
    if (!matchesTab) return false;

    if (!term) return true;
    var haystack = (row.getAttribute('data-search') || '').toLowerCase();
    return haystack.indexOf(term) !== -1;
  }

  function refreshVisibleRecords() {
    var rows = Array.prototype.slice.call(document.querySelectorAll('.records-row'));
    var btn = document.getElementById('view-all-btn');
    var input = document.getElementById('records-search-input');
    var term = input ? input.value.trim().toLowerCase() : '';

    var filtered = rows.filter(function (row) {
      return rowMatchesFilters(row, term);
    });

    rows.forEach(function (row) {
      row.style.display = 'none';
      row.classList.add('row-hidden');
    });

    var limit = recordsExpanded ? filtered.length : recordsVisibleLimit;
    filtered.forEach(function (row, index) {
      if (index < limit) {
        row.classList.remove('row-hidden');
        row.style.display = 'table-row';
      }
    });

    if (!btn) return;
    if (filtered.length <= recordsVisibleLimit) {
      btn.style.display = 'none';
      btn.textContent = 'View all prescriptions \u2192';
      return;
    }

    btn.style.display = 'block';
    btn.textContent = recordsExpanded
      ? 'Show fewer prescriptions \u2191'
      : 'View all ' + filtered.length + ' prescriptions \u2192';
  }

  function applySearchFilter() {
    refreshVisibleRecords();
  }

  // ---- "View all N prescriptions" reveals the remaining rows ----
  function initViewAllToggle() {
    var btn = document.getElementById('view-all-btn');
    if (!btn) return;

    btn.addEventListener('click', function () {
      recordsExpanded = !recordsExpanded;
      refreshVisibleRecords();
    });
  }

  function initRowNavigation() {
    var rows = document.querySelectorAll('.records-row');
    rows.forEach(function (row) {
      row.style.cursor = 'pointer';
      row.addEventListener('click', function (event) {
        var statusBtn = event.target.closest('.status-pill-trigger');
        if (statusBtn) {
          event.preventDefault();
          event.stopPropagation();
          if (window.WorkflowStatusModal && typeof window.WorkflowStatusModal.openFromRow === 'function') {
            window.WorkflowStatusModal.openFromRow(row);
          }
          return;
        }

        var rx = row.getAttribute('data-rx-number');
        if (rx) {
          window.location.href = '/pbm/review/' + encodeURIComponent(rx);
        }
      });
    });
  }

  function formatIsoDate(date) {
    var year = date.getFullYear();
    var month = String(date.getMonth() + 1).padStart(2, '0');
    var day = String(date.getDate()).padStart(2, '0');
    return year + '-' + month + '-' + day;
  }

  function weekdayFromIsoDate(rawDate) {
    var value = String(rawDate || '').trim();
    if (!value || value === '-') return null;

    var parsed = new Date(value + 'T00:00:00');
    if (Number.isNaN(parsed.getTime())) {
      return null;
    }

    var days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    return days[parsed.getDay()] || null;
  }

  function fullWeekdayName(shortDay) {
    var mapping = {
      Mon: 'Monday',
      Tue: 'Tuesday',
      Wed: 'Wednesday',
      Thu: 'Thursday',
      Fri: 'Friday',
      Sat: 'Saturday',
      Sun: 'Sunday'
    };
    return mapping[shortDay] || shortDay;
  }

  function deriveDueDate(live, pillLabel) {
    var rawDate = live && live.date_written ? String(live.date_written).trim() : '';
    var baseDate = rawDate ? new Date(rawDate + 'T00:00:00') : new Date();
    if (Number.isNaN(baseDate.getTime())) {
      baseDate = new Date();
    }

    var normalizedLabel = String(pillLabel || '').toLowerCase();
    var offsetDays = 1;
    if (normalizedLabel === 'under review') {
      offsetDays = 3;
    } else if (normalizedLabel === 'pending') {
      offsetDays = 2;
    }

    baseDate.setDate(baseDate.getDate() + offsetDays);
    return formatIsoDate(baseDate);
  }

  function renderDueDay(day, grouped) {
    var dayLabel = document.getElementById('due-day-label');
    var dayCount = document.getElementById('due-day-count');
    var dayList = document.getElementById('due-day-list');
    var items = grouped[day] || [];

    if (dayLabel) dayLabel.textContent = 'Prescriptions due ' + fullWeekdayName(day);
    if (dayCount) dayCount.textContent = String(items.length);
    if (!dayList) return;

    if (!items.length) {
      dayList.innerHTML = '<div class="due-day-empty">No prescriptions due.</div>';
      return;
    }

    dayList.innerHTML = items.map(function (item) {
      return '<div class="due-day-item" data-day="' + day + '">' +
        '<div class="due-day-item-rx">' + item.rx_number + '</div>' +
        '<div class="due-day-item-member">' + item.member_id + '</div>' +
      '</div>';
    }).join('');
  }

  function rebuildDueSummaryFromRows() {
    var grouped = { Mon: [], Tue: [], Wed: [], Thu: [], Fri: [] };
    var todayCount = 0;
    var weekCount = 0;
    var now = new Date();
    var todayIso = formatIsoDate(now);
    var todayDateOnly = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var todayWeekday = todayDateOnly.getDay(); // 0=Sun, 1=Mon, ... 6=Sat
    var fridayDate = null;
    if (todayWeekday >= 1 && todayWeekday <= 5) {
      fridayDate = new Date(todayDateOnly);
      fridayDate.setDate(todayDateOnly.getDate() + (5 - todayWeekday));
    }

    document.querySelectorAll('.records-row').forEach(function (row) {
      var status = row.getAttribute('data-status');
      var dueDateCell = row.cells && row.cells.length > 6 ? row.cells[6] : null;
      if (status !== 'pending' || !dueDateCell) {
        return;
      }

      var dueDate = String(dueDateCell.textContent || '').trim();
      var day = weekdayFromIsoDate(dueDate);
      if (!day || !grouped[day]) {
        return;
      }

      grouped[day].push({
        rx_number: row.getAttribute('data-rx-number') || '',
        member_id: row.cells && row.cells.length > 1 ? String(row.cells[1].textContent || '').trim() : ''
      });
      var dueDateObj = new Date(dueDate + 'T00:00:00');
      if (!Number.isNaN(dueDateObj.getTime()) && fridayDate && dueDateObj >= todayDateOnly && dueDateObj <= fridayDate) {
        weekCount += 1;
      }
      if (dueDate === todayIso) {
        todayCount += 1;
      }
    });

    window.__PROVIDER_DATA__ = grouped;

    var activeTab = document.querySelector('.day-tab.is-active');
    var activeDay = activeTab ? activeTab.getAttribute('data-day') : 'Mon';
    var countNodes = document.querySelectorAll('.due-summary-row .due-summary-count');
    if (countNodes.length > 0) {
      countNodes[0].textContent = String(todayCount);
    }
    if (countNodes.length > 1) {
      countNodes[1].textContent = String(weekCount);
    }

    renderDueDay(activeDay, grouped);
  }

  function updatePbmStats(totalCount, autoApproveCount, completedCount, pendingCount) {
    var totalNode = document.getElementById('pbm-stat-total');
    var autoNode = document.getElementById('pbm-stat-auto');
    var completedNode = document.getElementById('pbm-stat-completed');
    var pendingNode = document.getElementById('pbm-stat-pending');
    var autoCircle = document.getElementById('pbm-stat-auto-circle');
    var completedCircle = document.getElementById('pbm-stat-completed-circle');
    var pendingCircle = document.getElementById('pbm-stat-pending-circle');

    var safeTotal = totalCount > 0 ? totalCount : 0;
    var autoPct = safeTotal ? Math.round((autoApproveCount / safeTotal) * 100) : 0;
    var completedPct = safeTotal ? Math.round((completedCount / safeTotal) * 100) : 0;
    var pendingPct = safeTotal ? Math.round((pendingCount / safeTotal) * 100) : 0;

    if (totalNode) totalNode.textContent = String(totalCount);
    if (autoNode) autoNode.textContent = String(autoPct) + '%';
    if (completedNode) completedNode.textContent = String(completedPct) + '%';
    if (pendingNode) pendingNode.textContent = String(pendingPct) + '%';

    if (autoCircle) autoCircle.style.setProperty('--pct', String(autoPct));
    if (completedCircle) completedCircle.style.setProperty('--pct', String(completedPct));
    if (pendingCircle) pendingCircle.style.setProperty('--pct', String(pendingPct));
  }

  async function syncLiveOverviewStatus() {
    try {
      var response = await authFetch('/api/prescriptions');
      if (!response.ok) return;
      var data = await response.json();
      var byRx = {};
      var pendingCount = 0;
      var completedCount = 0;
      var totalCount = 0;
      var autoApproveCount = 0;

      (Array.isArray(data) ? data : []).forEach(function (item) {
        byRx[String(item.rx_number || '').trim()] = item;
      });

      document.querySelectorAll('.records-row').forEach(function (row) {
        var rx = row.getAttribute('data-rx-number');
        var live = byRx[rx];
        var pill = row.querySelector('.status-pill');
        var dueDateCell = row.cells && row.cells.length > 6 ? row.cells[6] : null;
        if (!pill) return;

        totalCount += 1;

        var label = pill.textContent.trim();
        var className = pill.className;
        var normalizedStatus = row.getAttribute('data-status') || 'pending';
        var decisionStatus = live && live.decision_status ? String(live.decision_status).toUpperCase() : '';
        var pbmStatus = live && live.pbm_status ? String(live.pbm_status).toUpperCase() : '';

        if (pbmStatus === 'APPROVED') {
          label = 'Auto Approve';
          className = 'status-pill status-auto-approve';
          normalizedStatus = 'completed';
          autoApproveCount += 1;
          completedCount += 1;
        } else if (decisionStatus === 'ACCEPTED') {
          label = 'Accept';
          className = 'status-pill status-accept';
          normalizedStatus = 'completed';
          completedCount += 1;
        } else if (decisionStatus === 'REJECTED') {
          label = 'DAW';
          className = 'status-pill status-daw';
          normalizedStatus = 'completed';
          completedCount += 1;
        } else if (pbmStatus === 'KEEP_ORIGINAL') {
          label = 'DAW';
          className = 'status-pill status-daw';
          normalizedStatus = 'completed';
          completedCount += 1;
        } else if (pbmStatus === 'ESCALATED') {
          label = 'Under Review';
          className = 'status-pill status-under-review';
          normalizedStatus = 'pending';
          pendingCount += 1;
        } else if (pbmStatus === 'PENDING_REVIEW') {
          label = 'Pending';
          className = 'status-pill status-pending';
          normalizedStatus = 'pending';
          pendingCount += 1;
        } else if (pbmStatus === 'IN_PROGRESS') {
          label = 'In Progress';
          className = 'status-pill status-in-progress';
          normalizedStatus = 'pending';
          pendingCount += 1;
        } else if (pill.textContent.trim().toLowerCase() === 'pending') {
          normalizedStatus = 'pending';
          pendingCount += 1;
        } else if (pill.textContent.trim().toLowerCase() === 'in progress') {
          normalizedStatus = 'pending';
          className = 'status-pill status-in-progress';
          pendingCount += 1;
        } else if (pill.textContent.trim().toLowerCase() === 'under review') {
          normalizedStatus = 'pending';
          className = 'status-pill status-under-review';
          pendingCount += 1;
        } else {
          normalizedStatus = 'completed';
          completedCount += 1;
        }

        pill.textContent = label;
        pill.className = className;
        row.setAttribute('data-status', normalizedStatus);

        if (dueDateCell) {
          var existingDueDate = String(dueDateCell.textContent || '').trim();
          if (normalizedStatus === 'completed') {
            dueDateCell.textContent = '-';
          } else if (!existingDueDate || existingDueDate === '-') {
            dueDateCell.textContent = deriveDueDate(live, label);
          }
        }
      });

      var allCountNode = document.getElementById('all-count');
      var pendingCountNode = document.getElementById('pending-count');
      var completedCountNode = document.getElementById('completed-count');
      if (allCountNode) allCountNode.textContent = 'All (' + totalCount + ')';
      if (pendingCountNode) pendingCountNode.textContent = 'Pending (' + pendingCount + ')';
      if (completedCountNode) completedCountNode.textContent = 'Completed (' + completedCount + ')';
      refreshPbmStatsByFilter();
      refreshVisibleRecords();
      rebuildDueSummaryFromRows();
    } catch (error) {
      return;
    }
  }

  // ---- Due Summary day tabs (Mon/Tue/Wed/Thu/Fri) ----
  function initDayTabs() {
    var dayTabs = document.querySelectorAll('.day-tab');
    var todayDate = window.__TODAY_DATE__ || '';

    dayTabs.forEach(function (tab) {
      var tabDate = tab.getAttribute('title') || '';
      if (tabDate && todayDate && tabDate === todayDate) {
        tab.classList.add('is-today');
      }

      tab.addEventListener('click', function () {
        dayTabs.forEach(function (t) { t.classList.remove('is-active'); });
        tab.classList.add('is-active');

        var day = tab.getAttribute('data-day');
        renderDueDay(day, window.__PROVIDER_DATA__ || {});
      });
    });
  }
})();




