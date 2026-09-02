// 앱 진입점 — 세션 확인, 상단 네비게이션, 해시 라우팅

import { api, setUnauthorizedHandler } from './api.js';
import { $, clear, h, parseQs } from './util.js';
import { toastErr } from './ui.js';
import { loadPrefs, clearPrefs } from './prefs.js';

import { renderLogin } from './pages/login.js';
import { renderDashboard } from './pages/dashboard.js';
import { renderAssetList } from './pages/assets.js';
import { renderAssetForm } from './pages/assetForm.js';
import { renderAssetDetail } from './pages/assetDetail.js';
import { renderImport } from './pages/importer.js';
import { renderHistory } from './pages/history.js';
import { renderEmployees, renderEmployeeDetail } from './pages/employees.js';
import { renderCodes } from './pages/codes.js';
import { renderEol } from './pages/eol.js';
import { renderAccounts, renderPassword } from './pages/accounts.js';

export const state = {
  user: null,
  codes: null,      // 공통코드 옵션 캐시
};

/** 공통코드 옵션 (셀렉트 박스용). 코드 관리 화면에서 변경하면 무효화한다. */
export async function codes(force = false) {
  if (!state.codes || force) state.codes = await api.get('/codes/options');
  return state.codes;
}
export function invalidateCodes() { state.codes = null; }

export function labelsOf(group) {
  return ((state.codes && state.codes[group]) || []).map(c => c.label);
}

// ---------------------------------------------------------------- 라우팅
const ROUTES = [
  [/^\/dashboard$/,               (m, q) => renderDashboard(q)],
  [/^\/assets$/,                  (m, q) => renderAssetList(q)],
  [/^\/assets\/new$/,             (m, q) => renderAssetForm(null, q)],
  [/^\/assets\/(\d+)$/,           (m, q) => renderAssetDetail(Number(m[1]), q)],
  [/^\/assets\/(\d+)\/edit$/,     (m, q) => renderAssetForm(Number(m[1]), q)],
  [/^\/import$/,                  (m, q) => renderImport(q)],
  [/^\/history$/,                 (m, q) => renderHistory(q)],
  [/^\/employees$/,               (m, q) => renderEmployees(q)],
  [/^\/employees\/([^/]+)$/,      (m, q) => renderEmployeeDetail(decodeURIComponent(m[1]), q)],
  [/^\/codes$/,                   (m, q) => renderCodes(q)],
  [/^\/eol$/,                     (m, q) => renderEol(q)],
  [/^\/accounts$/,                (m, q) => renderAccounts(q)],
  [/^\/password$/,                (m, q) => renderPassword(q)],
];

export function go(path, { replace = false } = {}) {
  const target = '#' + path;
  if (location.hash === target) { route(); return; }
  if (replace) location.replace(target); else location.hash = target;
}

