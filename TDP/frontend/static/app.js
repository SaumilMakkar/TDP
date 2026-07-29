// ============================================
// PBM Prescription System — Client Logic
// ============================================

const state = {
  currentView: 'submit',
  pollInterval: null,
  initialized: false,
  appVisible: false,
  pendingAppLaunch: false,
  selectedRxNumber: null
};

const ROLE_PERMISSIONS = {
  pharmacist: ['submit', 'dashboard', 'results'],
  provider: ['dashboard', 'results'],
  pbm: ['dashboard', 'results']
};

function isProviderRole(role = getCurrentRole()) {
  const normalized = (role || '').toLowerCase();
  return normalized === 'provider' || normalized === 'doctor';
}

function getCurrentRole() {
  return (localStorage.getItem('role') || '').toLowerCase();
}

function getAllowedViews(role = getCurrentRole()) {
  return ROLE_PERMISSIONS[role] || [];
}

function getDefaultViewForRole(role = getCurrentRole()) {
  if (isProviderRole(role)) {
    return 'dashboard';
  }
  const allowed = getAllowedViews(role);
  return allowed[0] || 'results';
}

function getRoleHomePath(role = getCurrentRole()) {
  if (isProviderRole(role)) {
    return '/provider';
  }
  if ((role || '').toLowerCase() === 'pbm') {
    return '/pbm';
  }
  return '';
}

function canAccessView(viewId, role = getCurrentRole()) {
  return getAllowedViews(role).includes(viewId);
}

function canSubmitDecision(role = getCurrentRole()) {
  return isProviderRole(role);
}

function updateResultsNavLock() {
  const resultsNav = document.getElementById('nav-results');
  if (!resultsNav) return;

  const providerNeedsSelection = isProviderRole() && !state.selectedRxNumber;
  resultsNav.classList.toggle('disabled', providerNeedsSelection);
  resultsNav.setAttribute('aria-disabled', String(providerNeedsSelection));
  resultsNav.title = providerNeedsSelection
    ? 'Select a prescription from Overview first.'
    : '';
}

function setSelectedRxNumber(rxNumber) {
  const value = String(rxNumber || '').trim();
  state.selectedRxNumber = value || null;
  updateResultsNavLock();
}

function roleLabel(role) {
  const labels = {
    pharmacist: 'Pharmacist',
    provider: 'Provider',
    doctor: 'Provider',
    pbm: 'PBM'
  };
  return labels[role] || 'Portal User';
}

function applyRoleAccess() {
  const role = getCurrentRole();
  const allowed = new Set(getAllowedViews(role));
  document.querySelectorAll('.nav-item').forEach(item => {
    const view = item.getAttribute('data-view');
    item.style.display = allowed.has(view) ? 'flex' : 'none';
  });

  const resultsNav = document.getElementById('nav-results');
  if (resultsNav) {
    resultsNav.textContent = isProviderRole(role) ? 'Review & Decision' : 'Review';
  }

  updateResultsNavLock();
}

function showSystemApp() {
  const landingPage = document.getElementById('landing-page');
  const appLayout = document.getElementById('app-layout');

  if (landingPage) landingPage.style.display = 'none';
  if (appLayout) appLayout.style.display = 'flex';
  state.appVisible = true;
}

function showLandingPage() {
  const landingPage = document.getElementById('landing-page');
  const appLayout = document.getElementById('app-layout');

  if (landingPage) landingPage.style.display = 'block';
  if (appLayout) appLayout.style.display = 'none';
  state.appVisible = false;
}


function autofetch(url, options = {}) {
  const token = localStorage.getItem('token');
  const headers = {
    ...(options.headers || {})
  };

  if (token && !headers.Authorization) {
    headers.Authorization = `Bearer ${token}`;
  }

  return fetch(url, {
    ...options,
    headers
  }).then(res => {
    if (res.status === 401 && url !== '/api/login') {
      logout();
      showToast('Session expired. Please login again.');
    }
    return res;
  });
}


function openAuthModal(mode = 'login', pendingAppLaunch = true) {
  const authModal = document.getElementById('auth-modal');
  if (!authModal) return;

  state.pendingAppLaunch = pendingAppLaunch;
  authModal.classList.add('show');
}

function closeAuthModal() {
  const authModal = document.getElementById('auth-modal');
  if (!authModal) return;
  authModal.classList.remove('show');
}

function openUploadExcelModal() {
  const modal = document.getElementById('upload-excel-modal');
  if (!modal) return;
  modal.classList.add('show');
}

function closeUploadExcelModal() {
  const modal = document.getElementById('upload-excel-modal');
  if (!modal) return;
  modal.classList.remove('show');
}

function normalizeExcelKey(key) {
  return String(key || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

function setFieldValue(fieldId, value, eventName = 'input') {
  const field = document.getElementById(fieldId);
  if (!field) return;
  field.value = value;
  field.dispatchEvent(new Event(eventName, { bubbles: true }));
}

function firstNonEmpty(obj, keys) {
  for (const key of keys) {
    const value = obj[key];
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      return String(value).trim();
    }
  }
  return '';
}

function extractRowFromColumnOrientedRows(rows) {
  const mapped = {};

  for (const raw of rows) {
    const normalized = {};
    Object.entries(raw || {}).forEach(([k, v]) => {
      normalized[normalizeExcelKey(k)] = v;
    });

    const key = firstNonEmpty(normalized, ['field', 'field_name', 'column', 'name', 'key']);
    const value = firstNonEmpty(normalized, ['value', 'field_value', 'data', 'input']);
    if (!key) continue;

    mapped[normalizeExcelKey(key)] = value;
  }

  return mapped;
}

async function loadExcelIntoSubmitForm(file) {
  if (!window.XLSX) {
    showToast('Excel parser is not available. Please refresh the page.');
    return;
  }

  const arrayBuffer = await file.arrayBuffer();
  const workbook = XLSX.read(arrayBuffer, { type: 'array' });
  const firstSheetName = workbook.SheetNames[0];
  if (!firstSheetName) {
    showToast('Excel file has no sheet.');
    return;
  }

  const rows = XLSX.utils.sheet_to_json(workbook.Sheets[firstSheetName], { defval: '' });
  if (!rows.length) {
    showToast('Excel file has no data rows.');
    return;
  }

  const source = rows[0];
  const normalizedSource = {};
  Object.entries(source).forEach(([k, v]) => {
    normalizedSource[normalizeExcelKey(k)] = v;
  });

  const looksColumnOriented = (
    Object.prototype.hasOwnProperty.call(normalizedSource, 'field') &&
    Object.prototype.hasOwnProperty.call(normalizedSource, 'value')
  ) || (
    Object.prototype.hasOwnProperty.call(normalizedSource, 'field_name') &&
    Object.prototype.hasOwnProperty.call(normalizedSource, 'field_value')
  );

  const row = looksColumnOriented
    ? extractRowFromColumnOrientedRows(rows)
    : normalizedSource;

  const diagnosisCode = firstNonEmpty(row, ['diagnosis_code', 'icd10', 'icd_10', 'diagnosis_icd10']);
  const diagnosisText = firstNonEmpty(row, ['diagnosis', 'diagnosis_description', 'dx_description']);
  const diagnosisValue = diagnosisCode && diagnosisText
    ? `${diagnosisCode} - ${diagnosisText}`
    : (diagnosisCode || diagnosisText);

  const memberId = firstNonEmpty(row, ['member_id', 'patient_id', 'patient_account_id']);
  const npi = firstNonEmpty(row, ['prescriber_npi', 'npi_number', 'provider_npi']);
  const pharmacyId = firstNonEmpty(row, ['pharmacy_id', 'phr_id']);
  const medication = firstNonEmpty(row, ['medication', 'prod_nm', 'drug_name']);
  const strength = firstNonEmpty(row, ['strength', 'dosage_size', 'dose']);
  const frequency = firstNonEmpty(row, ['frequency', 'sig_frequency']).toUpperCase();
  const daysSupply = firstNonEmpty(row, ['days_supply', 'day_supply']);

  if (memberId) setFieldValue('patient_id', memberId);
  if (npi) setFieldValue('npi_number', npi);
  if (pharmacyId) setFieldValue('phr_id', pharmacyId);
  if (diagnosisValue) setFieldValue('diagnosis', diagnosisValue);
  if (medication) setFieldValue('prod_nm', medication);
  if (strength) setFieldValue('dosage_size', strength);
  if (daysSupply) setFieldValue('days_supply', daysSupply);

  const frequencyField = document.getElementById('frequency');
  if (frequencyField) {
    const valid = Array.from(frequencyField.options).map(o => o.value.toUpperCase());
    frequencyField.value = valid.includes(frequency) ? frequency : '';
    frequencyField.dispatchEvent(new Event('change', { bubbles: true }));
  }

  const rxcuiField = document.getElementById('prod_rxcui');
  if (rxcuiField) {
    rxcuiField.value = firstNonEmpty(row, ['prod_rxcui', 'rxcui']);
  }

  showToast('Excel data loaded into form.');
}

function initUploadExcelFlow() {
  const uploadBtn = document.getElementById('submit-upload-btn');
  const modal = document.getElementById('upload-excel-modal');
  const closeBtn = document.getElementById('upload-excel-close');
  const cancelBtn = document.getElementById('upload-excel-cancel');
  const applyBtn = document.getElementById('upload-excel-apply');
  const fileInput = document.getElementById('upload-excel-file');
  const status = document.getElementById('upload-excel-file-status');

  if (!uploadBtn || !modal || !applyBtn || !fileInput || !status) return;

  uploadBtn.addEventListener('click', openUploadExcelModal);

  if (closeBtn) closeBtn.addEventListener('click', closeUploadExcelModal);
  if (cancelBtn) cancelBtn.addEventListener('click', closeUploadExcelModal);

  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeUploadExcelModal();
  });

  fileInput.addEventListener('change', () => {
    const file = fileInput.files && fileInput.files[0];
    status.textContent = file ? `Selected: ${file.name}` : 'No file selected.';
  });

  applyBtn.addEventListener('click', async () => {
    const file = fileInput.files && fileInput.files[0];
    if (!file) {
      showToast('Please choose an Excel file first.');
      return;
    }

    const validExt = /\.(xlsx|xls)$/i.test(file.name);
    if (!validExt) {
      showToast('Please upload .xlsx or .xls file.');
      return;
    }

    try {
      applyBtn.disabled = true;
      applyBtn.textContent = 'Loading...';
      await loadExcelIntoSubmitForm(file);
      closeUploadExcelModal();
    } catch (error) {
      console.error(error);
      showToast('Could not read the Excel file. Check the template format.');
    } finally {
      applyBtn.disabled = false;
      applyBtn.textContent = 'Load Into Form';
    }
  });
}

async function performLogin(loginId, password) {

  if (!loginId || !password) {
    showToast('Enter login ID and password');
    return false;
  }

  const res = await autofetch('/api/login', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      password,
      login_id: loginId || null,
    })
  });

  const data = await res.json();

  if (res.ok) {
    localStorage.setItem('token', data.token);
    localStorage.setItem('role', data.role || 'user');
    if (data.username) {
      localStorage.setItem('username', data.username);
    } else {
      localStorage.setItem('username', roleLabel(data.role || 'user'));
    }
    if (data.pharmacist_id) localStorage.setItem('pharmacist_id', data.pharmacist_id);
    else localStorage.removeItem('pharmacist_id');
    if (data.provider_npi) localStorage.setItem('provider_npi', data.provider_npi);
    else localStorage.removeItem('provider_npi');
    if (data.pbm_id) localStorage.setItem('pbm_id', data.pbm_id);
    else localStorage.removeItem('pbm_id');
    if (data.full_name) localStorage.setItem('full_name', data.full_name);
    else localStorage.removeItem('full_name');
    setAuthUiState(true);

    if (data.role === 'provider') {
      window.location.href = '/provider';
      return true;
    }

    if (data.role === 'pbm') {
      window.location.href = '/pbm';
      return true;
    }

    showToast('Login successful');
    return true;
  } else {
    showToast(data.error || 'Login failed');
    return false;
  }
}

async function login() {
  const passwordInput = document.getElementById('password');
  const loginIdInput = document.getElementById('login-id') || document.getElementById('login-role-id');
  if (!passwordInput || !loginIdInput) return;
  const password = passwordInput.value;
  const loginId = loginIdInput.value.trim();
  await performLogin(loginId, password);
}

async function loginFromModal() {
  const loginId = document.getElementById('modal-login-role-id').value.trim();
  const password = document.getElementById('modal-password').value;
  const success = await performLogin(loginId, password);

  if (success) {
    closeAuthModal();
    if (state.pendingAppLaunch) {
      showSystemApp();
      window.location.hash = getDefaultViewForRole();
      state.pendingAppLaunch = false;
    }
  }
}

async function performRegistration(password, role, pharmacistId = '', providerNpi = '', pbmId = '', fullName = '') {

  if (!password) {
    showToast('Enter password to register');
    return false;
  }

  if (role === 'pharmacist' && !pharmacistId) {
    showToast('Enter pharmacist ID');
    return false;
  }

  if (role === 'provider' && !providerNpi) {
    showToast('Enter provider NPI ID');
    return false;
  }

  if (role === 'pbm' && !pbmId) {
    showToast('Enter PBM ID');
    return false;
  }

  const res = await fetch('/api/register', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      password,
      role,
      full_name: fullName || null,
      pharmacist_id: pharmacistId || null,
      provider_npi: providerNpi || null,
      pbm_id: pbmId || null,
    })
  });

  const data = await res.json();

  if (res.ok) {
    const loginId = data.login_id ? ` Login ID: ${data.login_id}` : '';
    showToast(`Registration successful. You can now login.${loginId}`);
    return true;
  } else {
    showToast(data.error || 'Registration failed');
    return false;
  }
}

async function registerUser() {
  const passwordInput = document.getElementById('register-password');
  const roleInput = document.getElementById('register-role');
  const roleIdInput = document.getElementById('register-role-id');
  if (!passwordInput || !roleInput || !roleIdInput) return;

  const password = passwordInput.value;
  const role = roleInput.value;
  const roleId = roleIdInput.value.trim();
  const pharmacistId = role === 'pharmacist' ? roleId : '';
  const providerNpi = role === 'provider' ? roleId : '';
  const pbmId = role === 'pbm' ? roleId : '';
  const success = await performRegistration(password, role, pharmacistId, providerNpi, pbmId);

  if (success) {
    passwordInput.value = '';
    roleIdInput.value = '';
  }
}

async function registerFromModal() {
  const password = document.getElementById('modal-register-password').value;
  const role = document.getElementById('modal-register-role').value;
  const roleId = document.getElementById('modal-register-role-id').value.trim();
  const fullName = (document.getElementById('modal-register-name').value || '').trim();
  const pharmacistId = role === 'pharmacist' ? roleId : '';
  const providerNpi = role === 'provider' ? roleId : '';
  const pbmId = role === 'pbm' ? roleId : '';
  const success = await performRegistration(password, role, pharmacistId, providerNpi, pbmId, fullName);

  if (success) {
    document.getElementById('modal-register-password').value = '';
    document.getElementById('modal-register-role-id').value = '';
    document.getElementById('modal-register-name').value = '';
  }
}

function syncRegisterRoleIdField() {
  const roleSelect = document.getElementById('modal-register-role');
  const idGroup = document.getElementById('modal-register-id-group');
  const idLabel = document.getElementById('modal-register-role-id-label');
  const idInput = document.getElementById('modal-register-role-id');
  if (!roleSelect || !idGroup || !idLabel || !idInput) return;

  const role = roleSelect.value;
  if (role === 'pharmacist') {
    idGroup.style.display = 'block';
    idLabel.textContent = 'Pharmacist ID';
    idInput.placeholder = 'Enter pharmacist ID';
    idInput.required = true;
  } else if (role === 'provider') {
    idGroup.style.display = 'block';
    idLabel.textContent = 'Provider NPI ID';
    idInput.placeholder = 'Enter 10-digit NPI ID';
    idInput.required = true;
  } else if (role === 'pbm') {
    idGroup.style.display = 'block';
    idLabel.textContent = 'PBM ID';
    idInput.placeholder = 'Enter PBM ID';
    idInput.required = true;
  } else {
    idGroup.style.display = 'none';
    idInput.value = '';
    idInput.required = false;
  }
}

