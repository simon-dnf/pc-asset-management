// DOM / 포맷 유틸리티

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k === 'text') el.textContent = v;
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  for (const c of children.flat(9)) {
    if (c === null || c === undefined || c === false) continue;
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export const $  = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export const dash = (v) => (v === null || v === undefined || v === '') ? '—' : v;

export function num(v) {
  if (v === null || v === undefined || v === '') return '—';
  return Number(v).toLocaleString('ko-KR');
}

export function money(v) {
  if (v === null || v === undefined || v === '') return '—';
  return Number(v).toLocaleString('ko-KR') + '원';
}

export function dateOnly(v) {
  if (!v) return '—';
  return String(v).slice(0, 10);
}

export function dateTime(v) {
  if (!v) return '—';
  return String(v).slice(0, 16);
}

/** 오늘 날짜 (YYYY-MM-DD, 로컬) */
export function today() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export function daysBetween(a, b) {
  if (!a || !b) return null;
  return Math.round((new Date(b) - new Date(a)) / 86400000);
}

export function statusBadge(status) {
  return h('span', { class: `badge st-${status}` }, status);
}

export function debounce(fn, ms = 250) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

/** 객체 → 쿼리스트링 (빈 값 제외, 배열은 콤마 결합) */
export function qs(params) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v === null || v === undefined || v === '' || v === false) continue;
    if (Array.isArray(v)) { if (v.length) p.set(k, v.join(',')); }
    else p.set(k, v);
  }
  const s = p.toString();
  return s ? '?' + s : '';
}

export function parseQs(str) {
  const out = {};
  const p = new URLSearchParams(str || '');
  for (const [k, v] of p.entries()) out[k] = v;
  return out;
}

/** 폼 요소 값을 name 기준으로 모은다. */
export function formValues(form) {
  const out = {};
  for (const el of form.elements) {
    if (!el.name || el.disabled) continue;
    if (el.type === 'checkbox') out[el.name] = el.checked;
    else out[el.name] = el.value === '' ? null : el.value;
  }
  return out;
}

export function setFieldError(form, field, message) {
  clearFieldErrors(form);
  if (!field) return false;
  const el = form.querySelector(`[name="${CSS.escape(field)}"]`);
  if (!el) return false;
  const wrap = el.closest('.field');
  if (!wrap) return false;
  wrap.classList.add('has-error');
  wrap.appendChild(h('div', { class: 'err' }, message));
  el.focus();
  return true;
}

export function clearFieldErrors(form) {
  $$('.field.has-error', form).forEach(f => f.classList.remove('has-error'));
  $$('.field .err', form).forEach(e => e.remove());
}
