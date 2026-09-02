// SC-07/08/09 배정·회수·상태변경 모달 (FR-08, FR-09, FR-12) — 목록과 상세에서 공용으로 쓴다.

import { api } from '../api.js';
import { h, today, formValues, clear } from '../util.js';
import { modal, toastOk, toastErr, toastWarn, selectField, textField, textareaField,
         employeeAutocomplete, alertBox } from '../ui.js';
import { labelsOf } from '../app.js';

function submitWrap(btnLabel, onSubmit) {
  return { label: btnLabel, class: 'primary', onClick: (close, foot) => onSubmit(close, foot) };
}

async function run(btnEl, fn) {
  const orig = btnEl.textContent;
  btnEl.disabled = true;
  btnEl.textContent = '처리 중…';
  try { return await fn(); }
  finally { btnEl.disabled = false; btnEl.textContent = orig; }
}

// ---------------------------------------------------------------- 배정 (FR-08)
export function assignModal({ asset = null, ids = null, onDone }) {
  const bulk = Array.isArray(ids);
  const empField = employeeAutocomplete({ name: 'emp_no', label: '사번', required: true, onPick });
  const nameField  = textField({ name: 'user_name', label: '사용자명', required: true, placeholder: '자동 입력' });
  const deptField  = selectField({ name: 'dept_code', label: '소속부서', options: labelsOf('DEPT') });
  const posField   = selectField({ name: 'position_code', label: '직급', options: labelsOf('POSITION') });
  const siteField  = selectField({ name: 'site', label: '사업장', required: true,
    options: labelsOf('SITE'), value: asset ? asset.site : '' });
  const locField   = textField({ name: 'location', label: '위치', value: asset ? asset.location : '',
    placeholder: '예: A동 3층' });
  const issueField = textField({ name: 'issue_date', label: '지급일', type: 'date', value: today(), required: true });
  const dueField   = textField({ name: 'due_return_date', label: '반납예정일', type: 'date',
    hint: '임대·임시 배정 시 입력' });
  const reasonField = textareaField({ name: 'reason', label: '배정 사유', rows: 2,
    placeholder: '예: 신규 입사자 배정', maxlength: 200 });
  const notice = h('div', {});

  function onPick(emp) {
    nameField.querySelector('input').value = emp.name || '';
    if (emp.dept_code) deptField.querySelector('select').value = emp.dept_code;
    if (emp.position_code) posField.querySelector('select').value = emp.position_code;
    if (emp.site_code && !asset) siteField.querySelector('select').value = emp.site_code;
    clear(notice);
    if (emp.employ_status !== '재직') {
      notice.appendChild(alertBox('warn', `${emp.name}님은 '${emp.employ_status}' 상태입니다.`));
    }
  }

  const form = h('form', { class: 'form-grid c2', onSubmit: (e) => e.preventDefault() },
    h('div', { class: 'span2' }, notice),
    empField, nameField, deptField, posField, siteField, locField,
    issueField, dueField,
    h('div', { class: 'span2' }, reasonField));

  const info = bulk
    ? alertBox('info', `선택한 ${ids.length}건을 같은 사용자에게 일괄 배정합니다.`)
    : h('p', { class: 'muted small mb16' },
        `${asset.asset_no} · ${asset.manufacturer} ${asset.model_name}`);

  const m = modal({
    title: bulk ? '자산 일괄 배정' : '자산 배정',
    size: 'wide',
    body: h('div', {}, info, form),
    buttons: [
      { label: '취소' },
      submitWrap('배정', async (close, foot) => {
        const btn = foot.querySelector('.btn.primary');
        const v = formValues(form);
        try {
          const res = await run(btn, () => bulk
            ? api.post('/assets/bulk/assign', { ids, payload: v })
            : api.post(`/assets/${asset.id}/assign`, v));
          if (bulk) {
            close();
            reportBulk(res, '배정');
          } else {
            close();
            toastOk('배정 처리되었습니다.');
            (res.warnings || []).forEach(w => toastWarn(w));
          }
          onDone && onDone();
        } catch (e) { toastErr(e.message); }
      }),
    ],
  });
  return m;
}

