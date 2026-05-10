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
