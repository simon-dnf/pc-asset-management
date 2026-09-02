// SC-14 관리자 계정 관리 / SC-15 비밀번호 변경 (FR-01)

import { api } from '../api.js';
import { h, clear, dash, dateTime, formValues, setFieldError, clearFieldErrors } from '../util.js';
import { modal, toastOk, toastErr, confirmDialog, alertBox, emptyRow, textField } from '../ui.js';
import { go, state } from '../app.js';

// ---------------------------------------------------------------- 계정 관리
export async function renderAccounts() {
  const root = h('div', {});
  root.appendChild(h('div', { class: 'page-head' },
    h('h1', {}, '관리자 계정'),
    h('span', { class: 'sub' }, 'v1은 IT 관리자 단일 역할입니다. (권한 분리는 v3)'),
    h('div', { class: 'actions' },
      h('button', { class: 'btn primary', onClick: () => accountModal(load) }, '+ 계정 생성'))));

  const panel = h('div', { class: 'panel' });
  root.appendChild(panel);

  async function load() {
    clear(panel);
    panel.appendChild(h('div', { class: 'loading' }, h('span', { class: 'spinner' })));
    const data = await api.get('/accounts');
    clear(panel);
    panel.appendChild(h('div', { class: 'panel-head' }, h('h2', {}, `${data.items.length}개 계정`)));

    const rows = data.items.map(u => {
      const locked = u.locked_until && u.locked_until > nowStr();
      return h('tr', { class: u.is_active ? '' : 'row-skip' },
        h('td', { class: 'mono' }, u.username),
        h('td', {}, u.name, u.id === state.user.id ? h('span', { class: 'badge blue', style: 'margin-left:6px' }, '나') : null),
        h('td', {}, u.role),
        h('td', {}, u.is_active
          ? h('span', { class: 'badge green' }, '활성')
          : h('span', { class: 'badge gray' }, '비활성'),
          locked ? h('span', { class: 'badge red', style: 'margin-left:4px' }, '잠금') : null,
          u.must_change_pw ? h('span', { class: 'badge amber', style: 'margin-left:4px' }, '초기 비밀번호') : null),
        h('td', { class: 'muted nowrap' }, u.last_login_at ? dateTime(u.last_login_at) : '—'),
        h('td', { class: 'muted nowrap' }, dateTime(u.created_at)),
        h('td', { class: 'nowrap' }, h('div', { class: 'flex' },
          h('button', { class: 'btn sm', onClick: () => resetModal(u, load) }, '비밀번호 재설정'),
          locked ? h('button', { class: 'btn sm', onClick: () => unlock(u, load) }, '잠금 해제') : null,
          u.id === state.user.id ? null : h('button', { class: 'btn sm', onClick: () => toggle(u, load) },
            u.is_active ? '비활성화' : '활성화'))));
    });

    panel.appendChild(h('div', { class: 'table-wrap' },
      h('table', { class: 'grid-table' },
        h('thead', {}, h('tr', {},
          h('th', {}, '아이디'), h('th', {}, '이름'), h('th', {}, '역할'), h('th', {}, '상태'),
          h('th', {}, '최근 로그인'), h('th', {}, '생성일'), h('th', {}, ''))),
        h('tbody', {}, ...(rows.length ? rows : [emptyRow(7)])))));
  }

  await load();
  return root;
}