function logout() {
  localStorage.removeItem('token');
  localStorage.removeItem('role');
  localStorage.removeItem('username');
  localStorage.removeItem('pharmacist_id');
  localStorage.removeItem('provider_npi');
  localStorage.removeItem('pbm_id');
  localStorage.removeItem('full_name');
  setSelectedRxNumber(null);
  setAuthUiState(false);
  
  // Close avatar dropdown if open
  const dropdown = document.getElementById('user-dropdown-menu');
  if (dropdown) {
    dropdown.classList.remove('show');
  }
  
  showToast('Logged out');
  showLandingPage();
}

function _buildIdentityLine(role, isLoggedIn) {
  if (!isLoggedIn) return 'Role';
  const pharmacistId = localStorage.getItem('pharmacist_id');
  const providerNpi  = localStorage.getItem('provider_npi');
  const pbmId = localStorage.getItem('pbm_id');
  const roleName     = roleLabel(role);
  if (role === 'pharmacist' && pharmacistId) return `${roleName} · ID: ${pharmacistId}`;
  if (isProviderRole(role) && providerNpi)  return `${roleName} · NPI: ${providerNpi}`;
  if (role === 'pbm' && pbmId) return `${roleName} · ID: ${pbmId}`;
  return roleName;
}

function _buildNavbarLabel(role) {
  const pharmacistId = localStorage.getItem('pharmacist_id');
  const providerNpi  = localStorage.getItem('provider_npi');
  const roleName     = roleLabel(role);
  if (role === 'pharmacist' && pharmacistId) return roleName;
  if (isProviderRole(role) && providerNpi)  return roleName;
  return roleName;
}

function setAuthUiState(isLoggedIn) {
  const full_name = localStorage.getItem('full_name');
  const username  = full_name || localStorage.getItem('username') || 'User';
  const role      = getCurrentRole();
  const roleName  = isLoggedIn ? roleLabel(role) : 'Login';

  // Role pill badge — shows only the role label
  const navbarBadge = document.getElementById('navbar-role-badge');
  if (navbarBadge) {
    navbarBadge.textContent = isLoggedIn ? _buildNavbarLabel(role) : 'Login';
  }

  // Dropdown name (full name, prominent)
  const dropdownUserName = document.getElementById('dropdown-user-name');
  if (dropdownUserName) dropdownUserName.textContent = isLoggedIn ? username : '—';

  // Dropdown identity line: "Pharmacist · ID: PHARMA001"
  const dropdownIdentity = document.getElementById('dropdown-user-identity');
  if (dropdownIdentity) dropdownIdentity.textContent = _buildIdentityLine(role, isLoggedIn);

  if (isLoggedIn) {
    applyRoleAccess();
  }
}





function init() {
  if (state.initialized) {
    setAuthUiState(Boolean(localStorage.getItem('token')));
    return;
  }
  state.initialized = true;

  window.addEventListener('hashchange', handleRoute);
  
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', (e) => {
      e.preventDefault();
      const view = item.getAttribute('data-view');
      if (view === 'results' && isProviderRole() && !state.selectedRxNumber) {
        showToast('Select a prescription from Overview first.');
        return;
      }
      window.location.hash = view;
    });
  });

  document.getElementById('prescription-form').addEventListener('submit', handleFormSubmit);
  initDrugAutocomplete();
  initDiagnosisAutocomplete();
  initRecentRxSearch();
  initUploadExcelFlow();
  initSubmissionProgressModalControls();
  document.getElementById('results-btn').addEventListener('click', handleResultsSearch);
  
  // Old sidebar auth buttons (removed - now using modal)
  // document.getElementById('login-btn').addEventListener('click', login);
  // document.getElementById('register-btn').addEventListener('click', registerUser);
  
  const dropdownLogoutBtn = document.getElementById('dropdown-logout-btn');
  if (dropdownLogoutBtn) {
    dropdownLogoutBtn.addEventListener('click', logout);
  }

  const avatarBtn = document.getElementById('user-avatar-btn');
  const dropdownMenu = document.getElementById('user-dropdown-menu');
  if (avatarBtn && dropdownMenu) {
    avatarBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const isOpen = dropdownMenu.classList.toggle('show');
      avatarBtn.setAttribute('aria-expanded', String(isOpen));
      // Flip chevron
      const chevron = avatarBtn.querySelector('.pill-chevron');
      if (chevron) chevron.style.transform = isOpen ? 'rotate(180deg)' : '';
    });
    
    // Close dropdown on click outside
    document.addEventListener('click', (e) => {
      if (!avatarBtn.contains(e.target) && !dropdownMenu.contains(e.target)) {
        dropdownMenu.classList.remove('show');
        avatarBtn.setAttribute('aria-expanded', 'false');
        const chevron = avatarBtn.querySelector('.pill-chevron');
        if (chevron) chevron.style.transform = '';
      }
    });
  }

  const openSystemBtn = document.getElementById('open-system-btn');
  if (openSystemBtn) {
    openSystemBtn.addEventListener('click', () => {
      if (localStorage.getItem('token')) {
        const roleHomePath = getRoleHomePath();
        if (roleHomePath) {
          window.location.href = roleHomePath;
          return;
        }
        showSystemApp();
        window.location.hash = getDefaultViewForRole();
      } else {
        openAuthModal('login', true);
      }
    });
  }

  const startTrialBtn = document.getElementById('start-trial-btn');
  if (startTrialBtn) {
    startTrialBtn.addEventListener('click', () => {
      if (localStorage.getItem('token')) {
        const roleHomePath = getRoleHomePath();
        if (roleHomePath) {
          window.location.href = roleHomePath;
          return;
        }
        showSystemApp();
        window.location.hash = getDefaultViewForRole();
      } else {
        openAuthModal('login', true);
      }
    });
  }

  const brandAuthBtn = document.getElementById('open-auth-brand-btn');
  if (brandAuthBtn) {
    brandAuthBtn.addEventListener('click', () => openAuthModal('login', true));
    brandAuthBtn.addEventListener('keypress', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openAuthModal('login', true);
      }
    });
  }

  const authCloseBtn = document.getElementById('auth-close-btn');
  if (authCloseBtn) {
    authCloseBtn.addEventListener('click', closeAuthModal);
  }

  const authModal = document.getElementById('auth-modal');
  if (authModal) {
    authModal.addEventListener('click', (e) => {
      if (e.target === authModal) closeAuthModal();
    });
  }

  // Auth pane switching via "Don't have an account?" / "Sign in" links
  document.querySelectorAll('.auth-switch-link').forEach(link => {
    link.addEventListener('click', () => {
      const pane = link.getAttribute('data-pane');
      document.querySelectorAll('.auth-pane').forEach(p => p.classList.remove('active'));
      document.getElementById(`auth-pane-${pane}`).classList.add('active');
      if (pane === 'register') {
        syncRegisterRoleIdField();
      }
    });
  });

  const modalLoginBtn = document.getElementById('modal-login-btn');
  if (modalLoginBtn) {
    modalLoginBtn.addEventListener('click', loginFromModal);
  }

  const modalRegisterBtn = document.getElementById('modal-register-btn');
  if (modalRegisterBtn) {
    modalRegisterBtn.addEventListener('click', registerFromModal);
  }

  const modalRegisterRole = document.getElementById('modal-register-role');
  if (modalRegisterRole) {
    modalRegisterRole.addEventListener('change', syncRegisterRoleIdField);
  }

  const backLandingBtn = document.getElementById('back-landing-btn');
  if (backLandingBtn) {
    backLandingBtn.addEventListener('click', showLandingPage);
  }


  const modalPasswordInput = document.getElementById('modal-password');
  if (modalPasswordInput) {
    modalPasswordInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') loginFromModal();
    });
  }

  const modalRegisterPasswordInput = document.getElementById('modal-register-password');
  if (modalRegisterPasswordInput) {
    modalRegisterPasswordInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') registerFromModal();
    });
  }

  syncRegisterRoleIdField();
  
  document.getElementById('results-search').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleResultsSearch();
  });

  setAuthUiState(Boolean(localStorage.getItem('token')));

  const initialHash = window.location.hash.substring(1);
  const hasAppRoute = ['submit', 'results', 'dashboard'].includes(initialHash);
  const isLoggedIn = Boolean(localStorage.getItem('token'));
  const roleHomePath = getRoleHomePath();

  if (isLoggedIn && roleHomePath) {
    window.location.href = roleHomePath;
    return;
  }

  if (hasAppRoute && isLoggedIn) {
    showSystemApp();
  } else {
    showLandingPage();
  }

  if (!window.location.hash) {
    if (isLoggedIn) {
      window.location.hash = getDefaultViewForRole();
    } else {
      window.location.hash = '';
    }
  } else {
    handleRoute();
  }
}

function handleRoute() {
  const hash = window.location.hash.substring(1);
  const validViews = ['submit', 'results', 'dashboard'];
  
  if (validViews.includes(hash)) {
    if (!localStorage.getItem('token')) {
      window.location.hash = '';
      showLandingPage();
      openAuthModal('login', true);
      return;
    }
    if (!canAccessView(hash)) {
      showToast('This page is not available for your role.');
      window.location.hash = getDefaultViewForRole();
      return;
    }
    if (hash === 'results' && isProviderRole() && !state.selectedRxNumber) {
      showToast('Select a prescription from Overview first.');
      window.location.hash = 'dashboard';
      return;
    }
    showSystemApp();
    switchView(hash);
  }
}

function switchView(viewId) {
  if (!canAccessView(viewId)) {
    showToast('This page is not available for your role.');
    const fallback = getDefaultViewForRole();
    if (viewId !== fallback) {
      window.location.hash = fallback;
    }
    return;
  }

  if (viewId === 'results' && isProviderRole() && !state.selectedRxNumber) {
    showToast('Select a prescription from Overview first.');
    if (window.location.hash.substring(1) !== 'dashboard') {
      window.location.hash = 'dashboard';
    }
    return;
  }

  state.currentView = viewId;
  
  if (state.pollInterval) {
    clearInterval(state.pollInterval);
    state.pollInterval = null;
  }

  document.querySelectorAll('.nav-item').forEach(item => {
    item.classList.toggle('active', item.getAttribute('data-view') === viewId);
  });

  document.querySelectorAll('.view').forEach(view => {
    view.classList.toggle('active', view.id === `view-${viewId}`);
  });

  const appLayout = document.getElementById('app-layout');
  if (appLayout) {
    appLayout.classList.remove('is-submit-view', 'is-results-view', 'is-dashboard-view');
    appLayout.classList.add(`is-${viewId}-view`);
  }

  if (viewId === 'dashboard') {
    loadDashboard();
  }
  if (viewId === 'submit') {
    loadRecentRx();
  }
}

function initDiagnosisAutocomplete() {
  const input = document.getElementById('diagnosis');
  const list = document.getElementById('diagnosis-suggestions');
  if (!input || !list) return;

  let activeIndex = -1;
  let debounceTimer = null;

  function closeList() {
    list.classList.remove('open');
    list.innerHTML = '';
    activeIndex = -1;
  }

  function selectItem(code, description) {
    input.value = code + ' - ' + description;
    closeList();
  }

  input.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    const q = input.value.trim();
    if (q.length < 1) { closeList(); return; }
    debounceTimer = setTimeout(async () => {
      try {
        const res = await fetch('/api/diagnosis-search?q=' + encodeURIComponent(q));
        const items = await res.json();
        list.innerHTML = '';
        activeIndex = -1;
        if (items.length === 0) { closeList(); return; }
        const header = document.createElement('li');
        header.className = 'autocomplete-col-header';
        header.innerHTML = '<span>ICD-10 Code</span><span>Diagnosis Description</span>';
        list.appendChild(header);
        items.forEach((item, idx) => {
          const li = document.createElement('li');
          li.innerHTML = `<span class="diag-code">${item.code}</span><span class="diag-desc">${item.description}</span>`;
          li.addEventListener('mousedown', (e) => {
            e.preventDefault();
            selectItem(item.code, item.description);
          });
          list.appendChild(li);
        });
        list.classList.add('open');
      } catch (err) {
        closeList();
      }
    }, 200);
  });

  input.addEventListener('keydown', (e) => {
    const items = list.querySelectorAll('li:not(.autocomplete-col-header)');
    if (!list.classList.contains('open') || items.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIndex = (activeIndex + 1) % items.length;
      items.forEach((li, i) => li.classList.toggle('active', i === activeIndex));
      items[activeIndex].scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIndex = (activeIndex - 1 + items.length) % items.length;
      items.forEach((li, i) => li.classList.toggle('active', i === activeIndex));
      items[activeIndex].scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault();
      items[activeIndex].dispatchEvent(new MouseEvent('mousedown'));
    } else if (e.key === 'Escape') {
      closeList();
    }
  });

  document.addEventListener('click', (e) => {
    if (!input.contains(e.target) && !list.contains(e.target)) {
      closeList();
    }
  });
}

function initDrugAutocomplete() {
  const input = document.getElementById('prod_nm');
  const rxcuiInput = document.getElementById('prod_rxcui');
  const list = document.getElementById('drug-suggestions');
  if (!input || !rxcuiInput || !list) return;

  let activeIndex = -1;
  let debounceTimer = null;

  function closeList() {
    list.classList.remove('open');
    list.innerHTML = '';
    activeIndex = -1;
  }

  function selectItem(drugName, rxcui) {
    input.value = drugName;
    rxcuiInput.value = rxcui || '';
    closeList();
  }

  input.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    const q = input.value.trim();
    rxcuiInput.value = '';
    if (q.length < 1) { closeList(); return; }
    debounceTimer = setTimeout(async () => {
      try {
        const res = await fetch('/api/drug-search?q=' + encodeURIComponent(q));
        const items = await res.json();
        list.innerHTML = '';
        activeIndex = -1;
        if (items.length === 0) { closeList(); return; }
        const header = document.createElement('li');
        header.className = 'autocomplete-col-header';
        header.innerHTML = '<span>RxCUI</span><span>Drug Name</span>';
        list.appendChild(header);
        items.forEach((item) => {
          const li = document.createElement('li');
          li.innerHTML = `<span class="drug-rxcui">${item.rxcui}</span><span class="drug-name">${item.drug_name}</span>`;
          li.addEventListener('mousedown', (e) => {
            e.preventDefault();
            selectItem(item.drug_name, item.rxcui);
          });
          list.appendChild(li);
        });
        list.classList.add('open');
      } catch (err) {
        closeList();
      }
    }, 200);
  });

  input.addEventListener('keydown', (e) => {
    const items = list.querySelectorAll('li:not(.autocomplete-col-header)');
    if (!list.classList.contains('open') || items.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIndex = (activeIndex + 1) % items.length;
      items.forEach((li, i) => li.classList.toggle('active', i === activeIndex));
      items[activeIndex].scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIndex = (activeIndex - 1 + items.length) % items.length;
      items.forEach((li, i) => li.classList.toggle('active', i === activeIndex));
      items[activeIndex].scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault();
      items[activeIndex].dispatchEvent(new MouseEvent('mousedown'));
    } else if (e.key === 'Escape') {
      closeList();
    }
  });

  document.addEventListener('click', (e) => {
    if (!input.contains(e.target) && !list.contains(e.target)) {
      closeList();
    }
  });
}

// ── Submission progress modal ─────────────────────────────────────────────
// Two-stage animation matching the real orchestrator pipeline.
// Stage 1: Clinical agent sub-steps (sequential)
// Stage 2: Policy / Financial / Past agents sub-steps (parallel fan-out)

const SPM_STEPS = [
  // [id, pct at activation, delay ms from previous]
  ['spm-c1',  8,  200],
  ['spm-c2', 20,  700],
  ['spm-c3', 32,  800],
  // stage 2 kicks off after c3; all three agents start together
  ['spm-p1', 46,  600],  // policy
  ['spm-f1', 46,    0],  // financial  (same tick)
  ['spm-d1', 46,    0],  // past       (same tick)
  ['spm-p2', 58,  500],
  ['spm-f2', 58,    0],
  ['spm-d2', 58,    0],
  ['spm-d3', 70,  500],
  ['spm-d4', 80,  450],
];

function _spmSetStep(id, state) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = `spm-step spm-step--${state}`;
}

