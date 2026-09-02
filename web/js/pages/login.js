// SC-01 로그인 (FR-01)

import { api } from '../api.js';
import { h, $ } from '../util.js';
import { afterLogin } from '../app.js';

export function renderLogin() {
  const err = h('div', { class: 'alert error hidden' });
  const idInput = h('input', { type: 'text', name: 'username', autocomplete: 'username',
    placeholder: '아이디', autofocus: true });
  const pwInput = h('input', { type: 'password', name: 'password', autocomplete: 'current-password',
    placeholder: '비밀번호' });
  const btn = h('button', { class: 'btn primary lg', type: 'submit', style: 'width:100%' }, '로그인');

  const form = h('form', { onSubmit: submit },
    err,
    h('div', { class: 'field' }, h('label', {}, '아이디'), idInput),
    h('div', { class: 'field' }, h('label', {}, '비밀번호'), pwInput),
    h('div', { class: 'mt16' }, btn));

  async function submit(e) {
    e.preventDefault();
    err.classList.add('hidden');
    btn.disabled = true;
    btn.textContent = '확인 중…';
    try {
      const res = await api.post('/login', {
        username: idInput.value.trim(),
        password: pwInput.value,
      });
      await afterLogin(res.user);
    } catch (ex) {
      err.textContent = ex.message;
      err.classList.remove('hidden');
      pwInput.value = '';
      pwInput.focus();
    } finally {
      btn.disabled = false;
      btn.textContent = '로그인';
    }
  }

  return h('div', { class: 'login-wrap' },
    h('div', { class: 'login-card' },
      h('div', { class: 'logo' },
        h('div', { class: 'mark' }, 'PC'),
        h('h1', {}, 'PC 자산관리 시스템'),
        h('p', {}, 'IT 관리자 전용')),
      form,
      h('p', { class: 'muted small mt16', style: 'text-align:center' },
        '사내 자산관리 전용 시스템입니다.')));
}