function currentRoute() {
  const raw = location.hash.replace(/^#/, '') || '/dashboard';
  const [path, query] = raw.split('?');
  return { path: path || '/dashboard', query: parseQs(query) };
}

async function route() {
  const { path, query } = currentRoute();

  if (!state.user) {
    renderShellless(renderLogin());
    return;
  }
  if (path === '/login') { go('/dashboard', { replace: true }); return; }

  renderShell(path);
  const view = $('#view');
  for (const [re, handler] of ROUTES) {
    const m = re.exec(path);
    if (m) {
      try {
        const node = await handler(m, query);
        clear(view);
        if (node) view.appendChild(node);
      } catch (e) {
        clear(view);
        view.appendChild(h('div', { class: 'panel' },
          h('div', { class: 'panel-body' },
            h('div', { class: 'alert error' }, e.message || '화면을 불러오지 못했습니다.'))));
      }
      return;
    }
  }
  clear(view);
  view.appendChild(h('div', { class: 'panel' },
    h('div', { class: 'empty' }, '요청한 화면을 찾을 수 없습니다.')));
}

// ---------------------------------------------------------------- 셸
function renderShellless(node) {
  const app = clear($('#app'));
  app.appendChild(node);
}

const NAV = [
  { path: '/dashboard', label: '대시보드' },
  { label: '자산관리', children: [
    { path: '/assets', label: '자산 목록' },
    { path: '/assets/new', label: '자산 등록' },
    { path: '/import', label: '엑셀 가져오기' },
  ] },
  { path: '/employees', label: '임직원' },
  { path: '/history', label: '이력' },
  { label: '설정', children: [
    { path: '/codes', label: '공통코드' },
    { path: '/eol', label: 'OS 지원종료 관리' },
    { path: '/accounts', label: '계정 관리' },
  ] },
];

function navItem(item, activePath) {
  if (!item.children) {
    const on = activePath === item.path || (item.path === '/assets' && /^\/assets\/\d+/.test(activePath));
    return h('div', { class: 'nav-item' + (on ? ' active' : '') },
      h('a', { href: '#' + item.path }, item.label));
  }
  const on = item.children.some(c => activePath.startsWith(c.path));
  const el = h('div', { class: 'nav-item' + (on ? ' active' : '') },
    h('button', { type: 'button' }, item.label, h('span', { class: 'small' }, '▾')),
    h('div', { class: 'dropdown' }, ...item.children.map(c =>
      h('a', { href: '#' + c.path }, c.label))));
  el.querySelector('button').addEventListener('click', (e) => {
    e.stopPropagation();
    const wasOpen = el.classList.contains('open');
    document.querySelectorAll('.nav-item.open').forEach(n => n.classList.remove('open'));
    if (!wasOpen) el.classList.add('open');
  });
  el.querySelectorAll('.dropdown a').forEach(a =>
    a.addEventListener('click', () => el.classList.remove('open')));
  return el;
}

function renderShell(activePath) {
  const app = $('#app');
  if (!app.querySelector('.shell')) {
    clear(app);
    app.appendChild(h('div', { class: 'shell' },
      h('header', { class: 'topbar' },
        h('a', { class: 'brand', href: '#/dashboard' },
          h('span', { class: 'mark' }, 'PC'), 'PC 자산관리 시스템'),
        h('nav', { class: 'nav', id: 'nav' }),
        h('div', { class: 'nav-item', id: 'user-menu' })),
      h('main', { class: 'main', id: 'view' })));
    document.addEventListener('click', () => {
      document.querySelectorAll('.nav-item.open').forEach(n => n.classList.remove('open'));
    });
  }

  const nav = clear($('#nav'));
  NAV.forEach(item => nav.appendChild(navItem(item, activePath)));

  const um = clear($('#user-menu'));
  um.className = 'nav-item';
  um.appendChild(h('button', { type: 'button' }, state.user.name, h('span', { class: 'small' }, '▾')));
  const dd = h('div', { class: 'dropdown', style: 'right:0;left:auto' },
    h('a', { href: '#/password' }, '비밀번호 변경'),
    h('a', { href: '#', onClick: async (e) => {
      e.preventDefault();
      try { await api.post('/logout'); } catch { /* 이미 만료된 세션 */ }
      state.user = null;
      clearPrefs();
      location.hash = '';
      route();
    } }, '로그아웃'));
  um.appendChild(dd);
  um.querySelector('button').addEventListener('click', (e) => {
    e.stopPropagation();
    const wasOpen = um.classList.contains('open');
    document.querySelectorAll('.nav-item.open').forEach(n => n.classList.remove('open'));
    if (!wasOpen) um.classList.add('open');
  });
}

// ---------------------------------------------------------------- 부팅
export async function afterLogin(user) {
  state.user = user;
  await Promise.all([codes(true), loadPrefs()]);
  if (user.must_change_pw) {
    go('/password');
    setTimeout(() => toastErr('초기 비밀번호를 사용 중입니다. 새 비밀번호로 변경해 주세요.', '비밀번호 변경 필요'), 300);
    return;
  }
  const hash = location.hash.replace(/^#/, '');
  go(hash && hash !== '/login' ? hash : '/dashboard', { replace: true });
}

setUnauthorizedHandler(() => {
  state.user = null;
  clearPrefs();
  clear($('#modal-root'));
  route();
});

window.addEventListener('hashchange', route);

(async function boot() {
  try {
    const res = await api.get('/me');
    state.user = res.user;
    await Promise.all([codes(true), loadPrefs()]);
  } catch {
    state.user = null;
  }
  route();
})();