function _spmSetAgent(id, state) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = `spm-agent-header spm-agent-header--${state}`;
}

function _spmSetStage(badgeId, state) {
  const el = document.getElementById(badgeId);
  if (!el) return;
  el.className = `spm-stage-badge spm-stage-badge--${state}`;
}

function _spmSetFlowState(activeStep) {
  const stepIds = ['spm-flow-1', 'spm-flow-2', 'spm-flow-3', 'spm-flow-4', 'spm-flow-5'];
  const connectorIds = ['spm-flow-c1', 'spm-flow-c2', 'spm-flow-c3', 'spm-flow-c4'];

  stepIds.forEach((id, idx) => {
    const el = document.getElementById(id);
    if (!el) return;
    const stepNum = idx + 1;
    let state = 'pending';
    if (stepNum < activeStep) state = 'done';
    else if (stepNum === activeStep) state = 'current';
    el.className = `spm-flow-step spm-flow-step--${state}`;
  });

  connectorIds.forEach((id, idx) => {
    const el = document.getElementById(id);
    if (!el) return;
    const leftStepNum = idx + 1;
    const done = leftStepNum < activeStep;
    el.className = done ? 'spm-flow-connector spm-flow-connector--done' : 'spm-flow-connector';
  });
}

// Smooth progress animation state
let _spmProgressState = { current: 0, target: 0, animationId: null };

function _spmSetPercent(pct, label) {
  const fill  = document.getElementById('submission-progress-fill');
  const value = document.getElementById('submission-progress-value');
  const track = document.getElementById('submission-progress-track');
  const p = Math.max(0, Math.min(100, pct));
  
  _spmProgressState.target = p;
  
  // Cancel existing animation
  if (_spmProgressState.animationId) {
    cancelAnimationFrame(_spmProgressState.animationId);
  }
  
  // Update label immediately
  if (value) value.textContent = `${Math.round(p)}% — ${label}`;
  if (track) track.setAttribute('aria-valuenow', String(Math.round(p)));
  
  // Animate from current to target
  const animate = () => {
    const diff = _spmProgressState.target - _spmProgressState.current;
    if (Math.abs(diff) < 0.1) {
      _spmProgressState.current = _spmProgressState.target;
    } else {
      _spmProgressState.current += diff * 0.15; // Smooth easing factor
    }
    
    if (fill) {
      fill.style.width = `${_spmProgressState.current}%`;
    }
    
    if (Math.abs(_spmProgressState.current - _spmProgressState.target) > 0.1) {
      _spmProgressState.animationId = requestAnimationFrame(animate);
    }
  };
  
  _spmProgressState.animationId = requestAnimationFrame(animate);
}

function _spmSetStageCollapsed(stageId, collapsed) {
  const stage = document.getElementById(stageId);
  if (!stage) return;

  stage.classList.toggle('spm-stage--collapsed', Boolean(collapsed));

  const toggle = document.getElementById(`${stageId}-toggle`);
  if (toggle) {
    toggle.setAttribute('aria-expanded', String(!collapsed));
    toggle.textContent = collapsed ? 'Show' : 'Hide';
  }
}

function _spmInitStageToggle(stageId) {
  const toggle = document.getElementById(`${stageId}-toggle`);
  if (!toggle || toggle.dataset.bound === '1') return;

  toggle.addEventListener('click', () => {
    const stage = document.getElementById(stageId);
    if (!stage) return;
    const currentlyCollapsed = stage.classList.contains('spm-stage--collapsed');
    _spmSetStageCollapsed(stageId, !currentlyCollapsed);
  });

  toggle.dataset.bound = '1';
}

function openSubmissionProgressModal() {
  const modal = document.getElementById('submission-progress-modal');
  if (!modal) return;
  const title = document.getElementById('submission-progress-title');
  const successState = document.getElementById('spm-success-state');
  if (title) title.textContent = 'Submitting to NextGen PBM';
  if (successState) successState.hidden = true;
  // Reset progress animation state
  _spmProgressState = { current: 0, target: 0, animationId: null };
  if (_spmProgressState.animationId) {
    cancelAnimationFrame(_spmProgressState.animationId);
  }
  // Reset all steps to pending
  ['spm-c1','spm-c2','spm-c3',
   'spm-p1','spm-p2',
   'spm-f1','spm-f2',
   'spm-d1','spm-d2','spm-d3','spm-d4'].forEach(id => _spmSetStep(id, 'pending'));
  ['spm-policy-header','spm-financial-header','spm-past-header'].forEach(id => _spmSetAgent(id, 'pending'));
  _spmSetStage('spm-s1-badge', 'pending');
  _spmSetStage('spm-s2-badge', 'pending');
  // Keep timeline filled through AI Processing while orchestration runs.
  _spmSetFlowState(3);
  _spmSetPercent(0, 'Initialising…');
  const stage2 = document.getElementById('spm-stage2');
  if (stage2) stage2.classList.remove('spm-stage--active');
  _spmSetStageCollapsed('spm-stage1', false);
  _spmSetStageCollapsed('spm-stage2', false);
  modal.classList.add('show');
}

function closeSubmissionProgressModal() {
  const modal = document.getElementById('submission-progress-modal');
  if (!modal) return;
  modal.classList.remove('show');
}

function showSubmissionProgressSuccess(rxNumber) {
  const title = document.getElementById('submission-progress-title');
  const successState = document.getElementById('spm-success-state');
  const successRx = document.getElementById('submission-success-rx-number');
  if (title) title.textContent = 'Prescription Submitted';
  if (successState) successState.hidden = false;
  if (successRx) successRx.textContent = rxNumber || '';
  _spmSetStageCollapsed('spm-stage1', true);
  _spmSetStageCollapsed('spm-stage2', true);
}

function showSubmissionProgressDelayed(rxNumber) {
  const title = document.getElementById('submission-progress-title');
  const successState = document.getElementById('spm-success-state');
  const successRx = document.getElementById('submission-success-rx-number');
  if (title) title.textContent = 'PBM Processing In Progress';
  if (successState) successState.hidden = true;
  if (successRx) successRx.textContent = rxNumber || '';
  _spmSetPercent(96, 'Processing is taking longer than expected');
}

function initSubmissionProgressModalControls() {
  const closeBtn = document.getElementById('submission-progress-close');
  if (closeBtn) {
    closeBtn.addEventListener('click', closeSubmissionProgressModal);
  }

  _spmInitStageToggle('spm-stage1');
  _spmInitStageToggle('spm-stage2');
}

function createRealtimeProgressTracker() {
  // No timers — all updates come from backend SSE events
  _spmSetStage('spm-s1-badge', 'active');
  _spmSetPercent(2, 'AI Processing…');

  // step id -> percent when active
  const STEP_PCT = {
    'spm-c1': 10, 'spm-c2': 22, 'spm-c3': 35,
    'spm-p1': 46, 'spm-f1': 46, 'spm-d1': 46,
    'spm-p2': 60, 'spm-f2': 60, 'spm-d2': 60,
    'spm-d3': 75, 'spm-d4': 88,
  };

  return {
    onEvent(update) {
      const { stage, step, status } = update;
      const stepId = 'spm-' + step;

      // Stage transitions
      if (step === 'p1' && status === 'active') {
        _spmSetStage('spm-s1-badge', 'done');
        _spmSetStage('spm-s2-badge', 'active');
        _spmSetAgent('spm-policy-header',    'active');
        _spmSetAgent('spm-financial-header', 'active');
        _spmSetAgent('spm-past-header',      'active');
        const stage2 = document.getElementById('spm-stage2');
        if (stage2) stage2.classList.add('spm-stage--active');
      }

      // Agent header done
      if (step === 'p2' && status === 'done') _spmSetAgent('spm-policy-header', 'done');
      if (step === 'f2' && status === 'done') _spmSetAgent('spm-financial-header', 'done');
      if (step === 'd2' && status === 'done') _spmSetAgent('spm-past-header', 'done');

      _spmSetStep(stepId, status);

      const pct = STEP_PCT[stepId] || 0;
      const label = stage === 'Stage 1' ? 'Stage 1 — Clinical Agent' : 'Stage 2 — agents running';
      if (pct > 0) _spmSetPercent(pct, label);
    },
    complete() {
      const stepIds = ['spm-c1','spm-c2','spm-c3',
                       'spm-p1','spm-p2',
                       'spm-f1','spm-f2',
                       'spm-d1','spm-d2','spm-d3','spm-d4'];
      const agentIds = ['spm-policy-header','spm-financial-header','spm-past-header'];
      
      // Stagger step completions
      stepIds.forEach((id, idx) => {
        setTimeout(() => {
          _spmSetStep(id, 'done');
        }, idx * 120); // 120ms delay between each step
      });
      
      // Stagger agent header completions
      agentIds.forEach((id, idx) => {
        setTimeout(() => {
          _spmSetAgent(id, 'done');
        }, (stepIds.length + idx) * 120);
      });
      
      // Mark stages as done after all steps
      setTimeout(() => {
        _spmSetStage('spm-s1-badge', 'done');
        _spmSetStage('spm-s2-badge', 'done');
        _spmSetFlowState(4);
        _spmSetPercent(100, 'Analysis complete ✓');
      }, (stepIds.length + agentIds.length) * 120 + 200);
    },
    delayed() {
      _spmSetPercent(96, 'Processing is taking longer than expected');
      _spmSetFlowState(3);
    },
    disconnected() {
      _spmSetPercent(92, 'Live progress disconnected; using result polling');
    },
    stop() {}
  };
}

async function waitForPbmProcessingComplete(rxNumber, timeoutMs = 90000, intervalMs = 1500) {
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await autofetch(`/api/prescription/${encodeURIComponent(rxNumber)}/result`);
      if (response.ok) {
        const data = await response.json();
        if (data && data.pbm) {
          return true;
        }
      }
    } catch (error) {
      // Ignore transient polling errors and continue until timeout.
    }

    await new Promise(resolve => setTimeout(resolve, intervalMs));
  }

  return false;
}

async function handleFormSubmit(e) {
  e.preventDefault();
  const btn = document.getElementById('submit-btn');
  btn.disabled = true;
  btn.textContent = 'Submitting...';

  openSubmissionProgressModal();
  const progressTracker = createRealtimeProgressTracker();
  const traceId = 'trace-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);

  function getFieldValue(ids) {
    for (const id of ids) {
      const el = document.getElementById(id);
      if (el) return el.value;
    }
    return '';
  }

  const formData = {
    member_id: getFieldValue(['member_id', 'patient_id']),
    prescriber_npi: getFieldValue(['prescriber_npi', 'npi_number']),
    pharmacy_id: getFieldValue(['pharmacy_id', 'phr_id']),
    medication: getFieldValue(['medication', 'prod_nm']),
    strength: getFieldValue(['strength', 'dosage_size']),
    frequency: getFieldValue(['frequency']),
    days_supply: getFieldValue(['days_supply']),
    diagnosis_icd10: getFieldValue(['diagnosis_icd10', 'diagnosis']),
    trace_id: traceId
  };

  // Connect to real-time SSE progress stream from backend
  let eventSource = null;
  let sseDisconnected = false;
  eventSource = new EventSource(`/api/progress/${encodeURIComponent(traceId)}`);
  eventSource.onmessage = (event) => {
    try {
      progressTracker.onEvent(JSON.parse(event.data));
    } catch (e) {
      console.error('SSE parse error:', e);
    }
  };
  eventSource.onerror = () => {
    sseDisconnected = true;
    progressTracker.disconnected();
    showToast('Live progress disconnected. Continuing with background status checks.');
    if (eventSource) eventSource.close();
  };

  try {
    const response = await autofetch('/api/prescription', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(formData)
    });

    const data = await response.json();

    if (response.ok) {
      const rxNumber = data.rx_number || '';
      _spmSetPercent(95, 'Finalising AI processing…');

      const ready = rxNumber
        ? await waitForPbmProcessingComplete(rxNumber)
        : false;
      if (eventSource) eventSource.close();

      if (ready) {
        progressTracker.complete();
        await new Promise(resolve => setTimeout(resolve, 400));
        showSubmissionProgressSuccess(rxNumber);
        showToast(
          sseDisconnected
            ? 'Prescription submitted successfully. Live progress reconnected via polling.'
            : 'Prescription submitted successfully'
        );
      } else {
        progressTracker.delayed();
        showSubmissionProgressDelayed(rxNumber);
        showToast('Prescription submitted. Processing is taking longer than expected. Please refresh results shortly.');
      }

      document.getElementById('prescription-form').reset();
      loadRecentRx();
    } else {
      if (eventSource) eventSource.close();
      progressTracker.stop();
      showToast(data.error || 'Failed to submit prescription');
    }
  } catch (error) {
    if (eventSource) eventSource.close();
    progressTracker.stop();
    showToast('Network error while submitting');
    console.error(error);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Submit to NextGen PBM →';
  }
}

// ---- Recent Rx Sidebar Panel ----

let _recentRxAll = [];

function _recentRxSortValue(row) {
  const raw = row?.date_written || row?.created_at || row?.updated_at || '';
  const ts = Date.parse(String(raw));
  return Number.isNaN(ts) ? 0 : ts;
}

function goToOverviewFromSubmit() {
  window.location.hash = 'dashboard';
}

async function loadRecentRx() {
  const body = document.getElementById('submit-rx-rows');
  if (!body) return;

  body.innerHTML = '<div class="submit-rx-skeleton"><div class="submit-rx-sk-line" style="width:68%"></div><div class="submit-rx-sk-line" style="width:48%"></div></div>';

  try {
    const res = await autofetch('/api/prescriptions');
    if (!res.ok) throw new Error('Failed to load');
    const data = await res.json();
    _recentRxAll = [...(data || [])].sort((a, b) => _recentRxSortValue(b) - _recentRxSortValue(a));
    renderRecentRxRows(_recentRxAll, '');
  } catch {
    body.innerHTML = '<div class="submit-rx-empty">Could not load recent prescriptions.</div>';
  }
}

function renderRecentRxRows(rows, filter) {
  const body = document.getElementById('submit-rx-rows');
  const footer = document.getElementById('submit-rx-footer');
  if (!body) return;
  const q = (filter || '').toLowerCase().trim();

  const buildRecentRxSearchHaystack = (row) => {
    const rxNumber = String(row.rx_number || '');
    const medication = String(row.medication || row.prod_nm || '');
    const member = String(row.member_id || row.patient_account_id || '');
    const rawDate = String(row.date_written || row.created_at || row.updated_at || '').trim();

    const tokens = [rxNumber, medication, member];
    if (rawDate) {
      tokens.push(rawDate);
      tokens.push(rawDate.slice(0, 10));
      const parsedTs = Date.parse(rawDate);
      if (!Number.isNaN(parsedTs)) {
        const d = new Date(parsedTs);
        tokens.push(d.toISOString().slice(0, 10));
        tokens.push(d.toLocaleDateString('en-US')); // MM/DD/YYYY
        tokens.push(d.toLocaleDateString('en-GB')); // DD/MM/YYYY
      }
    }

    return tokens.join(' ').toLowerCase();
  };

  const filtered = q
    ? rows.filter(r => buildRecentRxSearchHaystack(r).includes(q))
    : rows;

  const visibleRows = filtered.slice(0, 6);
  if (footer) footer.hidden = filtered.length <= 6;
  if (!visibleRows.length) {
    body.innerHTML = '<div class="submit-rx-empty">No prescriptions found.</div>';
    if (footer) footer.hidden = true;
    return;
  }

  body.innerHTML = visibleRows.map(r => {
    const rxNum = String(r.rx_number || '');
    const med = String(r.medication || r.prod_nm || '—');
    const dateRaw = String(r.date_written || '');
    const date = dateRaw ? dateRaw.slice(0, 10) : '—';
    return `<div class="submit-rx-row" role="button" tabindex="0" aria-label="Open prescription ${escapeHtml(rxNum)} in review" onclick="goToResults('${escapeHtml(rxNum)}')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();goToResults('${escapeHtml(rxNum)}');}">
      <span class="rx-num" title="${rxNum}">${rxNum}</span>
      <span title="${med}">${med}</span>
      <span>${date}</span>
    </div>`;
  }).join('');
}