// ---------------------------------------------------------------- 회수 (FR-09)
export function returnModal({ asset = null, ids = null, onDone }) {
  const bulk = Array.isArray(ids);
  const form = h('form', { class: 'form-grid c2', onSubmit: (e) => e.preventDefault() },
    textField({ name: 'return_date', label: '회수일', type: 'date', value: today(), required: true }),
    selectField({ name: 'return_reason', label: '회수 사유', required: true,
      options: labelsOf('RETURN_REASON') }),
    selectField({ name: 'after_status', label: '회수 후 상태', required: true,
      options: ['대기', '수리', '폐기예정'], value: '대기', placeholder: '' }),
    h('div', {}),
    h('div', { class: 'span2' },
      textareaField({ name: 'remark', label: '비고', rows: 2, maxlength: 200 })));

  const info = bulk
    ? alertBox('info', `선택한 ${ids.length}건을 일괄 회수합니다. (퇴사자 일괄 처리 등)`)
    : h('p', { class: 'muted small mb16' },
        `${asset.asset_no} · 현재 사용자 ${asset.assignment ? asset.assignment.user_name : '—'}`);

  modal({
    title: bulk ? '자산 일괄 회수' : '자산 회수',
    size: 'wide',
    body: h('div', {}, info, form),
    buttons: [
      { label: '취소' },
      submitWrap('회수', async (close, foot) => {
        const btn = foot.querySelector('.btn.primary');
        const v = formValues(form);
        try {
          const res = await run(btn, () => bulk
            ? api.post('/assets/bulk/return', { ids, payload: v })
            : api.post(`/assets/${asset.id}/return`, v));
          close();
          if (bulk) reportBulk(res, '회수');
          else toastOk('회수 처리되었습니다.');
          onDone && onDone();
        } catch (e) { toastErr(e.message); }
      }),
    ],
  });
}

// ---------------------------------------------------------------- 상태 변경 (FR-12)
export function statusModal({ asset = null, ids = null, allowed = null, onDone }) {
  const bulk = Array.isArray(ids);
  const options = allowed || labelsOf('STATUS');
  const disposalWrap = h('div', { class: 'span2 hidden' },
    h('div', { class: 'form-grid c2' },
      textField({ name: 'disposal_date', label: '폐기일', type: 'date', value: today(), required: true }),
      selectField({ name: 'disposal_method', label: '폐기방법', required: true,
        options: labelsOf('DISPOSAL_METHOD') })));

  const statusSel = selectField({
    name: 'status', label: '변경할 상태', required: true, options,
    onChange: (e) => disposalWrap.classList.toggle('hidden', e.target.value !== '폐기'),
  });

  const form = h('form', { class: 'form-grid c2', onSubmit: (e) => e.preventDefault() },
    statusSel,
    h('div', {}),
    disposalWrap,
    h('div', { class: 'span2' },
      textareaField({ name: 'reason', label: '변경 사유', required: true, rows: 2, maxlength: 200,
        placeholder: '예: 2026년 상반기 노후 장비 교체' })));

  const info = bulk
    ? alertBox('info', `선택한 ${ids.length}건의 상태를 일괄 변경합니다. 전환 규칙에 맞지 않는 자산은 건너뜁니다.`)
    : h('p', { class: 'muted small mb16' }, `${asset.asset_no} · 현재 상태 ${asset.status}`);

  modal({
    title: bulk ? '일괄 상태 변경' : '상태 변경',
    size: 'wide',
    body: h('div', {}, info, form),
    buttons: [
      { label: '취소' },
      submitWrap('변경', async (close, foot) => {
        const btn = foot.querySelector('.btn.primary');
        const v = formValues(form);
        if (!v.status) { toastErr('변경할 상태를 선택하세요.'); return; }
        if (!v.reason) { toastErr('변경 사유를 입력하세요.'); return; }
        try {
          const res = await run(btn, () => bulk
            ? api.post('/assets/bulk/status', { ids, payload: v })
            : api.post(`/assets/${asset.id}/status`, v));
          close();
          if (bulk) reportBulk(res, '상태 변경');
          else toastOk('상태가 변경되었습니다.');
          onDone && onDone();
        } catch (e) { toastErr(e.message); }
      }),
    ],
  });
}

// ---------------------------------------------------------------- 일괄 결과 안내
function reportBulk(res, label) {
  if (res.success) toastOk(`${res.success}건 ${label} 처리되었습니다.`);
  if (res.failed && res.failed.length) {
    const lines = res.failed.slice(0, 8).map(f => `${f.asset_no}: ${f.error}`);
    modal({
      title: `${label} 실패 ${res.failed.length}건`,
      body: h('div', {},
        h('p', { class: 'muted small' }, `성공 ${res.success}건 / 실패 ${res.failed.length}건`),
        h('ul', {}, ...res.failed.map(f => h('li', {},
          h('strong', { class: 'mono' }, f.asset_no), ' — ', f.error)))),
      buttons: [{ label: '닫기', class: 'primary' }],
    });
  }
}
