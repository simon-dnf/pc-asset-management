// 공용 UI 컴포넌트: 토스트, 모달, 확인창, 페이저, 자동완성, 셀렉트

import { $, clear, h, debounce } from './util.js';
import { api } from './api.js';

// ---------------------------------------------------------------- 토스트
export function toast(message, { type = 'ok', title = '', timeout = 3800 } = {}) {
  const root = $('#toast-root');
  const el = h('div', { class: `toast ${type}` },
    title ? h('div', { class: 't' }, title) : null,
    h('div', { class: 'd' }, message));
  root.appendChild(el);
  const kill = () => { el.style.opacity = '0'; setTimeout(() => el.remove(), 200); };
  el.addEventListener('click', kill);
  setTimeout(kill, timeout);
}

export const toastOk    = (m, t) => toast(m, { type: 'ok', title: t });
export const toastErr   = (m, t = '오류') => toast(m, { type: 'error', title: t, timeout: 6500 });
export const toastWarn  = (m, t = '확인 필요') => toast(m, { type: 'warn', title: t, timeout: 6500 });

// ---------------------------------------------------------------- 모달
let openModals = 0;

export function modal({ title, body, buttons = [], size = '', onClose }) {
  const root = $('#modal-root');
  const backdrop = h('div', { class: 'modal-backdrop' });
  const box = h('div', { class: `modal ${size}` });

  const close = (result) => {
    backdrop.remove();
    openModals = Math.max(0, openModals - 1);
    document.removeEventListener('keydown', onKey);
    if (onClose) onClose(result);
  };
  const onKey = (e) => { if (e.key === 'Escape' && openModals) close(null); };

  box.appendChild(h('div', { class: 'modal-head' },
    h('h3', {}, title),
    h('button', { class: 'x', type: 'button', title: '닫기', onClick: () => close(null) }, '×')));

  const bodyEl = h('div', { class: 'modal-body' });
  if (body instanceof Node) bodyEl.appendChild(body);
  else bodyEl.innerHTML = body || '';
  box.appendChild(bodyEl);

  if (buttons.length) {
    const foot = h('div', { class: 'modal-foot' });
    for (const b of buttons) {
      foot.appendChild(h('button', {
        class: `btn ${b.class || ''}`, type: 'button',
        onClick: () => b.onClick ? b.onClick(close, foot) : close(b.value),
      }, b.label));
    }
    box.appendChild(foot);
  }

  backdrop.appendChild(box);
  backdrop.addEventListener('mousedown', (e) => { if (e.target === backdrop) close(null); });
  document.addEventListener('keydown', onKey);
  root.appendChild(backdrop);
  openModals++;

  const focusable = box.querySelector('input, select, textarea, button.btn');
  if (focusable) setTimeout(() => focusable.focus(), 40);
  return { close, body: bodyEl, root: box };
}

export function confirmDialog(message, { title = '확인', okLabel = '확인', danger = false } = {}) {
  return new Promise((resolve) => {
    let done = false;
    const m = modal({
      title,
      body: h('div', { style: 'white-space:pre-line' }, message),
      buttons: [
        { label: '취소', onClick: (close) => { done = true; close(); resolve(false); } },
        { label: okLabel, class: danger ? 'danger' : 'primary',
          onClick: (close) => { done = true; close(); resolve(true); } },
      ],
      onClose: () => { if (!done) resolve(false); },
    });
    return m;
  });
}

/** 사유 입력을 요구하는 확인창 (FR-04-3, FR-12-2) */
export function reasonDialog({ title, label = '사유', placeholder = '', okLabel = '확인', extra = null, maxlength = 200 }) {
  return new Promise((resolve) => {
    const ta = h('textarea', { name: 'reason', rows: 3, placeholder, maxlength });
    const errEl = h('div', { class: 'err hidden' });
    const body = h('div', {},
      extra,
      h('div', { class: 'field' },
        h('label', {}, label, h('span', { class: 'req' }, '*')),
        ta, errEl));
    let done = false;
    modal({
      title, body,
      buttons: [
        { label: '취소', onClick: (close) => { done = true; close(); resolve(null); } },
        { label: okLabel, class: 'primary', onClick: (close) => {
          const v = ta.value.trim();
          if (!v) { errEl.textContent = `${label}를 입력하세요.`; errEl.classList.remove('hidden'); ta.focus(); return; }
          done = true; close(); resolve(v);
        } },
      ],
      onClose: () => { if (!done) resolve(null); },
    });
  });
}