function initRecentRxSearch() {
  const input = document.getElementById('submit-quick-search');
  const moreBtn = document.getElementById('submit-rx-more-btn');
  if (!input) return;
  input.addEventListener('input', () => {
    renderRecentRxRows(_recentRxAll, input.value);
  });
  if (moreBtn) {
    moreBtn.addEventListener('click', goToOverviewFromSubmit);
  }
}









function copyRxNumber() {
  const rxNumber = (document.getElementById('submission-success-rx-number')?.textContent || '').trim();
  if (!rxNumber) return;
  navigator.clipboard.writeText(rxNumber).then(() => {
    showToast('RX Number copied to clipboard');
  });
}

function closeModal() {
  const progressModal = document.getElementById('submission-progress-modal');
  if (progressModal) progressModal.classList.remove('show');
}

function goToResultsFromModal() {
  const rxNumber = (document.getElementById('submission-success-rx-number')?.textContent || '').trim();
  if (!rxNumber) return;
  closeModal();
  setSelectedRxNumber(rxNumber);
  document.getElementById('results-search').value = rxNumber;
  window.location.hash = 'results';
  setTimeout(() => handleResultsSearch(), 100);
}

function goToResults(rxNumber) {
  setSelectedRxNumber(rxNumber);
  document.getElementById('results-search').value = rxNumber;
  window.location.hash = 'results';
  setTimeout(() => handleResultsSearch(), 100);
}

async function handleResultsSearch() {
  const rxNumber = document.getElementById('results-search').value.trim();
  if (!rxNumber) {
    showToast('Please enter an RX Number');
    return;
  }

  const contentArea = document.getElementById('results-content');
  contentArea.innerHTML = '<div class="loading-state">Loading PBM results...</div>';
  const dlBtn = document.getElementById('results-download-btn');
  if (dlBtn) dlBtn.style.display = 'none';

  try {
    const response = await autofetch(`/api/prescription/${rxNumber}/result`);
    const data = await response.json();

    if (response.ok) {
      if (!data.pbm) {
         contentArea.innerHTML = `
          <div class="empty-state">
            <p>PBM results not available yet. The prescription may still be processing.</p>
            <button class="btn" style="margin-top: 10px" onclick="setTimeout(handleResultsSearch, 3000);">Refresh Results</button>
          </div>`;
         return;
      }
      setSelectedRxNumber(rxNumber);
      renderPbmResults(rxNumber, data);
    } else {
      contentArea.innerHTML = `<div class="empty-state"><p>${data.error || 'Failed to load results'}</p></div>`;
    }
  } catch (error) {
    showToast('Network error while autofetching results');
    contentArea.innerHTML = `<div class="empty-state"><p>Failed to load results. Please try again.</p></div>`;
  }
}

function formatMoneyDisplay(value) {
  return value === null || value === undefined || value === '' ? '—' : `$${Number(value).toFixed(2)}`;
}

function formatPercentDisplay(value) {
  return value === null || value === undefined || value === '' ? '—' : `${Number(value).toFixed(2)}%`;
}

function formatSavingsPercentDisplay(value) {
  if (value === null || value === undefined || value === '') return '—';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '—';
  const percent = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
  return `${percent.toFixed(2)}%`;
}

function formatPhaseDisplay(phase) {
  if (!phase) return '—';
  const mapped = {
    DEDUCTIBLE: 'Deductible Stage',
    INITIAL_COVERAGE: 'Standard Coverage',
    CATASTROPHIC: 'OOP Max Reached'
  };
  return mapped[phase] || phase;
}

function formatReviewStatus(status) {
  const map = {
    'APPROVED':    'Auto Approved',
    'ACCEPTED':    'Accepted by Provider',
    'ESCALATED':   'Pending Review',
    'REJECTED':    'Not Recommended',
    'KEEP_ORIGINAL': 'Original Drug Recommended',
    'PENDING_REVIEW': 'Pending Review',
    'NOT_SELECTED': 'Not Selected',
  };
  return map[status] || status || 'Pending Review';
}

function getReviewSummaryStatus(status, decisionStatus) {
  const normalizedStatus = String(status || '').toUpperCase();
  const normalizedDecision = String(decisionStatus || '').toUpperCase();

  if (normalizedDecision === 'REJECTED') {
    return { label: 'Original Medication Retained', color: '#C06A1A', textColor: '#C06A1A', background: '#FCEBD8', border: '#C06A1A' };
  }
  if (normalizedDecision === 'ACCEPTED' && normalizedStatus !== 'APPROVED') {
    return { label: 'Alternative Approved by Clinician', color: '#0F8A80', textColor: '#0F8A80', background: '#DDF7F4', border: '#0F8A80' };
  }
  if (normalizedStatus === 'APPROVED') {
    return { label: 'Auto Approve', color: '#16A34A', textColor: '#374151', background: '#DCF3E3', border: '#0B7A33' };
  }
  if (normalizedStatus === 'KEEP_ORIGINAL') {
    return { label: 'Original Medication Retained', color: '#C06A1A', textColor: '#C06A1A', background: '#FCEBD8', border: '#C06A1A' };
  }
  if (normalizedStatus === 'ESCALATED' || normalizedStatus === 'PENDING_REVIEW') {
    return { label: 'Under Review', color: '#7C3AED', textColor: '#374151', background: '#F0E8FF', border: '#7C3AED' };
  }
  if (!normalizedStatus) {
    return { label: 'Awaiting AI Evaluation', color: '#7B8794', textColor: '#374151', background: '#ECEFF3', border: '#7B8794' };
  }
  return { label: 'Submitted for AI Analysis', color: '#2563EB', textColor: '#374151', background: '#E7F0FF', border: '#2563EB' };
}

