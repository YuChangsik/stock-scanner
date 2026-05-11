const BASE = '/api/v1';

function getToken() { return localStorage.getItem('token'); }
function setToken(t) { localStorage.setItem('token', t); }
function setNickname(n) { localStorage.setItem('nickname', n); }
function getNickname() { return localStorage.getItem('nickname'); }

function clearAuth() {
  localStorage.removeItem('token');
  localStorage.removeItem('nickname');
}

function authHeaders() {
  return { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` };
}

async function apiFetch(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: authHeaders(),
    ...options,
  });
  if (res.status === 401) {
    clearAuth();
    location.href = '/login.html';
    return;
  }
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || '요청 실패');
  return data;
}

// ── Auth ──────────────────────────────────────────────────────────────────────

async function login(username, password) {
  const form = new URLSearchParams({ username, password });
  const res = await fetch(BASE + '/auth/login', { method: 'POST', body: form });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || '로그인 실패');
  setToken(data.access_token);
  setNickname(data.nickname);
  return data;
}

async function signup(username, password, nickname) {
  const res = await fetch(BASE + '/auth/signup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, nickname }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || '회원가입 실패');
  setToken(data.access_token);
  setNickname(data.nickname);
  return data;
}

async function getMe() { return apiFetch('/auth/me'); }

async function updateConditions(conditions) {
  return apiFetch('/auth/me/conditions', {
    method: 'PUT',
    body: JSON.stringify({ conditions }),
  });
}

// ── Stocks ────────────────────────────────────────────────────────────────────

async function getStocks(market) {
  const q = market ? `?market=${market}` : '';
  return apiFetch(`/stocks${q}`);
}

async function getIndicators(ticker) {
  return apiFetch(`/stocks/${ticker}/indicators`);
}

async function getStockDetail(ticker) {
  return apiFetch(`/stocks/${ticker}/detail`);
}

// ── Scan ──────────────────────────────────────────────────────────────────────

async function runScan(conditions, trade_date) {
  // trade_date is optional — server defaults to latest available date
  const body = trade_date ? { trade_date, conditions } : { conditions };
  return apiFetch('/scan', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

async function getLatestTradeDate() {
  return apiFetch('/scan/latest-date');
}

async function getLatestResults() {
  return apiFetch('/scan/results/latest');
}

// ── Stocks ────────────────────────────────────────────────────────────────────

async function getSectors() {
  return apiFetch('/stocks/sectors');
}

async function getSectorStats() {
  return apiFetch('/stocks/sector-stats');
}

async function getSectorStocks(sectorName) {
  return apiFetch(`/stocks/sector/${encodeURIComponent(sectorName)}/stocks`);
}

async function getTickerPrices(ticker, days = 90) {
  return apiFetch(`/stocks/${ticker}/prices?days=${days}`);
}

async function getResearch(startDate, endDate, page = 1, pageSize = 30) {
  const params = new URLSearchParams({ page, page_size: pageSize });
  if (startDate) params.set('start_date', startDate);
  if (endDate)   params.set('end_date',   endDate);
  return apiFetch(`/stocks/research?${params}`);
}

// ── Admin / Batch ─────────────────────────────────────────────────────────────

async function getLatestTradingDay() {
  return apiFetch('/admin/latest-trading-day');
}

async function triggerBatch(date) {
  const q = date ? `?date=${date}` : '';
  return apiFetch(`/admin/trigger-batch${q}`, { method: 'POST' });
}

async function triggerRange(startDate, endDate) {
  return apiFetch(`/admin/trigger-range?start_date=${startDate}&end_date=${endDate}`, { method: 'POST' });
}

async function getBatchStatus() {
  return apiFetch('/admin/batch-status');
}

async function getDataDates(months = 6) {
  return apiFetch(`/admin/data-dates?months=${months}`);
}

// ── Notify / KakaoTalk ────────────────────────────────────────────────────────

async function getKakaoAuthUrl() {
  return apiFetch('/notify/kakao/auth-url');
}

async function getKakaoStatus() {
  return apiFetch('/notify/kakao/status');
}

async function disconnectKakao() {
  return apiFetch('/notify/kakao/disconnect', { method: 'DELETE' });
}

async function testNotify() {
  return apiFetch('/notify/kakao/test', { method: 'POST' });
}

async function getNotifyConfig() {
  return apiFetch('/notify/config');
}

async function updateNotifyConfig(conditions, schedule) {
  return apiFetch('/notify/config', {
    method: 'PUT',
    body: JSON.stringify({ conditions, schedule }),
  });
}

// ── Permissions ───────────────────────────────────────────────────────────────

async function getPermPages()  { return apiFetch('/permissions/pages'); }
async function getPermRoles()  { return apiFetch('/permissions/roles'); }
async function updatePermRole(role, allowed_pages) {
  return apiFetch(`/permissions/roles/${role}`, {
    method: 'PUT',
    body: JSON.stringify({ allowed_pages }),
  });
}
async function getPermUsers()  { return apiFetch('/permissions/users'); }
async function updateUserRole(uid, role) {
  return apiFetch(`/permissions/users/${uid}`, {
    method: 'PUT',
    body: JSON.stringify({ role }),
  });
}

// ── Analysis / ChatGPT ────────────────────────────────────────────────────────

async function getAnalysisTemplate() { return apiFetch('/analysis/template'); }
async function updateAnalysisTemplate(data) {
  return apiFetch('/analysis/template', { method: 'PUT', body: JSON.stringify(data) });
}
async function resetAnalysisTemplate() {
  return apiFetch('/analysis/template/reset', { method: 'POST' });
}
async function runAnalysis(ticker, avg_price) {
  return apiFetch('/analysis/run', {
    method: 'POST',
    body: JSON.stringify({ ticker, avg_price: avg_price || null }),
  });
}

// ── Role-based nav ────────────────────────────────────────────────────────────

/**
 * 현재 로그인 사용자의 역할을 캐시하여 반환.
 * 로그인 후 localStorage에 'role' 저장.
 */
function getRole() { return localStorage.getItem('role') || 'user'; }
function setRole(r) { localStorage.setItem('role', r); }

/**
 * applyNavPermissions(allowedPages)
 * allowedPages: 서버에서 받은 이 사용자 역할의 허용 페이지 키 배열.
 * data-page 속성이 있는 nav 링크를 허용 목록 기준으로 숨김.
 */
function applyNavPermissions(allowedPages) {
  const allowed = new Set(allowedPages || []);
  document.querySelectorAll('[data-page]').forEach(function(el) {
    const key = el.getAttribute('data-page');
    el.style.display = allowed.has(key) ? '' : 'none';
  });
}

/**
 * initNav() — 모든 페이지에서 호출.
 * 1. 로그인 확인
 * 2. /auth/me 로 역할·권한 조회 후 nav 업데이트
 */
async function initNav() {
  if (!getToken()) { location.href = '/login.html'; return; }
  const navUser = document.getElementById('navUser');
  if (navUser) navUser.textContent = getNickname() || '';

  try {
    const me = await getMe();
    setRole(me.role || 'user');

    // admin 전용 항목 표시
    document.querySelectorAll('[data-role="admin"]').forEach(function(el) {
      el.style.display = me.role === 'admin' ? '' : 'none';
    });

    // 권한 기반 메뉴 숨김 (서버 DB 기준)
    try {
      const perm = await apiFetch('/permissions/roles');
      const myRole = me.role || 'user';
      const allowed = (perm.roles || {})[myRole] || [];
      applyNavPermissions(allowed);
    } catch (e) {
      // 권한 API 실패 시 무시 (admin 전용 엔드포인트라 user는 403)
      // user는 기본 허용 목록 적용
      const defaultAllowed = ['home', 'settings', 'sector', 'research', 'analysis', 'notify'];
      if (me.role === 'admin') {
        // admin은 모든 메뉴 표시
        document.querySelectorAll('[data-page]').forEach(function(el) {
          el.style.display = '';
        });
      } else {
        applyNavPermissions(defaultAllowed);
      }
    }
  } catch (e) {
    // getMe 실패 → 로그아웃 처리
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function requireAuth() {
  if (!getToken()) { location.href = '/login.html'; return false; }
  return true;
}

// ── 결과 표시 수 (localStorage) ───────────────────────────────────────────────
const DISPLAY_COUNT_KEY = 'scan_display_count';
const DISPLAY_COUNT_DEFAULT = 20;

function getDisplayCount() {
  const v = localStorage.getItem(DISPLAY_COUNT_KEY);
  return v ? parseInt(v, 10) : DISPLAY_COUNT_DEFAULT;
}

function setDisplayCount(n) {
  localStorage.setItem(DISPLAY_COUNT_KEY, String(n));
}

function fmt(n, digits = 0) {
  if (n == null) return '-';
  return Number(n).toLocaleString('ko-KR', { maximumFractionDigits: digits });
}

function fmtRsi(v) {
  if (v == null) return '-';
  const n = parseFloat(v).toFixed(1);
  if (v < 30) return `<span class="badge badge-red">${n}</span>`;
  if (v > 70) return `<span class="badge badge-blue">${n}</span>`;
  return n;
}

function fmtChgPct(v) {
  if (v == null) return '-';
  const sign = v > 0 ? '+' : '';
  const cls  = v > 0 ? 'chg-up' : v < 0 ? 'chg-dn' : 'chg-flat';
  return `<span class="${cls}">${sign}${v.toFixed(2)}%</span>`;
}

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

function latestTradingDay() {
  const d = new Date();
  // skip weekends
  while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
}