// ---------------------------------------------------------------- 페이저
export function pager({ total, page, size, onPage, onSize }) {
  const pages = Math.max(1, Math.ceil(total / size));
  const from = total === 0 ? 0 : (page - 1) * size + 1;
  const to = Math.min(total, page * size);

  const wrap = h('div', { class: 'pager' },
    h('div', { class: 'info' }, `총 ${total.toLocaleString('ko-KR')}건 중 ${from.toLocaleString('ko-KR')}–${to.toLocaleString('ko-KR')}`),
    h('select', {
      title: '페이지당 건수',
      onChange: (e) => onSize(Number(e.target.value)),
    }, ...[20, 50, 100].map(n => h('option', { value: n, selected: n === size }, `${n}건씩`))));

  const right = h('div', { class: 'right' });
  const btn = (label, target, opts = {}) => h('button', {
    type: 'button', class: opts.on ? 'on' : '', disabled: opts.disabled || false,
    onClick: () => onPage(target),
  }, label);

  right.appendChild(btn('«', 1, { disabled: page <= 1 }));
  right.appendChild(btn('‹', page - 1, { disabled: page <= 1 }));

  const win = 5;
  let start = Math.max(1, page - Math.floor(win / 2));
  let end = Math.min(pages, start + win - 1);
  start = Math.max(1, end - win + 1);
  for (let p = start; p <= end; p++) right.appendChild(btn(String(p), p, { on: p === page }));

  right.appendChild(btn('›', page + 1, { disabled: page >= pages }));
  right.appendChild(btn('»', pages, { disabled: page >= pages }));
  wrap.appendChild(right);
  return wrap;
}

// ---------------------------------------------------------------- 셀렉트
export function selectField({ name, label, options, value, required, placeholder = '선택', onChange, disabled }) {
  const sel = h('select', { name, required, disabled, onChange: onChange || null },
    h('option', { value: '' }, placeholder),
    ...options.map(o => {
      const v = typeof o === 'string' ? o : o.value;
      const t = typeof o === 'string' ? o : o.label;
      return h('option', { value: v, selected: String(value ?? '') === String(v) }, t);
    }));
  if (!label) return sel;
  return h('div', { class: 'field' },
    h('label', {}, label, required ? h('span', { class: 'req' }, '*') : null), sel);
}

export function textField({ name, label, value, required, type = 'text', placeholder, hint, disabled, maxlength, min, max, readonly }) {
  const input = h('input', {
    type, name, value: value ?? '', required, placeholder, disabled, maxlength, min, max, readonly,
  });
  return h('div', { class: 'field' },
    label ? h('label', {}, label, required ? h('span', { class: 'req' }, '*') : null) : null,
    input,
    hint ? h('div', { class: 'hint' }, hint) : null);
}

export function textareaField({ name, label, value, required, rows = 3, placeholder, maxlength, hint }) {
  return h('div', { class: 'field' },
    label ? h('label', {}, label, required ? h('span', { class: 'req' }, '*') : null) : null,
    h('textarea', { name, rows, placeholder, maxlength }, value ?? ''),
    hint ? h('div', { class: 'hint' }, hint) : null);
}