function buildAlternativePanelHtml(pbm, alternative, currentRole = '') {
  const cost = alternative.cost || {};
  const safety = alternative.safety || {};
  const policy = alternative.policy || {};
  const orchestratorCards = alternative.orchestrator_summary_cards || {};
  const clinicalCard = orchestratorCards.clinical_agent || {};
  const policyCard = orchestratorCards.policy_agent || {};
  const financialCard = orchestratorCards.financial_agent || {};
  const insuranceCard = orchestratorCards.insurance_context || {};
  const confPercent = Math.round(Number(alternative.combined_score || 0) * 100);
  const pbmStatus = String(pbm.status || '').toUpperCase();
  const reviewStatus = String(alternative.review_status || pbm.status || '').toUpperCase();
  const isPharmacistRole = (currentRole || '').toLowerCase() === 'pharmacist';
  const showAiConfidenceLabel = !isPharmacistRole;

  const normalizePercent = (value, fallback = 0) => {
    const numeric = Number(value);
    const base = Number.isFinite(numeric) ? numeric : Number(fallback);
    const scaled = base <= 1 ? base * 100 : base;
    return Math.max(0, Math.min(100, Math.round(scaled)));
  };

  const resolveAgentPercent = (key, fallback) => {
    const direct = (alternative.agent_confidence || {})[key];
    if (direct !== undefined && direct !== null && direct !== '') {
      return normalizePercent(direct, fallback);
    }
    const breakdown = (alternative.agent_breakdown || {})[key];
    if (breakdown !== undefined && breakdown !== null && breakdown !== '') {
      return normalizePercent(breakdown, fallback);
    }
    const summaryScoreByKey = {
      clinical: clinicalCard.score,
      financial: financialCard.score,
      policy: policyCard.score,
      coverage: insuranceCard.score,
    };
    const summaryScore = summaryScoreByKey[key];
    if (summaryScore !== undefined && summaryScore !== null && summaryScore !== '') {
      return normalizePercent(summaryScore, fallback);
    }
    return normalizePercent(fallback, fallback);
  };

  const normalizeTier = (value) => {
    const raw = String(value || '').trim();
    if (!raw) return '';
    const lower = raw.toLowerCase();
    if (['unknown', 'none', 'null', 'na', 'n/a', '-'].includes(lower)) return '';
    if (lower.startsWith('tier')) return raw;
    const numeric = Number(raw);
    if (!Number.isNaN(numeric)) return `Tier ${Math.trunc(numeric)}`;
    return raw;
  };

  const originalTierDisplay = normalizeTier(cost.original_tier) || normalizeTier(cost.alternative_tier) || '—';
  const alternativeTierDisplay = normalizeTier(cost.alternative_tier) || normalizeTier(cost.original_tier) || '—';
  const showEscalatedChip =
    (reviewStatus === 'ESCALATED' || reviewStatus === 'PENDING_REVIEW') &&
    (pbmStatus === 'ESCALATED' || pbmStatus === 'PENDING_REVIEW');

  // SVG confidence ring
  const ringR = 28;
  const ringC = 2 * Math.PI * ringR;
  const ringOffset = ringC - (confPercent / 100) * ringC;
  const ringColor = confPercent >= 80 ? '#1E8449' : confPercent >= 60 ? '#C9880A' : '#CC3300';

  // Progress bar helper (handles "$X.XX" strings or raw numbers)
  const parseMoney = v => parseFloat(String(v || '0').replace(/[$,]/g, '')) || 0;
  const dedMet = parseMoney(cost.deductible_met);
  const dedCap = parseMoney(cost.deductible_cap);
  const dedPct = dedCap > 0 ? Math.min(100, (dedMet / dedCap) * 100).toFixed(1) : 0;
  const oopMet = parseMoney(cost.oop_met);
  const oopMax = parseMoney(cost.oop_max_cap);
  const oopPct = oopMax > 0 ? Math.min(100, (oopMet / oopMax) * 100).toFixed(1) : 0;

  const monthlySavingsRaw =
    financialCard.monthly_savings
    || cost.estimated_monthly_savings
    || cost.monthly_savings
    || cost.savings
    || financialCard.savings;
  const annualSavingsRaw =
    financialCard.annual_savings
    || cost.estimated_annual_savings;
  const monthlySavingsValue =
    parseMoney(monthlySavingsRaw) > 0
      ? parseMoney(monthlySavingsRaw)
      : (parseMoney(annualSavingsRaw) > 0 ? (parseMoney(annualSavingsRaw) / 12) : 0);
  const hasSavings = monthlySavingsValue > 0;
  const monthlySavings = hasSavings ? Math.max(1, Math.round(monthlySavingsValue)) : 0;

  const altStatusText = String(policyCard.alternative_status || policy.alternative_status || '').trim();
  const origStatusText = String(policyCard.original_status || policy.original_status || '').trim();
  const isPreferred = altStatusText.toLowerCase().includes('preferred');
  const isCovered = altStatusText.length > 0 && !altStatusText.toLowerCase().includes('not covered');
  // Hardcoded from backend/app/config/scoring_config.json for deterministic box colors.
  const clinicalThresholdPct = 60;
  const financialThresholdPct = 60;
  const policyThresholdPct = 70;
  const coverageThresholdPct = 80;
  const clinicalPct = resolveAgentPercent('clinical', confPercent);
  const financialPct = resolveAgentPercent('financial', hasSavings ? 82 : 45);
  const coveragePct = resolveAgentPercent('coverage', isCovered ? 80 : 45);
  const policyPct = resolveAgentPercent('policy', (isCovered && isPreferred) ? 88 : 46);
  const rawClinicalStatusNote = String(clinicalCard.status || safety.summary || '').trim();
  const clinicalStatusNote = ['clinically_acceptable', 'clinically acceptable'].includes(rawClinicalStatusNote.toLowerCase())
    ? ''
    : rawClinicalStatusNote;
  const cardStatus = {
    clinical: { percent: clinicalPct, cls: clinicalPct >= clinicalThresholdPct ? 'pbm-card-status--success' : 'pbm-card-status--attention', label: `Clinical confidence ${clinicalPct}%` },
    cost: { percent: financialPct, cls: financialPct >= financialThresholdPct ? 'pbm-card-status--success' : 'pbm-card-status--attention', label: `Financial confidence ${financialPct}%` },
    coverage: { percent: coveragePct, cls: coveragePct >= coverageThresholdPct ? 'pbm-card-status--success' : 'pbm-card-status--attention', label: `Coverage confidence ${coveragePct}%` },
    policy: { percent: policyPct, cls: policyPct >= policyThresholdPct ? 'pbm-card-status--success' : 'pbm-card-status--attention', label: `Policy confidence ${policyPct}%` },
  };

  const statusBadge = (status) => `
    <span class="pbm-status-badge ${status.cls}" aria-label="${status.label}">
      <span class="pbm-status-badge__icon" aria-hidden="true">${status.percent}%</span>
    </span>
  `;

  const clinicalChecks = Array.isArray(clinicalCard.clinical_summary) && clinicalCard.clinical_summary.length
    ? clinicalCard.clinical_summary
    : [
      'Same dosage form',
      'Mechanism-of-action similarity',
      'Strength alignment',
      'Combination-therapy similarity',
    ];
  const safetyChecks = Array.isArray(clinicalCard.safety_summary) && clinicalCard.safety_summary.length
    ? clinicalCard.safety_summary
    : [
      (safety.contraindications === 'None' || !safety.contraindications) ? 'No allergy conflicts identified' : null,
      (safety.interactions === 'None' || !safety.interactions) ? 'No drug interactions identified' : null,
      'No contraindications identified',
      'No duplicate therapy signal identified',
    ].filter(Boolean);

  const costRows = [
    { label: 'Drug',             orig: escapeHtml(pbm.prescribed_drug || '—'),      alt: escapeHtml(alternative.label || '—') },
    { label: 'Tier',             orig: escapeHtml(originalTierDisplay),               alt: escapeHtml(alternativeTierDisplay) },
    { label: 'Total Price',      orig: formatMoneyDisplay(cost.original_price),      alt: formatMoneyDisplay(cost.alternative_price) },
    { label: 'Patient Copay',    orig: formatMoneyDisplay(cost.original_copay),      alt: formatMoneyDisplay(cost.alternative_copay) },
    { label: 'Plan Paid Amount', orig: formatMoneyDisplay(cost.original_plan_paid),  alt: formatMoneyDisplay(cost.alternative_plan_paid) },
    { label: 'Total Cost',       orig: formatMoneyDisplay(cost.original_total_cost), alt: formatMoneyDisplay(cost.alternative_total_cost) },
  ];

  return `
    <div class="pbm-dashboard">

      <!-- Analysis Summary Card -->
      <div class="pbm-card pbm-card-full">
        <div class="pbm-analysis-summary">
          <div class="pbm-analysis-left">
            <div class="pbm-analysis-title">NextGen PBM Analysis Report</div>
            <div class="pbm-analysis-metrics">
              <div class="pbm-metric-item">
                <div class="pbm-analysis-bar"></div>
                <span class="pbm-metric-label">Tier</span>
                  <span class="pbm-metric-value">${escapeHtml(alternativeTierDisplay || originalTierDisplay || '—')}</span>
              </div>
              <div class="pbm-metric-item">
                <div class="pbm-analysis-bar"></div>
                <span class="pbm-metric-label">Selected Alternative</span>
                <span class="pbm-metric-value">${escapeHtml(alternative.label || '—')}</span>
              </div>
              <div class="pbm-metric-item">
                <div class="pbm-analysis-bar"></div>
                <span class="pbm-metric-label">Patient / Member ID</span>
                <span class="pbm-metric-value">${escapeHtml(pbm.member_id || '—')}</span>
              </div>
            </div>
          </div>
          <div class="pbm-analysis-right">
            <svg class="pbm-conf-ring" viewBox="0 0 70 70" width="78" height="78" aria-label="${confPercent}% AI confidence">
              <circle cx="35" cy="35" r="${ringR}" fill="none" stroke="#E3EEE7" stroke-width="8"/>
              <circle cx="35" cy="35" r="${ringR}" fill="none" stroke="${ringColor}" stroke-width="8"
                stroke-dasharray="${ringC.toFixed(2)}" stroke-dashoffset="${ringOffset.toFixed(2)}"
                stroke-linecap="round" transform="rotate(-90 35 35)"/>
              <text x="35" y="40" text-anchor="middle" fill="${ringColor}" font-size="13" font-weight="700" font-family="Helvetica">${confPercent}%</text>
            </svg>
            ${showAiConfidenceLabel ? '<div class="pbm-conf-label">AI Confidence</div>' : ''}
          </div>
        </div>
      </div>

      <!-- 2×2 Dashboard Grid -->
      <div class="pbm-grid-2">

        <!-- Card 1: Clinical Review -->
        <div class="pbm-card ${cardStatus.clinical.cls}">
          <div class="pbm-card-header">
            <span class="pbm-card-title pbm-card-title--blue">Clinical Review</span>
            ${statusBadge(cardStatus.clinical)}
          </div>
          <div class="pbm-two-col">
            <div>
              <div class="pbm-subsection-label">Clinical Summary</div>
              ${clinicalChecks.map(c => `<div class="pbm-check-item">${c}</div>`).join('')}
            </div>
            <div>
              <div class="pbm-subsection-label">Safety Summary</div>
              ${safetyChecks.map(c => `<div class="pbm-check-item">${c}</div>`).join('')}
              ${clinicalStatusNote ? `<div class="pbm-safety-note">${escapeHtml(clinicalStatusNote)}</div>` : ''}
            </div>
          </div>
        </div>

        <!-- Card 2: Cost Analysis -->
        <div class="pbm-card ${cardStatus.cost.cls}">
          <div class="pbm-card-header">
            <span class="pbm-card-title">Cost Analysis</span>
            ${statusBadge(cardStatus.cost)}
          </div>
          <table class="pbm-compare-table">
            <thead>
              <tr>
                <th>Field</th>
                <th>Original</th>
                <th>Alternative</th>
              </tr>
            </thead>
            <tbody>
              ${costRows.map((r, i) => `
                <tr class="${i % 2 === 0 ? 'pbm-row-even' : 'pbm-row-odd'}">
                  <td class="pbm-col-label">${r.label}</td>
                  <td class="pbm-col-orig">${r.orig}</td>
                  <td class="pbm-col-alt">${r.alt}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
          ${hasSavings ? `
            <div class="pbm-savings-banner">
              <div class="pbm-savings-main">You save ${formatMoneyDisplay(monthlySavings)} per month</div>
              ${cost.member_savings_percentage ? `<div class="pbm-savings-sub">${formatSavingsPercentDisplay(cost.member_savings_percentage)} lower than original drug</div>` : ''}
            </div>
          ` : ''}
        </div>

        <!-- Card 3: Coverage Details -->
        <div class="pbm-card ${cardStatus.coverage.cls}">
          <div class="pbm-card-header">
            <span class="pbm-card-title">Coverage Details</span>
            ${statusBadge(cardStatus.coverage)}
          </div>
          <div class="pbm-kpi-row">
            <div class="pbm-kpi">
              <div class="pbm-kpi-label">Insurance Phase</div>
              <div class="pbm-kpi-value">${formatPhaseDisplay(insuranceCard.insurance_phase || cost.insurance_phase)}</div>
            </div>
            <div class="pbm-kpi">
              <div class="pbm-kpi-label">YTD OOP</div>
              <div class="pbm-kpi-value">${formatMoneyDisplay(insuranceCard.ytd_oop || cost.ytd_oop)}</div>
            </div>
            <div class="pbm-kpi">
              <div class="pbm-kpi-label">Coinsurance</div>
              <div class="pbm-kpi-value">${formatPercentDisplay(insuranceCard.coinsurance || cost.coinsurance_percentage)}</div>
            </div>
          </div>
          <div class="pbm-progress-block">
            <div class="pbm-progress-row">
              <span class="pbm-progress-label">Deductible</span>
              <span class="pbm-progress-meta">${formatMoneyDisplay(cost.deductible_met)} met of ${formatMoneyDisplay(cost.deductible_cap)}</span>
            </div>
            <div class="pbm-progress-track">
              <div class="pbm-progress-fill" style="width:${dedPct}%"></div>
            </div>
            <div class="pbm-progress-remaining">${formatMoneyDisplay(cost.deductible_remaining)} remaining</div>
          </div>
          <div class="pbm-progress-block">
            <div class="pbm-progress-row">
              <span class="pbm-progress-label">Out-of-Pocket Max</span>
              <span class="pbm-progress-meta">${formatMoneyDisplay(cost.oop_met)} met of ${formatMoneyDisplay(cost.oop_max_cap)}</span>
            </div>
            <div class="pbm-progress-track">
              <div class="pbm-progress-fill" style="width:${oopPct}%"></div>
            </div>
            <div class="pbm-progress-remaining">${formatMoneyDisplay(cost.oop_remaining)} remaining</div>
          </div>
          <div class="pbm-kpi-row pbm-kpi-row--bottom">
            <div class="pbm-kpi">
              <div class="pbm-kpi-label">Deductible Cap</div>
              <div class="pbm-kpi-value">${formatMoneyDisplay(cost.deductible_cap)}</div>
            </div>
            <div class="pbm-kpi">
              <div class="pbm-kpi-label">OOP Max Cap</div>
              <div class="pbm-kpi-value">${formatMoneyDisplay(cost.oop_max_cap)}</div>
            </div>
          </div>
        </div>

        <!-- Card 4: Policy Review -->
        <div class="pbm-card ${cardStatus.policy.cls}">
          <div class="pbm-card-header">
            <span class="pbm-card-title">Policy Review</span>
            ${statusBadge(cardStatus.policy)}
          </div>
          <div class="pbm-policy-section">
            <div class="pbm-kpi-label">Original Status</div>
            <div class="pbm-policy-chip">${escapeHtml(origStatusText || '—')}</div>
          </div>
          <div class="pbm-policy-section">
            <div class="pbm-kpi-label">Alternative Status</div>
            <div class="pbm-policy-text">${escapeHtml(altStatusText || '—')}</div>
          </div>
          <div class="pbm-policy-section">
            <div class="pbm-kpi-label">Formulary Preference</div>
            <div class="pbm-chip-row">
              ${(String(policyCard.formulary_preference || '').toLowerCase().includes('covered') || isPreferred) ? '<span class="pbm-chip pbm-chip--green">Preferred</span>' : ''}
              ${(String(policyCard.coverage_status || '').toLowerCase() === 'covered' || isCovered) ? '<span class="pbm-chip pbm-chip--green">Covered</span>' : '<span class="pbm-chip pbm-chip--red">Not Covered</span>'}
              ${showEscalatedChip ? '<span class="pbm-chip pbm-chip--amber">Escalated</span>' : ''}
            </div>
          </div>
          <div class="pbm-policy-section">
            <div class="pbm-kpi-label">Policy Notes</div>
            <div class="pbm-policy-notes">${escapeHtml(policyCard.policy_notes || altStatusText || policy.original_status || pbm.policy_compliance || 'All policy checks completed.')}</div>
          </div>
        </div>

      </div><!-- end pbm-grid-2 -->
    </div><!-- end pbm-dashboard -->
  `;
}

function buildFinalDecisionSection(rxNumber, pbm, policy, existingDecision, currentRole, maySubmitDecision, rejectedAlternatives, initialConfPercent, overallThreshold = 0.80) {
  if ((String(currentRole || '').toLowerCase()) === 'pharmacist') {
    return '';
  }

  const confPercent = initialConfPercent !== undefined ? initialConfPercent : Math.round(Number(pbm.ai_confidence || 0) * 100);
  const thresholdPercent = Math.round(Number(overallThreshold || 0.80) * 100);
  const pbmStatus = String(pbm.status || '').toUpperCase();
  const rejectedList = Array.isArray(rejectedAlternatives) ? rejectedAlternatives : [];
  const decisionStatus = String((existingDecision || {}).status || '').toUpperCase();
  const decisionIsAccepted = decisionStatus === 'ACCEPTED';
  const decisionIsRejected = decisionStatus === 'REJECTED';
  const isDispenseAsWritten = pbmStatus === 'KEEP_ORIGINAL' || decisionIsRejected;
  const escalatedButAboveThreshold = pbmStatus === 'ESCALATED' && confPercent >= thresholdPercent;
  const showProviderOnlyDecisionDetails = isProviderRole(currentRole);

  const rejectedDrugsHtml = (rejectedList.length && !decisionIsAccepted) ? `
    <div style="margin-top: 12px;">
      <strong>Drugs:</strong>
      <div style="margin-top: 8px; display: flex; flex-direction: column; gap: 6px;">
        ${rejectedList.map((drug, idx) => {
          const safeId = `rej-drug-${idx}-${String(rxNumber).replace(/[^a-z0-9]/gi, '')}`;
          const reason = drug.rejection_reason || drug.rejection_comment || 'No reason recorded';
          return `
            <div style="border: 1px solid #e8b1b1; border-radius: 8px; overflow: hidden; background: #fff8f8;">
              <button
                type="button"
                onclick="(function(el){ var panel = el.nextElementSibling; var arrow = el.querySelector('.rej-arrow'); var open = panel.style.display !== 'none'; panel.style.display = open ? 'none' : 'block'; arrow.style.transform = open ? 'rotate(0deg)' : 'rotate(90deg)'; })(this)"
                style="width: 100%; display: flex; align-items: center; gap: 8px; padding: 9px 14px; background: none; border: none; cursor: pointer; text-align: left; font-size: 0.88rem; color: #7a1a1a; font-weight: 600;"
              >
                <span class="rej-arrow" style="display: inline-block; transition: transform 0.2s; font-size: 0.75rem;">&#9654;</span>
                ${escapeHtml(drug.label || `Drug ${idx + 1}`)}
                <span style="margin-left: auto; font-size: 0.78rem; font-weight: 400; color: #a33;">Rejected</span>
              </button>
              <div style="display: none; padding: 10px 14px 12px 32px; font-size: 0.86rem; color: #555; border-top: 1px solid #f0c8c8;">
                ${escapeHtml(reason)}
              </div>
            </div>
          `;
        }).join('')}
      </div>
    </div>
  ` : '';

  const existingDecisionHtml = (existingDecision && showProviderOnlyDecisionDetails) ? `
    <div style="margin-top: 10px; padding: 15px; background: #f8f9fa; border: 1px solid var(--border-color); border-radius: 8px;">
      <div style="display: flex; justify-content: space-between; margin-bottom: 10px;">
        <span class="badge badge-${String(existingDecision.status || '').toLowerCase()}">${escapeHtml(existingDecision.status || '—')}</span>
        <span style="color: var(--text-muted); font-size: 0.9rem;">Recorded on ${new Date(existingDecision.created_at).toLocaleString()}</span>
      </div>
      ${rejectedDrugsHtml}
      ${!rejectedList.length ? (
        existingDecision.reasons && existingDecision.reasons.length ? `
          <div>
            <strong>Reason${existingDecision.reasons.length > 1 ? 's' : ''}:</strong>
            <div class="decision-static-chip-list">
              ${existingDecision.reasons.map((item) => `<span class="decision-static-chip">${escapeHtml(item.reason_text)}</span>`).join('')}
            </div>
          </div>
        ` : existingDecision.reason ? `<div><strong>Reason:</strong> ${escapeHtml(existingDecision.reason)}</div>` : ''
      ) : ''}
      ${existingDecision.comment ? `<div style="margin-top: 10px;"><strong>Description / Clinical Notes:</strong><div style="margin-top: 6px; white-space: pre-wrap;">${escapeHtml(existingDecision.comment)}</div></div>` : ''}
    </div>
  ` : '';

  return `
    <div style="margin-top: 30px; border-top: 1px solid var(--border-color); padding-top: 20px;">
      <div class="section-header">
        <div class="header-with-tooltip">
          <h4 class="section-header-title">Final Portal Decision</h4>
          <span class="header-help" tabindex="0" aria-label="Clinical decision help">i</span>
          <div class="header-tooltip" role="tooltip">
            <div class="tooltip-line">Final decision recorded in this portal after PBM analysis.</div>
          </div>
        </div>
      </div>

      ${(pbm.status === 'ESCALATED' && !isDispenseAsWritten && showProviderOnlyDecisionDetails) ? `
        <div style="margin-top: 10px; padding: 12px 16px; background: #fff8ec; border: 1px solid #efc58e; border-radius: 10px; margin-bottom: 14px; font-size: 0.88rem; color: #7a4a00;">
          <strong>Escalation Summary:</strong> ${escapeHtml(pbm.orchestrator_summary || policy.original_status || pbm.policy_compliance || 'Case escalated for clinical decision due to unresolved policy/financial checks.')}
        </div>
      ` : ''}

      ${isDispenseAsWritten ? `
        <div style="margin-top: 10px; padding: 16px; background: linear-gradient(135deg, #fbe8e8 0%, #fff4f4 100%); border: 1.5px solid #e8b1b1; border-radius: 10px; display: flex; align-items: flex-start; gap: 14px;">
          <div>
            <div style="font-weight: 700; color: #8b1f1f; font-size: 1rem; margin-bottom: 4px;">Dispense as Written (DAW)</div>
            <div style="font-size: 0.85rem; color: #8b1f1f;">
              ${decisionIsRejected
                ? `The provider reviewed and rejected the proposed alternative${rejectedList.length > 1 ? 's' : ''}. The original prescription is retained as written.`
                : `The AI system rejected the proposed alternative${rejectedList.length > 1 ? 's' : ''} because no candidate cleared all gate checks. The original prescription is retained as written.`
              }
            </div>
            ${rejectedDrugsHtml}
          </div>
        </div>
      ` : pbmStatus === 'APPROVED' ? `
        <div style="margin-top: 10px; padding: 16px; background: linear-gradient(135deg, #dcf4e7 0%, #edfbf3 100%); border: 1.5px solid #a8e4c4; border-radius: 10px; display: flex; align-items: flex-start; gap: 14px;">
          <div>
            <div style="font-weight: 700; color: #165b38; font-size: 1rem; margin-bottom: 4px;">Auto Approved by AI System</div>
            <div style="font-size: 0.85rem; color: #1a7a4a;">
              AI confidence score of <strong class="final-decision-conf-pct">${confPercent}%</strong> exceeded the auto-approval threshold.
              This prescription was automatically accepted — no manual provider review required.
            </div>
          </div>
        </div>
      ` : existingDecisionHtml || (maySubmitDecision ? `
        <div style="margin-top: 10px; padding: 12px 16px; background: #fff8ec; border: 1.5px solid var(--sunset-orange); border-radius: 10px; margin-bottom: 14px; font-size: 0.88rem; color: #7a4a00;">
          ${escalatedButAboveThreshold
            ? `AI confidence (<strong class="final-decision-conf-pct">${confPercent}%</strong>) meets/exceeds the configured threshold (${thresholdPercent}%), but this case is still escalated because one or more gate checks failed or mandatory clinical review is required.`
            : `AI confidence (<strong class="final-decision-conf-pct">${confPercent}%</strong>) is below the configured threshold (${thresholdPercent}%). This prescription requires your review.`}
        </div>
        <div style="margin-top: 10px;">
          <div style="display: flex; gap: 10px; margin-bottom: 10px;">
            <button class="btn btn-success" onclick="showDecisionReason('ACCEPTED', '${rxNumber}')">Accept</button>
            <button class="btn btn-danger" onclick="showDecisionReason('REJECTED', '${rxNumber}')">Reject</button>
          </div>
          <div class="decision-reason" id="decision-reason-container">
            <div id="decision-reject-fields" class="decision-conditional-block">
              <div class="form-group" style="position:relative;">
                <label for="decision-reason-search">Reason (Required)</label>
                <div id="decision-selected-reasons" class="decision-chip-list"></div>
                <input type="text" id="decision-reason-search" placeholder="Search and add one or more reasons..." autocomplete="off">
                <ul id="decision-reason-suggestions" class="decision-autocomplete-list"></ul>
              </div>
            </div>
            <div class="form-group">
              <label id="decision-comment-label" for="decision-comment-input">Description / Clinical Notes</label>
              <textarea id="decision-comment-input" placeholder="Enter clinical notes or additional comments (optional)..." rows="4"></textarea>
            </div>
            <div style="display: flex; gap: 10px;">
              <button class="btn btn-primary" id="submit-decision-btn">Submit Decision</button>
              <button class="btn" onclick="cancelDecision()">Cancel</button>
            </div>
          </div>
        </div>
      ` : ``)}
    </div>
  `;
}

function initAlternativeTabs(root) {
  const buttons = Array.from(root.querySelectorAll('.alternative-tab-btn'));
  const panels = Array.from(root.querySelectorAll('.alternative-tab-panel'));
  if (!buttons.length || !panels.length) return;

  function updateConfScore(button) {
    const confScore = button.getAttribute('data-conf-score');
    if (confScore === null) return;
    root.querySelectorAll('.final-decision-conf-pct').forEach((el) => {
      el.textContent = confScore + '%';
    });
  }

  buttons.forEach((button) => {
    button.addEventListener('click', () => {
      const target = button.getAttribute('data-target');
      buttons.forEach((item) => item.classList.toggle('active', item === button));
      panels.forEach((panel) => panel.classList.toggle('active', panel.id === target));
      updateConfScore(button);
    });
  });
}

function buildClientFallbackAlternative(pbm, cost, safety, policy) {
  const label = (pbm.recommended_alt || '').trim() || 'Alternative 1';
  return {
    index: 0,
    label,
    is_selected: true,
    review_status: pbm.status || 'ESCALATED',
    combined_score: Number(pbm.ai_confidence || 0),
    score_basis: 'client_fallback_single',
    outcome: 'selected',
    reason: pbm.orchestrator_summary || policy.original_status || pbm.policy_compliance || 'Review required',
    prescribed_drug: pbm.prescribed_drug,
    diagnosis: pbm.diagnosis,
    agent_breakdown: {},
    cost: {
      original_tier: cost.original_tier,
      original_price: cost.original_price,
      original_copay: cost.original_copay,
      alternative_tier: cost.alternative_tier,
      alternative_price: cost.alternative_price,
      alternative_copay: cost.alternative_copay,
      savings: cost.savings,
      insurance_phase: cost.insurance_phase,
      ytd_oop: cost.ytd_oop,
      deductible_cap: cost.deductible_cap,
      oop_max_cap: cost.oop_max_cap,
      deductible_remaining: cost.deductible_remaining,
      oop_remaining: cost.oop_remaining,
      original_total_cost: cost.original_total_cost,
      alternative_total_cost: cost.alternative_total_cost,
      original_plan_paid: cost.original_plan_paid,
      alternative_plan_paid: cost.alternative_plan_paid,
      estimated_annual_savings: cost.estimated_annual_savings,
      member_savings_percentage: cost.member_savings_percentage,
      deductible_met: cost.deductible_met,
      oop_met: cost.oop_met,
      coinsurance_percentage: cost.coinsurance_percentage,
    },
    safety: {
      summary: pbm.safety_summary || 'Reviewed by AI',
      contraindications: safety.contraindications || 'None',
      interactions: safety.interactions || 'None',
      monitoring: safety.monitoring || 'None',
    },
    policy: {
      original_status: policy.original_status || '—',
      alternative_status: policy.alternative_status || '—',
      policy_state: 'client_fallback',
    },
  };
}

function renderPbmResults(rxNumber, data) {
  const contentArea = document.getElementById('results-content');
  const currentRole = getCurrentRole();
  const isPharmacistRole = (currentRole || '').toLowerCase() === 'pharmacist';
  const maySubmitDecision = canSubmitDecision(currentRole);
  const pbm = data.pbm;
  const cost = data.cost || {};
  const safety = data.safety || {};
  const policy = data.policy || {};
  const pastAgentSummary = data.past_agent_summary || {};
  const existingDecision = data.doctor_decision;
  const rejectedAlternatives = Array.isArray(data.rejected_alternatives) ? data.rejected_alternatives : [];
  const alternatives = Array.isArray(data.alternatives) && data.alternatives.length
    ? data.alternatives
    : [];

  // Clinical agent is now the source of truth — orchestrator decision drives status.
  // No threshold-based auto-approval override needed.
  const overallThreshold = Number(
    data.overall_threshold
    || pbm.overall_threshold
    || ((data.scoring_config || {}).overall_threshold)
    || ((pbm.scoring_config || {}).overall_threshold)
    || 0.80
  );
  const normalizedAlternatives = alternatives;
  const resolvedMemberId =
    firstNonEmpty(pbm || {}, ['member_id', 'patient_account_id', 'patient_id'])
    || firstNonEmpty(data || {}, ['member_id', 'patient_account_id', 'patient_id'])
    || firstNonEmpty(normalizedAlternatives[0] || {}, ['member_id', 'patient_account_id', 'patient_id']);
  const displayPbm = {
    ...pbm,
    member_id: resolvedMemberId || '',
    patient_account_id: firstNonEmpty(pbm || {}, ['patient_account_id']) || resolvedMemberId || '',
  };
  const decisionStatus = String((existingDecision || {}).status || '').toUpperCase();
  const isRejectedAlternative = (alt) => {
    const reviewStatus = String(alt.review_status || '').toUpperCase();
    const outcome = String(alt.outcome || '').toLowerCase();
    const policyState = String((((alt || {}).policy || {}).policy_state) || '').toLowerCase();
    return reviewStatus === 'REJECTED' || outcome === 'rejected' || policyState === 'deny';
  };
  const allAlternativesRejected = normalizedAlternatives.length > 0
    && normalizedAlternatives.every((alt) => isRejectedAlternative(alt));
  const isDawOutcome = decisionStatus === 'REJECTED' || allAlternativesRejected;
  const isFinalizedOutcome = (
    decisionStatus === 'ACCEPTED'
    || decisionStatus === 'REJECTED'
    || String(displayPbm.status || '').toUpperCase() === 'APPROVED'
    || String(displayPbm.status || '').toUpperCase() === 'KEEP_ORIGINAL'
    || isDawOutcome
  );
  const isUnderReviewView = (
    String(displayPbm.status || '').toUpperCase() === 'ESCALATED'
    && !isFinalizedOutcome
  );
  const summaryStatus = getReviewSummaryStatus(isDawOutcome ? 'KEEP_ORIGINAL' : pbm.status, decisionStatus);
  const totalPastReviews = Number(((pastAgentSummary || {}).metrics || {}).total_reviews || 0);
  const pastAcceptanceRate = Number(((pastAgentSummary || {}).metrics || {}).acceptance_rate || 0);
  const latestPastEntry = Array.isArray((pastAgentSummary || {}).entries) && pastAgentSummary.entries.length
    ? pastAgentSummary.entries[0]
    : null;
  const latestPastOutcome = String((latestPastEntry || {}).outcome || '').toLowerCase();
  const pastGood = totalPastReviews > 0
    ? (latestPastOutcome === 'accepted' || pastAcceptanceRate >= 50)
    : false;

  const formatPastDate = (value) => {
    if (!value) return '—';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return String(value);
    return parsed.toLocaleString();
  };

  const formatPastMoney = (value) => {
    const numeric = Number(value || 0);
    if (!Number.isFinite(numeric) || numeric <= 0) return '—';
    return `$${numeric.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  };

  const buildPastAgentSummarySection = () => {
    if (!isPharmacistRole) return '';
    const selectedAlt = normalizedAlternatives[0] || {};
    const pastPercent = (() => {
      const direct = ((selectedAlt.agent_confidence || {}).past);
      const breakdown = ((selectedAlt.agent_breakdown || {}).past);
      const base = direct !== undefined ? direct : (breakdown !== undefined ? breakdown : (pastGood ? 80 : 45));
      const numeric = Number(base);
      const scaled = Number.isFinite(numeric) ? (numeric <= 1 ? numeric * 100 : numeric) : 0;
      return Math.max(0, Math.min(100, Math.round(scaled)));
    })();
    const pastCardClass = pastGood ? 'agent-card-status--good' : 'agent-card-status--warn';
    const pastBadgeClass = pastGood ? 'review-agent-badge--good' : 'review-agent-badge--warn';
    const pastBadgeLabel = `Past decision confidence ${pastPercent}%`;
    const pastSummaryText = totalPastReviews > 0
      ? (pastGood
        ? 'Historical evidence generally supports the recommendation because similar past cases were accepted by doctors.'
        : 'Historical evidence is mixed or weak for this recommendation and requires closer review.')
      : 'No historical decision evidence is available for this medication context yet.';
    const enhancedSummary = selectedAlt.past_decision_summary || pastSummaryText;

    return `
      <section class="card past-agent-summary-card ${pastCardClass}" aria-label="Past Agent Summary">
        <div class="past-agent-head">
          <h4 class="past-agent-title">Past Decision Summary</h4>
          <span class="review-agent-badge ${pastBadgeClass}" aria-label="${pastBadgeLabel}">${pastPercent}%</span>
        </div>
        <div class="past-agent-empty">${escapeHtml(enhancedSummary)}</div>
      </section>
    `;
  };

  const pastAgentSummaryHtml = buildPastAgentSummarySection();

  let displayAlternatives = normalizedAlternatives.filter((alt) => {
    // Rejected alternatives should not appear in the review list.
    return !isRejectedAlternative(alt);
  });

  const topRankedAlternative = (items) => {
    if (!items.length) {
      return null;
    }
    return [...items].sort((a, b) => {
      const scoreA = Number(a.combined_score ?? a.score ?? 0);
      const scoreB = Number(b.combined_score ?? b.score ?? 0);
      if (scoreB !== scoreA) {
        return scoreB - scoreA;
      }
      const indexA = Number(a.index ?? Number.MAX_SAFE_INTEGER);
      const indexB = Number(b.index ?? Number.MAX_SAFE_INTEGER);
      return indexA - indexB;
    })[0];
  };

  if (decisionStatus === 'ACCEPTED' || String(displayPbm.status || '').toUpperCase() === 'APPROVED') {
    const isAutoApprovedByPbm = String(displayPbm.status || '').toUpperCase() === 'APPROVED';
    // After accept/auto-approve, keep only one top-ranked selected/approved alternative.
    const chosenAlternatives = displayAlternatives.filter((alt) => {
      const reviewStatus = String(alt.review_status || '').toUpperCase();
      const outcome = String(alt.outcome || '').toLowerCase();
      return Boolean(alt.is_selected)
        || reviewStatus === 'APPROVED'
        || reviewStatus === 'ACCEPTED'
        || outcome === 'selected'
        || outcome === 'auto_approved';
    });
    const topChoice = topRankedAlternative(chosenAlternatives) || topRankedAlternative(displayAlternatives);
    displayAlternatives = topChoice
      ? [{
          ...topChoice,
          review_status: (decisionStatus === 'ACCEPTED' && !isAutoApprovedByPbm)
            ? 'ACCEPTED'
            : (topChoice.review_status || 'APPROVED'),
        }]
      : [];
  }

  const effectiveDecision = (decisionStatus === 'REJECTED' && displayAlternatives.length > 0)
    ? null
    : existingDecision;

  const recommendedAltText = String(pbm.recommended_alt || '').trim().toLowerCase();
  const policyAltText = String(policy.alternative_status || '').trim().toLowerCase();
  const isFallbackNoAlternativeRow = displayAlternatives.length === 1
    && String(displayAlternatives[0].label || '').trim().toLowerCase() === 'no alternative recorded';
  const hasNoAlternativeSignal = (
    recommendedAltText === ''
    || recommendedAltText === 'no alternative recorded'
    || policyAltText.includes('no alternative cleared')
  );
  const isNoAlternativesCase = !displayAlternatives.length || (isFallbackNoAlternativeRow && hasNoAlternativeSignal);

  if (isNoAlternativesCase) {
    const noAltDecisionPbm = {
      ...displayPbm,
      status: 'KEEP_ORIGINAL',
    };
    const noAltHtml = `
      <div class="card" id="results-pdf-area">
        <div class="results-summary-strip" style="background:${summaryStatus.background}; border-color:${summaryStatus.border};">
          <div class="results-summary-pill" style="border-left-color:#FF612B;">
            <span class="results-summary-label">Diagnosis</span>
            <span class="results-summary-value">${escapeHtml(pbm.diagnosis_display || pbm.diagnosis || '—')}</span>
          </div>
          <div class="results-summary-pill" style="border-left-color:#12294B;">
            <span class="results-summary-label">Prescribed Drug</span>
            <span class="results-summary-value">${escapeHtml(pbm.prescribed_drug || '—')}</span>
          </div>
          <div class="results-summary-pill" style="border-left-color:${summaryStatus.color};">
            <span class="results-summary-label">Workflow Status</span>
            <span class="results-summary-value" style="color:${summaryStatus.textColor || summaryStatus.color};">${escapeHtml(summaryStatus.label)}</span>
          </div>
        </div>

        <div style="padding: 30px; text-align: center; background: #e8f0fe; border: 1.5px solid #b3ccf5; border-radius: 12px; margin-bottom: 20px;">
          <div style="font-size: 1.2rem; font-weight: 700; color: #1a4fa0; margin-bottom: 6px;">No alternative recorded</div>
          <div style="font-size: 0.9rem; color: #3a5fa0;">The original prescription is the recommended course of action.</div>
        </div>

        ${(!isPharmacistRole) ? `
        <div class="info-grid" style="margin-bottom: 20px;">
          <div class="info-item">
            <strong>Alternative Status:</strong> <span class="badge badge-keep_original">Original Retained</span>
          </div>
          <div class="info-item">
            <strong>Prescribed Drug:</strong> ${escapeHtml(pbm.prescribed_drug || '—')}
          </div>
          <div class="info-item">
            <strong>Diagnosis:</strong> ${escapeHtml(pbm.diagnosis_display || pbm.diagnosis || '—')}
          </div>
          <div class="info-item">
            <strong>Alternative:</strong>
            <div class="recommended-alt-highlight">
              <span class="recommended-alt-text">No alternative recorded</span>
            </div>
          </div>
        </div>
        ` : ''}

        ${buildFinalDecisionSection(rxNumber, noAltDecisionPbm, policy, effectiveDecision, currentRole, maySubmitDecision, rejectedAlternatives, undefined, overallThreshold)}
        ${(!isPharmacistRole) ? pastAgentSummaryHtml : ''}
      </div>
    `;
    contentArea.innerHTML = noAltHtml;
    const dlBtn = document.getElementById('results-download-btn');
    if (dlBtn) {
      dlBtn.style.display = '';
      dlBtn.onclick = () => downloadPDF('results-pdf-area', `PBM_Report_${rxNumber}`);
    }
    return;
  }

  const tabsHtml = displayAlternatives.map((alternative, index) => {
    const isActive = index === 0 ? 'active' : '';
    const tabTitle = alternative.label || `Alternative ${index + 1}`;
    const statusText = formatReviewStatus(alternative.review_status);
    const statusClass = String(alternative.review_status || 'pending_review')
      .toLowerCase()
      .replace(/\s+/g, '_')
      .replace(/[^a-z0-9_]/g, '');
    const altConfPercent = Math.round(Number(alternative.combined_score ?? alternative.score ?? 0) * 100);
    const showStatusBadge = statusText !== 'Original Drug Recommended';
    return `
      <button class="alternative-tab-btn ${isActive}" type="button" data-target="alternative-panel-${index}" data-conf-score="${altConfPercent}">
        <span class="alternative-tab-left">
          <span class="alternative-tab-main">
            <span class="alternative-tab-rank">Alternative ${index + 1}</span>
            <span class="alternative-tab-name">${escapeHtml(tabTitle)}</span>
            ${showStatusBadge ? `<span class="badge badge-${statusClass}">${escapeHtml(statusText)}</span>` : ''}
          </span>
        </span>
        <span class="alternative-tab-score">${altConfPercent}%</span>
      </button>
    `;
  }).join('');

  const panelsHtml = displayAlternatives.map((alternative, index) => `
    <section class="alternative-tab-panel ${index === 0 ? 'active' : ''}" id="alternative-panel-${index}">
      ${buildAlternativePanelHtml(displayPbm, alternative, currentRole)}
      ${index === 0 ? pastAgentSummaryHtml : ''}
    </section>
  `).join('');

  const leftAlternativesHtml = isUnderReviewView
    ? `
        <aside class="alternative-tabs" role="tablist" aria-label="Alternative options">
          ${tabsHtml}
        </aside>
      `
    : '';

  const workspaceClass = isUnderReviewView
    ? 'alternative-workspace'
    : 'alternative-workspace alternative-workspace--single';

  const html = `
    <div class="card" id="results-pdf-area">
      <div class="results-summary-strip" style="background:${summaryStatus.background}; border-color:${summaryStatus.border};">
        <div class="results-summary-pill" style="border-left-color:#FF612B;">
          <span class="results-summary-label">Diagnosis</span>
          <span class="results-summary-value">${escapeHtml(pbm.diagnosis_display || pbm.diagnosis || '—')}</span>
        </div>
        <div class="results-summary-pill" style="border-left-color:#12294B;">
          <span class="results-summary-label">Prescribed Drug</span>
          <span class="results-summary-value">${escapeHtml(pbm.prescribed_drug || '—')}</span>
        </div>
        <div class="results-summary-pill" style="border-left-color:${summaryStatus.color};">
          <span class="results-summary-label">Workflow Status</span>
          <span class="results-summary-value" style="color:${summaryStatus.textColor || summaryStatus.color};">${escapeHtml(summaryStatus.label)}</span>
        </div>
      </div>

      <div class="${workspaceClass}">
        ${leftAlternativesHtml}
        <div class="alternative-tab-panels">
          ${panelsHtml}
        </div>
      </div>

      ${buildFinalDecisionSection(rxNumber, displayPbm, policy, effectiveDecision, currentRole, maySubmitDecision, rejectedAlternatives, Math.round(Number(displayAlternatives[0]?.combined_score ?? displayAlternatives[0]?.score ?? pbm.ai_confidence ?? 0) * 100), overallThreshold)}
    </div>
  `;

  contentArea.innerHTML = html;
  initAlternativeTabs(contentArea);
  const dlBtn = document.getElementById('results-download-btn');
  if (dlBtn) {
    dlBtn.style.display = '';
    dlBtn.onclick = () => downloadPDF('results-pdf-area', `PBM_Report_${rxNumber}`);
  }
}