function nowStr() {
  const d = new Date(); const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function accountModal(onDone) {
  const form = h('form', { class: 'form-grid c2', onSubmit: e => e.preventDefault() },
    textField({ name: 'username', label: '아이디', required: true, hint: '영문/숫자' }),
    textField({ name: 'name', label: '이름', required: true }),
    h('div', { class: 'span2' },
      textField({ name: 'password', label: '초기 비밀번호', type: 'password', required: true,
        hint: '8자 이상, 영문+숫자 조합. 최초 로그인 시 변경하도록 안내됩니다.' })));

  modal({
    title: '관리자 계정 생성', size: 'wide', body: form,
    buttons: [
      { label: '취소' },
      { label: '생성', class: 'primary', onClick: async (close, foot) => {
        const btn = foot.querySelector('.btn.primary');
        clearFieldErrors(form);
        btn.disabled = true; btn.textContent = '생성 중…';
        try {
          await api.post('/accounts', formValues(form));
          close();
          toastOk('계정을 생성했습니다.');
          onDone();
        } catch (e) {
          if (!setFieldError(form, e.field, e.message)) toastErr(e.message);
          btn.disabled = false; btn.textContent = '생성';
        }
      } },
    ],
  });
}

function resetModal(u, onDone) {
  const form = h('form', { onSubmit: e => e.preventDefault() },
    textField({ name: 'new_password', label: '임시 비밀번호', type: 'password', required: true,
      hint: '8자 이상, 영문+숫자 조합' }));
  modal({
    title: `비밀번호 재설정 — ${u.name} (${u.username})`,
    body: h('div', {},
      alertBox('info', '메일 발송 없이 임시 비밀번호로 재설정합니다. 값을 대상자에게 직접 전달하세요.'),
      form),
    buttons: [
      { label: '취소' },
      { label: '재설정', class: 'primary', onClick: async (close, foot) => {
        const btn = foot.querySelector('.btn.primary');
        clearFieldErrors(form);
        btn.disabled = true; btn.textContent = '처리 중…';
        try {
          const r = await api.post(`/accounts/${u.id}/reset-password`, formValues(form));
          close();
          toastOk(r.message);
          onDone();
        } catch (e) {
          if (!setFieldError(form, e.field, e.message)) toastErr(e.message);
          btn.disabled = false; btn.textContent = '재설정';
        }
      } },
    ],
  });
}

async function toggle(u, onDone) {
  const active = !u.is_active;
  const ok = await confirmDialog(
    `${u.name}(${u.username}) 계정을 ${active ? '활성화' : '비활성화'}합니다.` +
    (active ? '' : '\n비활성화하면 즉시 로그아웃되고 로그인할 수 없습니다.'),
    { title: '계정 상태 변경', okLabel: active ? '활성화' : '비활성화', danger: !active });
  if (!ok) return;
  try {
    await api.post(`/accounts/${u.id}/active?active=${active}`);
    toastOk('처리했습니다.');
    onDone();
  } catch (e) { toastErr(e.message); }
}

async function unlock(u, onDone) {
  try {
    await api.post(`/accounts/${u.id}/unlock`);
    toastOk('잠금을 해제했습니다.');
    onDone();
  } catch (e) { toastErr(e.message); }
}

// ---------------------------------------------------------------- 비밀번호 변경
export async function renderPassword() {
  const root = h('div', {});
  root.appendChild(h('div', { class: 'page-head' }, h('h1', {}, '비밀번호 변경')));

  const form = h('form', { onSubmit: submit },
    textField({ name: 'current_password', label: '현재 비밀번호', type: 'password', required: true }),
    textField({ name: 'new_password', label: '새 비밀번호', type: 'password', required: true,
      hint: '8자 이상, 영문과 숫자를 모두 포함' }),
    textField({ name: 'confirm', label: '새 비밀번호 확인', type: 'password', required: true }),
    h('div', { class: 'btn-row mt16' },
      h('button', { class: 'btn primary', type: 'submit' }, '변경'),
      h('button', { class: 'btn ghost', type: 'button', onClick: () => go('/dashboard') }, '취소')));

  async function submit(e) {
    e.preventDefault();
    clearFieldErrors(form);
    const v = formValues(form);
    if (v.new_password !== v.confirm) {
      setFieldError(form, 'confirm', '새 비밀번호가 일치하지 않습니다.');
      return;
    }
    const btn = form.querySelector('button[type=submit]');
    btn.disabled = true; btn.textContent = '변경 중…';
    try {
      const r = await api.post('/me/password', {
        current_password: v.current_password, new_password: v.new_password,
      });
      state.user = null;
      toastOk(r.message);
      location.hash = '';
      location.reload();
    } catch (ex) {
      if (!setFieldError(form, ex.field, ex.message)) toastErr(ex.message);
      btn.disabled = false; btn.textContent = '변경';
    }
  }

  root.appendChild(h('div', { class: 'panel', style: 'max-width:520px' },
    h('div', { class: 'panel-body' },
      state.user && state.user.must_change_pw
        ? alertBox('warn', '초기 비밀번호를 사용 중입니다. 새 비밀번호로 변경해 주세요.')
        : null,
      form,
      h('p', { class: 'muted small mt16' }, '비밀번호를 변경하면 모든 세션이 종료되어 다시 로그인해야 합니다.'))));
  return root;
}