// ---------------------------------------------------------------- 임직원 자동완성 (FR-08 08-3)
export function employeeAutocomplete({ name = 'emp_no', label = '사번', value = '', required, onPick }) {
  const input = h('input', { type: 'text', name, value, autocomplete: 'off',
    placeholder: '사번 또는 이름으로 검색' });
  const list = h('div', { class: 'ac-list hidden' });
  const wrap = h('div', { class: 'autocomplete' }, input, list);
  let items = [];
  let cursor = -1;

  const hide = () => { list.classList.add('hidden'); cursor = -1; };
  const pick = (emp) => {
    input.value = emp.emp_no;
    hide();
    if (onPick) onPick(emp);
  };

  const render = () => {
    clear(list);
    if (!items.length) { hide(); return; }
    items.forEach((e, i) => {
      list.appendChild(h('div', {
        class: 'ac-item' + (i === cursor ? ' on' : ''),
        onMousedown: (ev) => { ev.preventDefault(); pick(e); },
      },
        h('span', { class: 'no' }, e.emp_no),
        h('strong', {}, e.name),
        e.employ_status !== '재직' ? h('span', { class: 'badge red' }, e.employ_status) : null,
        h('span', { class: 'dept' }, e.dept_label || e.dept_code || '')));
    });
    list.classList.remove('hidden');
  };

  const search = debounce(async (q) => {
    if (!q || q.length < 1) { items = []; hide(); return; }
    try {
      const res = await api.get(`/employees/suggest?q=${encodeURIComponent(q)}`);
      items = res.items; cursor = -1; render();
    } catch { /* 자동완성 실패는 조용히 무시 */ }
  }, 220);

  input.addEventListener('input', () => search(input.value.trim()));
  input.addEventListener('focus', () => { if (input.value.trim()) search(input.value.trim()); });
  input.addEventListener('blur', () => setTimeout(hide, 120));
  input.addEventListener('keydown', (e) => {
    if (list.classList.contains('hidden')) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); cursor = Math.min(items.length - 1, cursor + 1); render(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); cursor = Math.max(0, cursor - 1); render(); }
    else if (e.key === 'Enter' && cursor >= 0) { e.preventDefault(); pick(items[cursor]); }
    else if (e.key === 'Escape') hide();
  });

  const field = h('div', { class: 'field' },
    h('label', {}, label, required ? h('span', { class: 'req' }, '*') : null), wrap);
  field.inputEl = input;
  return field;
}

// ---------------------------------------------------------------- 기타
export function loading(text = '불러오는 중…') {
  return h('div', { class: 'loading' }, h('span', { class: 'spinner' }), ' ', text);
}

export function emptyRow(colspan, text = '데이터가 없습니다.') {
  return h('tr', {}, h('td', { colspan, class: 'empty' }, text));
}

export function alertBox(type, title, lines = []) {
  return h('div', { class: `alert ${type}` },
    h('strong', {}, title),
    lines.length ? h('ul', {}, ...lines.map(l => h('li', {}, l))) : null);
}

// ---------------------------------------------------------------- 복수 선택 필드 (05-2, 05-4)
/** 체크박스 목록. 같은 필터 안에서 여러 값을 고르면 OR로 동작한다.
 *  반환 요소의 `values()`로 선택값 배열을 얻는다. */
export function multiSelectField({ label, options, values = [], hint }) {
  const chosen = new Set(values.filter(Boolean));
  const box = h('div', {
    class: 'multi-select',
    role: 'group', 'aria-label': label,
  });

  const countEl = h('span', { class: 'muted small' });
  const paintCount = () => {
    countEl.textContent = chosen.size ? `${chosen.size}개 선택` : '전체';
  };

  for (const o of options) {
    const v = typeof o === 'string' ? o : o.value;
    const t = typeof o === 'string' ? o : o.label;
    box.appendChild(h('label', { class: 'check' },
      h('input', {
        type: 'checkbox', value: v, checked: chosen.has(v),
        onChange: (e) => {
          e.target.checked ? chosen.add(v) : chosen.delete(v);
          paintCount();
        },
      }), t));
  }
  paintCount();

  const field = h('div', { class: 'field' },
    h('div', { class: 'flex', style: 'margin-bottom:4px' },
      h('label', { style: 'margin:0' }, label),
      h('div', { class: 'spacer' }),
      countEl,
      h('button', {
        type: 'button', class: 'btn ghost sm', onClick: () => {
          chosen.clear();
          box.querySelectorAll('input').forEach(i => { i.checked = false; });
          paintCount();
        },
      }, '해제')),
    box,
    hint ? h('div', { class: 'hint' }, hint) : null);

  field.values = () => [...chosen];
  return field;
}