let pendingDecisionStatus = null;
let pendingDecisionRx = null;
let pendingDecisionAlternativeIndex = null;
let selectedDecisionReasons = [];
let decisionReasonMatches = [];
let decisionReasonDebounce = null;

function getActiveAlternativeIndex() {
  const activeButton = document.querySelector('.alternative-tab-btn.active');
  if (!activeButton) {
    return 0;
  }
  const target = String(activeButton.getAttribute('data-target') || '');
  const match = target.match(/alternative-panel-(\d+)/);
  return match ? Number(match[1]) : 0;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

async function showDecisionReason(status, rxNumber) {
  pendingDecisionStatus = status;
  pendingDecisionRx = rxNumber;
  pendingDecisionAlternativeIndex = getActiveAlternativeIndex();

  const container = document.getElementById('decision-reason-container');
  const rejectFields = document.getElementById('decision-reject-fields');
  const searchInput = document.getElementById('decision-reason-search');
  const commentInput = document.getElementById('decision-comment-input');
  const submitButton = document.getElementById('submit-decision-btn');

  if (!container || !commentInput || !submitButton) {
    return;
  }

  selectedDecisionReasons = [];
  decisionReasonMatches = [];

  container.classList.add('show');
  commentInput.value = '';
  submitButton.textContent = status === 'ACCEPTED' ? 'Submit Accept' : 'Submit Reject';
  submitButton.onclick = submitDecision;

  if (rejectFields) {
    rejectFields.classList.toggle('show', status === 'REJECTED');
  }

  if (searchInput) {
    searchInput.value = '';
    searchInput.oninput = handleDecisionReasonInput;
    searchInput.onkeydown = handleDecisionReasonKeydown;
  }

  renderSelectedDecisionReasons();
  clearDecisionReasonSuggestions();

  if (status === 'REJECTED') {
    if (searchInput) {
      searchInput.focus();
    }
  } else {
    commentInput.focus();
  }
}

function cancelDecision() {
  const container = document.getElementById('decision-reason-container');
  const commentInput = document.getElementById('decision-comment-input');
  const searchInput = document.getElementById('decision-reason-search');

  if (container) {
    container.classList.remove('show');
  }
  if (commentInput) {
    commentInput.value = '';
  }
  if (searchInput) {
    searchInput.value = '';
  }
  selectedDecisionReasons = [];
  decisionReasonMatches = [];
  clearDecisionReasonSuggestions();
  renderSelectedDecisionReasons();
  pendingDecisionStatus = null;
  pendingDecisionRx = null;
  pendingDecisionAlternativeIndex = null;
}

function renderSelectedDecisionReasons() {
  const chipContainer = document.getElementById('decision-selected-reasons');
  if (!chipContainer) {
    return;
  }

  chipContainer.innerHTML = '';
  selectedDecisionReasons.forEach((item) => {
    const chip = document.createElement('span');
    chip.className = 'decision-chip';

    const label = document.createElement('span');
    label.textContent = item.label;

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'decision-chip-remove';
    removeBtn.setAttribute('aria-label', `Remove ${item.label}`);
    removeBtn.textContent = 'x';
    removeBtn.onclick = () => removeDecisionReason(item.code);

    chip.appendChild(label);
    chip.appendChild(removeBtn);
    chipContainer.appendChild(chip);
  });
}

function renderDecisionReasonSuggestions() {
  const list = document.getElementById('decision-reason-suggestions');
  if (!list) {
    return;
  }

  list.innerHTML = '';

  if (pendingDecisionStatus !== 'REJECTED' || decisionReasonMatches.length === 0) {
    list.classList.remove('open');
    return;
  }

  decisionReasonMatches.forEach((item) => {
    const li = document.createElement('li');
    li.innerHTML = `<span class="decision-reason-code">${escapeHtml(item.code)}</span><span class="decision-reason-text">${escapeHtml(item.label)}</span>`;
    li.addEventListener('mousedown', (event) => {
      event.preventDefault();
      addDecisionReason(item);
    });
    list.appendChild(li);
  });

  list.classList.add('open');
}

function clearDecisionReasonSuggestions() {
  const list = document.getElementById('decision-reason-suggestions');
  if (!list) {
    return;
  }

  list.innerHTML = '';
  list.classList.remove('open');
}

function addDecisionReason(item) {
  if (selectedDecisionReasons.some((selected) => selected.code === item.code)) {
    return;
  }

  selectedDecisionReasons.push(item);
  renderSelectedDecisionReasons();

  const searchInput = document.getElementById('decision-reason-search');
  if (searchInput) {
    searchInput.value = '';
    searchInput.focus();
  }

  decisionReasonMatches = [];
  clearDecisionReasonSuggestions();
}

function removeDecisionReason(code) {
  selectedDecisionReasons = selectedDecisionReasons.filter((item) => item.code !== code);
  renderSelectedDecisionReasons();
}

function handleDecisionReasonInput(event) {
  window.clearTimeout(decisionReasonDebounce);
  const query = event.target.value.trim();
  if (!query) {
    decisionReasonMatches = [];
    clearDecisionReasonSuggestions();
    return;
  }
  decisionReasonDebounce = window.setTimeout(() => {
    loadDecisionReasonSuggestions(query);
  }, 150);
}

function handleDecisionReasonKeydown(event) {
  if (event.key === 'Enter' && decisionReasonMatches.length > 0) {
    event.preventDefault();
    addDecisionReason(decisionReasonMatches[0]);
    return;
  }

  if (event.key === 'Enter') {
    event.preventDefault();
    const query = event.target.value.trim();
    if (query) {
      loadDecisionReasonSuggestions(query);
    }
    return;
  }

  if (event.key === 'Backspace' && !event.target.value && selectedDecisionReasons.length > 0) {
    removeDecisionReason(selectedDecisionReasons[selectedDecisionReasons.length - 1].code);
    return;
  }

  if (event.key === 'Escape') {
    clearDecisionReasonSuggestions();
  }
}

async function loadDecisionReasonSuggestions(query) {
  try {
    const response = await autofetch('/api/decision-reasons?q=' + encodeURIComponent(query));
    const data = await response.json();

    if (!response.ok) {
      clearDecisionReasonSuggestions();
      return;
    }

    const selectedCodes = new Set(selectedDecisionReasons.map((item) => item.code));
    decisionReasonMatches = data.filter((item) => !selectedCodes.has(item.code));
    renderDecisionReasonSuggestions();
  } catch (error) {
    clearDecisionReasonSuggestions();
  }
}

async function submitDecision() {
  const commentInput = document.getElementById('decision-comment-input');
  const submitButton = document.getElementById('submit-decision-btn');
  const comment = commentInput ? commentInput.value.trim() : '';

  if (!pendingDecisionStatus || !pendingDecisionRx) {
  // Show and initialize progress bar
  const progressContainer = document.getElementById('submit-progress-container');
  const progressBar = document.getElementById('submit-progress-bar');
  const progressText = document.getElementById('submit-progress-text');
  progressContainer.style.display = 'block';
  progressBar.style.width = '0%';
  progressText.textContent = '0%';

  let progressPercent = 0;
  let progressInterval;

  // Simulate progress increment (starts fast, slows down)
  const simulateProgress = () => {
    progressInterval = setInterval(() => {
      if (progressPercent < 90) {
        const increment = Math.random() * (90 - progressPercent) * 0.1;
        progressPercent += increment;
        updateProgressBar(Math.min(progressPercent, 90));
      }
    }, 300);
  };

  const updateProgressBar = (percent) => {
    progressBar.style.width = percent + '%';
    progressText.textContent = Math.round(percent) + '%';
  };

  const completeProgress = () => {
    clearInterval(progressInterval);
    updateProgressBar(100);
    progressText.textContent = '100%';
  };

  simulateProgress();
    showToast('Select a decision before submitting');
    return;
  }

  if (pendingDecisionStatus === 'REJECTED' && selectedDecisionReasons.length === 0) {
    showToast('Please select at least one rejection reason');
    const searchInput = document.getElementById('decision-reason-search');
    if (searchInput) {
      searchInput.focus();
    }
    return;
  }
  
  if (submitButton) {
    submitButton.disabled = true;
    submitButton.textContent = 'Saving...';
  }

  try {
    const response = await autofetch(`/api/prescription/${pendingDecisionRx}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        status: pendingDecisionStatus,
        comment,
        reason_codes: selectedDecisionReasons.map((item) => item.code),
        alternative_index: pendingDecisionAlternativeIndex
      })
    });
    completeProgress();


    const data = await response.json();
    
    if (response.ok) {
      cancelDecision();
      // Hide progress bar after 1 second
      setTimeout(() => {
        progressContainer.style.display = 'none';
      }, 1000);
      showToast('Decision saved successfully');
      handleResultsSearch();
    } else {
      // Hide progress bar on error after 1.5 seconds
      setTimeout(() => {
        progressContainer.style.display = 'none';
      }, 1500);
      showToast(data.error || 'Failed to save decision');
    }
  } catch (error) {
    showToast('Network error while saving decision');
    completeProgress();
    // Hide progress bar on error after 1.5 seconds
    setTimeout(() => {
      progressContainer.style.display = 'none';
    }, 1500);
  } finally {
    if (submitButton) {
      submitButton.disabled = false;
      submitButton.textContent = pendingDecisionStatus === 'ACCEPTED' ? 'Submit Accept' : 'Submit Reject';
    }
  }
}

async function loadDashboard() {
  const contentArea = document.getElementById('dashboard-content');
  const statsArea = document.getElementById('dashboard-stats');
  const currentRole = getCurrentRole();
  const isPharmacist = currentRole === 'pharmacist';
  const dashboardTitle = document.getElementById('dashboard-title');
  const dashboardSubtitle = document.getElementById('dashboard-subtitle');
  const overviewStepper = document.getElementById('overview-stepper');

  if (dashboardTitle) {
    dashboardTitle.textContent = isPharmacist ? 'Prescription Overview' : 'All Prescriptions';
  }
  if (dashboardSubtitle) {
    dashboardSubtitle.textContent = 'Complete overview of all submitted prescriptions';
  }
  if (overviewStepper) {
    overviewStepper.style.display = isPharmacist ? 'flex' : 'none';
  }

  const getEffectivePbmStatus = (row) => {
    // Respect the status stored by the orchestrator — clinical agent drives this.
    return String(row.pbm_status || '').toUpperCase() || null;
  };

  const getActivityInfo = (row) => {
    const status = getEffectivePbmStatus(row);
    if (!status) {
      return { type: 'in-progress', text: 'submitted for AI analysis.' };
    }
    if (status === 'APPROVED') {
      return { type: 'auto-approved', text: 'auto-approved by AI agents.' };
    }
    if (status === 'ESCALATED') {
      return { type: 'review', text: 'escalated for clinical review.' };
    }
    if (status === 'KEEP_ORIGINAL') {
      return { type: 'daw', text: 'original medication retained after review.' };
    }
    return { type: 'accept', text: 'review completed in workflow.' };
  };

  const getWorkflowStatus = (row) => {
    const status = getEffectivePbmStatus(row);
    const decisionStatus = String(row.decision_status || '').toUpperCase();

    if (decisionStatus === 'ACCEPTED' && status !== 'APPROVED') {
      return { label: 'Accept', className: 'accept' };
    }
    if (decisionStatus === 'REJECTED') {
      return { label: 'DAW', className: 'daw' };
    }
    if (status === 'APPROVED') {
      return { label: 'Auto Approve', className: 'auto-approve' };
    }
    if (status === 'KEEP_ORIGINAL') {
      return { label: 'DAW', className: 'daw' };
    }
    if (status === 'ESCALATED') {
      return { label: 'Under Review', className: 'under-review' };
    }
    if (!status) {
      return { label: 'In Progress', className: 'in-progress' };
    }
    return { label: 'Pending', className: 'pending' };
  };

  const relativeDate = (value) => {
    if (!value) return 'recently';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return 'recently';
    const now = new Date();
    const diffMs = Math.max(0, now.getTime() - parsed.getTime());
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    if (diffDays === 0) return 'today';
    if (diffDays === 1) return '1 day ago';
    return `${diffDays} days ago`;
  };
  
  try {
    const response = await autofetch('/api/prescriptions');
    const data = await response.json();
    
    if (response.ok) {
      // For provider/pbm personas, skip rebuilding the table - templates already render correctly from presenter
      if (!isPharmacist) {
        return;
      }
      
      const total = data.length;
      // PBM Completed = PBM response exists
      const pbmCompleted = data.filter(r => r.pbm_status !== null).length;
      // Processing = PBM not yet returned
      const processing = data.filter(r => r.pbm_status === null).length;
      // Auto-approved are PBM approved with an auto-created ACCEPTED decision
      const autoApproved = data.filter(r => getEffectivePbmStatus(r) === 'APPROVED').length;
      // Manual decisions = any decision recorded that isn't an auto-approval
      const manualDecisions = data.filter(r => r.decision_status !== null && !(getEffectivePbmStatus(r) === 'APPROVED' && r.decision_status === 'ACCEPTED')).length;

      // Show summary cards: Total RXs, Auto Approved, Provider Decisions (manual), Pending Decisions
      const pendingDecisions = data.filter(r => getEffectivePbmStatus(r) === 'ESCALATED' && r.decision_status === null).length;

      if (isPharmacist) {
        statsArea.innerHTML = '';
      } else {
        statsArea.innerHTML = `
          <div class="stats-row">
            <div class="stat-card">
              <div class="stat-value">${total}</div>
              <div style="font-size: 0.8rem; color: var(--text-primary); font-weight: 600; margin-bottom: 2px;">Total RXs</div>
              <div style="font-size: 0.72rem; color: var(--text-muted);">Prescriptions submitted</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">${autoApproved}</div>
              <div style="font-size: 0.8rem; color: var(--text-primary); font-weight: 600; margin-bottom: 2px;">Auto Approved</div>
              <div style="font-size: 0.72rem; color: var(--text-muted);">Accepted by AI without provider review</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">${manualDecisions}</div>
              <div style="font-size: 0.8rem; color: var(--text-primary); font-weight: 600; margin-bottom: 2px;">Reviewed decisions</div>
              <div style="font-size: 0.72rem; color: var(--text-muted);">Final decision reviewed by provider</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">${pendingDecisions}</div>
              <div style="font-size: 0.8rem; color: var(--text-primary); font-weight: 600; margin-bottom: 2px;">Pending Decisions</div>
              <div style="font-size: 0.72rem; color: var(--text-muted);">Awaiting final portal review</div>
            </div>
          </div>
        `;
      }

      if (data.length === 0) {
        contentArea.innerHTML = `<div class="empty-state"><p>No prescriptions found.</p></div>`;
        return;
      }

      const isCompletedOutcome = (row) => {
        const effectivePbmStatus = getEffectivePbmStatus(row);
        const status = String(row.decision_status || '').toUpperCase();
        if (effectivePbmStatus === 'APPROVED') return 'completed'; // Auto Approve final
        if (status === 'ACCEPTED') return 'completed'; // Doctor final Accept
        if (status === 'REJECTED') return 'completed'; // Doctor final DAW
        return false;
      };

      const isUnderReviewPending = (row) => {
        const effectivePbmStatus = getEffectivePbmStatus(row);
        return effectivePbmStatus === 'ESCALATED' && !isCompletedOutcome(row);
      };

      const tabCounts = {
        pending: data.filter(row => isUnderReviewPending(row)).length,
        completed: data.filter(row => isCompletedOutcome(row)).length,
        all: data.length,
      };

      const renderStatusPill = (label, className) =>
        `<span class="dashboard-inline-status ${className}">${escapeHtml(label)}</span>`;

      const renderRows = (rows) => {
        if (!rows.length) {
          const emptyCols = isPharmacist ? 8 : 8;
          return `<tr><td colspan="${emptyCols}" class="empty-state" style="padding: 20px;">No records found for this tab.</td></tr>`;
        }

        return rows.map((row) => {
          if (isPharmacist) {
            const memberId = row.member_id || row.patient_account_id || '—';
            const medication = row.medication || row.prod_nm || '—';
            const dateWritten = row.date_written || '—';
            const dueDate = row.due_date || '—';
            const workflow = getWorkflowStatus(row);
            const workflowProgressState = isCompletedOutcome(row) ? 'completed' : 'pending';
            return `
              <tr class="dashboard-record-row" style="cursor: pointer;" data-rx-number="${escapeHtml(row.rx_number)}" data-status="${workflowProgressState}">
                <td>${row.rx_number}</td>
                <td>${memberId}</td>
                <td>${medication}</td>
                <td>${dateWritten}</td>
                <td>${row.insurance_phase || '—'}</td>
                <td>${row.ytd_oop !== null && row.ytd_oop !== undefined ? `$${Number(row.ytd_oop).toFixed(2)}` : '—'}</td>
                <td>${escapeHtml(dueDate)}</td>
                <td>
                  <button type="button" class="dashboard-status-trigger" aria-label="View workflow status for ${escapeHtml(row.rx_number)}">
                    <span class="dashboard-inline-status ${workflow.className}">${workflow.label}</span>
                  </button>
                </td>
              </tr>
            `;
          }

          const effectivePbmStatus = getEffectivePbmStatus(row);
          const totalAlternatives = Number(row.total_alternatives_count || 0);
          const activeAlternatives = Number(row.active_alternatives_count || 0);
          const allAlternativesRejected = totalAlternatives > 0 && activeAlternatives === 0;
          const decisionStatus = String(row.decision_status || '').toUpperCase();
          const isDawOutcome = decisionStatus === 'REJECTED' || (effectivePbmStatus === 'KEEP_ORIGINAL' && allAlternativesRejected);
          const memberId = row.member_id || row.patient_account_id || '—';
          const medication = row.medication || row.prod_nm || '—';

          let pbmBadge;
          if (effectivePbmStatus === 'APPROVED') {
            pbmBadge = renderStatusPill('Auto Approve', 'auto-approve');
          } else if (decisionStatus === 'ACCEPTED') {
            pbmBadge = renderStatusPill('ACCEPT', 'accept');
          } else if (isDawOutcome) {
            pbmBadge = renderStatusPill('DAW', 'daw');
          } else if (effectivePbmStatus === 'KEEP_ORIGINAL') {
            pbmBadge = renderStatusPill('DAW', 'daw');
          } else if (effectivePbmStatus === 'ESCALATED') {
            pbmBadge = renderStatusPill('Under Review', 'under-review');
          } else if (effectivePbmStatus) {
            pbmBadge = renderStatusPill('Awaiting Review', 'pending');
          } else {
            pbmBadge = renderStatusPill('Submitted', 'in-progress');
          }

          let decisionBadge;
          if (effectivePbmStatus === 'APPROVED') {
            decisionBadge = renderStatusPill('Auto Accept', 'auto-approve');
          } else if (isDawOutcome) {
            decisionBadge = renderStatusPill('DAW', 'daw');
          } else if (effectivePbmStatus === 'KEEP_ORIGINAL') {
            decisionBadge = renderStatusPill('DAW', 'daw');
          } else if (decisionStatus === 'ACCEPTED') {
            decisionBadge = renderStatusPill('ACCEPT', 'accept');
          } else if (decisionStatus) {
            decisionBadge = renderStatusPill('Awaiting Review', 'pending');
          } else {
            decisionBadge = renderStatusPill('Submitted', 'in-progress');
          }

          return `
            <tr style="cursor: pointer;" onclick="goToResults('${row.rx_number}')">
              <td>${row.rx_number}</td>
              <td>${memberId}</td>
              <td>${medication}</td>
              <td>${row.date_written}</td>
              <td>${row.insurance_phase || '—'}</td>
              <td>${row.ytd_oop !== null && row.ytd_oop !== undefined ? `$${Number(row.ytd_oop).toFixed(2)}` : '—'}</td>
              <td>${row.due_date || '—'}</td>
              <td>${pbmBadge}</td>
              <td>${decisionBadge}</td>
            </tr>
          `;
        }).join('');
      };

      const dashboardTableHead = `
        ${isPharmacist ? `
          <thead>
            <tr>
              <th>RX Number</th>
              <th>Member ID</th>
              <th>Medication</th>
              <th>Date Written</th>
              <th>Insurance Phase</th>
              <th>YTD OOP</th>
              <th>Due Date</th>
              <th>Workflow Status</th>
            </tr>
          </thead>
        ` : `
          <thead>
            <tr>
              <th>RX Number</th>
              <th>Member ID</th>
              <th>Medication</th>
              <th>Date Written</th>
              <th>Insurance Phase</th>
              <th>YTD OOP</th>
              <th>Due Date</th>
              <th>
                <span class="header-with-tooltip">
                  PBM Status
                  <span class="header-help" tabindex="0" aria-label="PBM status legend">i</span>
                  <span class="header-tooltip" role="tooltip">
                    <span class="tooltip-title">Legend</span>
                    <span class="legend-item">
                      <span class="legend-dot legend-auto-approved" aria-hidden="true"></span>
                      <strong>Auto Approved</strong>: accepted by PBM AI without manual review
                    </span>
                    <span class="legend-item">
                      <span class="legend-dot legend-escalated" aria-hidden="true"></span>
                      <strong>ESCALATED</strong>: manual clinician review needed
                    </span>
                    <span class="legend-item">
                      <span class="legend-dot legend-keep_original" aria-hidden="true"></span>
                      <strong>Original Drug Recommended</strong>: no alternative cleared thresholds
                    </span>
                    <span class="legend-item">
                      <span class="legend-dot legend-accepted" aria-hidden="true"></span>
                      <strong>ACCEPTED</strong>: original prescription accepted
                    </span>
                  </span>
                </span>
              </th>
              <th>
                <span class="header-with-tooltip">
                  Final Decision
                  <span class="header-help" tabindex="0" aria-label="Final decision legend">i</span>
                  <span class="header-tooltip" role="tooltip">
                    <span class="tooltip-title">Legend</span>
                    <span class="legend-item">
                      <span class="legend-dot legend-accepted" aria-hidden="true"></span>
                      <strong>ACCEPTED</strong>: recommendation accepted
                    </span>
                    <span class="legend-item">
                      <span class="legend-dot legend-rejected" aria-hidden="true"></span>
                      <strong>REJECTED</strong>: recommendation declined
                    </span>
                    <span class="legend-item">
                      <span class="legend-dot legend-auto-approved" aria-hidden="true"></span>
                      <strong>Auto Accept</strong>: AI approved without manual review
                    </span>
                    <span class="legend-item">
                      <span class="legend-dot legend-rejected" aria-hidden="true"></span>
                      <strong>DAW</strong>: all alternatives rejected, dispense as written
                    </span>
                    <span class="legend-item">
                      <span class="legend-dot legend-pending" aria-hidden="true"></span>
                      <strong>Pending</strong>: decision not submitted yet
                    </span>
                  </span>
                </span>
              </th>
            </tr>
          </thead>
        `}
      `;

      const recentActivityRows = [...data]
        .sort((a, b) => new Date(b.date_written || 0) - new Date(a.date_written || 0))
        .map((row) => {
          const activity = getActivityInfo(row);
          return `
            <div class="dashboard-activity-item">
              <span class="dashboard-activity-dot ${activity.type}" aria-hidden="true"></span>
              <div class="dashboard-activity-body">
                <div class="dashboard-activity-head">
                  <span class="dashboard-activity-rx">${escapeHtml(row.rx_number || 'RX')}</span>
                </div>
                <div class="dashboard-activity-text">${escapeHtml(activity.text)}</div>
                <div class="dashboard-activity-time">${escapeHtml(relativeDate(row.date_written))}</div>
              </div>
            </div>
          `;
        })
        .join('') || '<div class="dashboard-activity-text">No recent activity yet.</div>';


      const dashboardRecordsMarkup = `
        <div class="dashboard-record-header">
          <h3 class="dashboard-record-title">Prescription Records</h3>
          <div class="dashboard-record-search-wrap">
            <span class="dashboard-record-search-icon" aria-hidden="true">&#128269;</span>
            <input
              id="dashboard-record-search"
              class="dashboard-record-search"
              type="search"
              placeholder="Search RX Number, Member ID, Medication"
              aria-label="Search prescription records"
            />
          </div>
        </div>
        <div class="dashboard-record-tabs" role="tablist" aria-label="Prescription record tabs">
          <button class="dashboard-record-tab active" type="button" role="tab" aria-selected="true" data-tab="pending">
            Pending (${tabCounts.pending})
          </button>
          <button class="dashboard-record-tab" type="button" role="tab" aria-selected="false" data-tab="completed">
            Completed (${tabCounts.completed})
          </button>
          <button class="dashboard-record-tab" type="button" role="tab" aria-selected="false" data-tab="all">
            All (${tabCounts.all})
          </button>
        </div>
        <div style="overflow-x: auto;">
          <table class="data-table">
            ${dashboardTableHead}
            <tbody id="dashboard-records-body"></tbody>
          </table>
        </div>
        <div id="dashboard-view-all-wrap" class="dashboard-view-all-wrap" style="display: none;">
          <button type="button" id="dashboard-view-all-btn" class="btn dashboard-view-all-btn">View all prescriptions</button>
        </div>
      `;

      contentArea.innerHTML = isPharmacist
        ? `
          <div class="dashboard-overview-grid">
            <div class="dashboard-records-card">${dashboardRecordsMarkup}</div>
            <aside class="dashboard-overview-rail">
              <section class="dashboard-mini-card dashboard-mini-card-activity">
                <h4 class="dashboard-mini-title">Recent Activity</h4>
                <div class="dashboard-activity-timeline">
                  ${recentActivityRows}
                </div>
              </section>
              <section class="dashboard-mini-card dashboard-mini-card-legend">
                <h4 class="dashboard-mini-title">Legend</h4>
                <div class="dashboard-legend-item"><span class="dashboard-legend-swatch status-under-review"></span><span class="dashboard-legend-text">Referred for clinical review due to low confidence.</span></div>
                <div class="dashboard-legend-item"><span class="dashboard-legend-swatch status-auto-approve"></span><span class="dashboard-legend-text">Automatically approved due to high confidence.</span></div>
                <div class="dashboard-legend-item"><span class="dashboard-legend-swatch status-daw"></span><span class="dashboard-legend-text">Original medication retained after clinical review.</span></div>
                <div class="dashboard-legend-item"><span class="dashboard-legend-swatch status-accept"></span><span class="dashboard-legend-text">Alternative medication approved by clinician.</span></div>
              </section>
            </aside>
          </div>
        `
        : dashboardRecordsMarkup;

      const tableBody = document.getElementById('dashboard-records-body');
      const tabButtons = Array.from(contentArea.querySelectorAll('.dashboard-record-tab'));
      const recordsSearchInput = document.getElementById('dashboard-record-search');
      const viewAllWrap = document.getElementById('dashboard-view-all-wrap');
      const viewAllBtn = document.getElementById('dashboard-view-all-btn');
      let activeTab = 'pending';
      const pharmacistInitialLimit = 5;
      let showAllPharmacistRows = false;

      const matchesSearch = (row, query) => {
        if (!query) {
          return true;
        }

        const haystack = [
          row.rx_number,
          row.member_id,
          row.patient_account_id,
          row.medication,
          row.prod_nm,
        ]
          .filter(Boolean)
          .join(' ')
          .toLowerCase();

        return haystack.includes(query);
      };

      const applyTab = (tabName) => {
        activeTab = tabName;

        const tabRows = tabName === 'pending'
          ? data.filter(row => isUnderReviewPending(row))
          : tabName === 'completed'
            ? data.filter(row => isCompletedOutcome(row))
            : data;

        const searchQuery = (recordsSearchInput?.value || '').trim().toLowerCase();
        const filteredRows = tabRows.filter((row) => matchesSearch(row, searchQuery));

        let rowsToRender = filteredRows;
        if (isPharmacist && !showAllPharmacistRows) {
          rowsToRender = filteredRows.slice(0, pharmacistInitialLimit);
        }

        tableBody.innerHTML = renderRows(rowsToRender);

        if (viewAllWrap && viewAllBtn) {
          if (isPharmacist && !showAllPharmacistRows && filteredRows.length > pharmacistInitialLimit) {
            viewAllWrap.style.display = 'flex';
            viewAllBtn.textContent = `View all ${filteredRows.length} prescriptions ->`;
          } else {
            viewAllWrap.style.display = 'none';
          }
        }

        tabButtons.forEach((button) => {
          const isActive = button.dataset.tab === tabName;
          button.classList.toggle('active', isActive);
          button.setAttribute('aria-selected', String(isActive));
        });
      };

      tabButtons.forEach((button) => {
        button.addEventListener('click', () => {
          showAllPharmacistRows = false;
          applyTab(button.dataset.tab);
        });
      });

      if (recordsSearchInput) {
        recordsSearchInput.addEventListener('input', () => {
          showAllPharmacistRows = false;
          applyTab(activeTab);
        });
      }

      if (viewAllBtn) {
        viewAllBtn.addEventListener('click', () => {
          showAllPharmacistRows = true;
          applyTab(activeTab);
        });
      }

      if (tableBody && isPharmacist) {
        tableBody.addEventListener('click', (event) => {
          const row = event.target.closest('.dashboard-record-row');
          if (!row) return;

          const rxNumber = row.getAttribute('data-rx-number') || '';
          if (!rxNumber) return;

          const statusTrigger = event.target.closest('.dashboard-status-trigger');
          if (statusTrigger) {
            event.preventDefault();
            event.stopPropagation();
            if (window.WorkflowStatusModal && typeof window.WorkflowStatusModal.openFromRow === 'function') {
              window.WorkflowStatusModal.openFromRow(row);
            }
            return;
          }

          goToResults(rxNumber);
        });
      }

      // Default tab is Pending to prioritize pending reviews at load.
      applyTab('pending');
    } else {
      contentArea.innerHTML = `<div class="empty-state"><p>Failed to load dashboard</p></div>`;
    }
  } catch (error) {
    contentArea.innerHTML = `<div class="empty-state"><p>Network error loading dashboard</p></div>`;
  }
}

function showToast(message) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

document.addEventListener('click', (event) => {
  const searchInput = document.getElementById('decision-reason-search');
  const suggestionList = document.getElementById('decision-reason-suggestions');

  if (!searchInput || !suggestionList) {
    return;
  }

  if (!searchInput.contains(event.target) && !suggestionList.contains(event.target)) {
    clearDecisionReasonSuggestions();
  }
});

function downloadPDF(elementId, filename) {
  const element = document.getElementById(elementId);
  if (!element) return;
  const opt = {
    margin: 10,
    filename: `${filename}.pdf`,
    image: { type: 'jpeg', quality: 0.98 },
    html2canvas: { scale: 2 },
    jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
  };
  showToast('Generating PDF...');
  html2pdf().set(opt).from(element).save().then(() => {
    showToast('PDF downloaded');
  }).catch(err => {
    console.error(err);
    showToast('Error generating PDF');
  });
}

document.addEventListener('DOMContentLoaded', init);
