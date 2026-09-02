// SC-04 자산 등록 / SC-06 자산 수정 (FR-02, FR-04)

import { api } from '../api.js';
import { h, clear, today, formValues, setFieldError, clearFieldErrors, dash } from '../util.js';
import { modal, toastOk, toastErr, toastWarn, selectField, textField, textareaField,
         employeeAutocomplete, alertBox } from '../ui.js';
import { go, labelsOf } from '../app.js';

export async function renderAssetForm(assetId) {
  const editing = assetId !== null;
  const asset = editing ? await api.get(`/assets/${assetId}`) : null;

  if (editing && asset.status === '폐기') {
    return h('div', { class: 'panel' }, h('div', { class: 'panel-body' },
      alertBox('warn', '폐기 자산은 수정할 수 없습니다. (조회 전용)'),
      h('button', { class: 'btn', onClick: () => go(`/assets/${assetId}`) }, '상세로 돌아가기')));
  }

  const v = asset || {};
  const root = h('div', {});
  const warnBox = h('div', {});

  // ---------------- 기본정보
  const assetNoField = textField({
    name: 'asset_no', label: '자산번호', required: true, value: v.asset_no || '',
    disabled: editing, maxlength: 30,
    hint: editing ? '자산번호는 수정할 수 없습니다.' : '영문/숫자/하이픈 30자 이내. 중복 불가',
  });
  if (!editing) {
    const btn = h('button', { class: 'btn sm', type: 'button', onClick: async () => {
      try {
        const r = await api.get('/assets/next-no');
        assetNoField.querySelector('input').value = r.asset_no;
      } catch (e) { toastErr(e.message); }
    } }, '자동 채번');
    assetNoField.appendChild(h('div', { class: 'mt8' }, btn));
  }

  const basic = h('fieldset', { class: 'group' },
    h('legend', {}, '자산 기본정보'),
    h('div', { class: 'form-grid' },
      assetNoField,
      selectField({ name: 'asset_type', label: '자산구분', required: true, options: labelsOf('ASSET_TYPE'), value: v.asset_type }),
      selectField({ name: 'manufacturer', label: '제조사', required: true, options: labelsOf('MANUFACTURER'), value: v.manufacturer }),
      textField({ name: 'model_name', label: '모델명', required: true, value: v.model_name || '' }),
      textField({ name: 'serial_no', label: '시리얼번호 (S/N)', value: v.serial_no || '',
        hint: '실사·A/S 시 실물 식별 기준. 값이 있으면 중복 불가' }),
      textField({ name: 'purchase_date', label: '구매일', type: 'date', required: true,
        value: v.purchase_date || '', max: today() }),
      textField({ name: 'service_start_date', label: '사용시작일', type: 'date',
        value: v.service_start_date || '', hint: '미입력 시 구매일로 간주' }),
      textField({ name: 'purchase_amount', label: '취득금액(원)', type: 'number', value: v.purchase_amount ?? '', min: 0 }),
      textField({ name: 'useful_life_years', label: '내용연수(년)', type: 'number',
        value: v.useful_life_years ?? '', min: 1, max: 50, hint: '미입력 시 5년으로 간주' })));

  // ---------------- 배치·관리
  const ops = h('fieldset', { class: 'group' },
    h('legend', {}, '배치 · 운영관리'),
    h('div', { class: 'form-grid' },
      selectField({ name: 'site', label: '사업장', required: true, options: labelsOf('SITE'), value: v.site }),
      textField({ name: 'location', label: '위치', value: v.location || '', placeholder: '예: A동 3층',
        hint: '대기·공용 자산도 물리적 위치를 남깁니다.' }),
      textField({ name: 'manager_emp_no', label: '자산관리 담당자', required: true,
        value: v.manager_emp_no || '', hint: '이 자산을 관리하는 IT 담당자' })));

  // ---------------- 하드웨어
  const hw = h('fieldset', { class: 'group' },
    h('legend', {}, 'PC 하드웨어'),
    h('div', { class: 'form-grid' },
      textField({ name: 'hostname', label: 'Hostname', value: v.hostname || '',
        hint: '중복 시 경고만 표시하고 저장은 허용합니다.' }),
      textField({ name: 'ip_address', label: 'IP 주소', value: v.ip_address || '', placeholder: '10.20.3.41' }),
      selectField({ name: 'ip_type', label: 'IP 구분', options: ['고정', 'DHCP'], value: v.ip_type }),
      textField({ name: 'mac_address', label: 'MAC 주소', value: v.mac_address || '',
        placeholder: 'AC:DE:48:00:11:22', hint: '하이픈·콜론 모두 허용. 저장 시 대문자 콜론으로 정규화' }),
      textField({ name: 'cpu', label: 'CPU', value: v.cpu || '', placeholder: 'Intel i7-13700' }),
      textField({ name: 'ram_gb', label: 'RAM (GB)', type: 'number', value: v.ram_gb ?? '', min: 1, max: 1024 }),
      selectField({ name: 'disk_type', label: '디스크 유형', options: labelsOf('DISK_TYPE'), value: v.disk_type }),
      textField({ name: 'disk_gb', label: '디스크 용량 (GB)', type: 'number', value: v.disk_gb ?? '', min: 1, max: 100000 }),
      selectField({ name: 'os', label: '운영체제', options: labelsOf('OS'), value: v.os })));

  // ---------------- 등록 시 배정 (02-7)
  let assignBox = null;
  if (!editing) {
    const inner = h('div', { class: 'form-grid hidden' });
    const empField = employeeAutocomplete({ name: 'a_emp_no', label: '사번', onPick: (emp) => {
      inner.querySelector('[name=a_user_name]').value = emp.name || '';
      if (emp.dept_code) inner.querySelector('[name=a_dept_code]').value = emp.dept_code;
      if (emp.position_code) inner.querySelector('[name=a_position_code]').value = emp.position_code;
    } });
    inner.append(
      empField,
      textField({ name: 'a_user_name', label: '사용자명' }),
      selectField({ name: 'a_dept_code', label: '소속부서', options: labelsOf('DEPT') }),
      selectField({ name: 'a_position_code', label: '직급', options: labelsOf('POSITION') }),
      textField({ name: 'a_issue_date', label: '지급일', type: 'date', value: today() }),
      textField({ name: 'a_due_return_date', label: '반납예정일', type: 'date' }));

    const toggle = h('label', { class: 'check mb16' },
      h('input', { type: 'checkbox', onChange: (e) => inner.classList.toggle('hidden', !e.target.checked) }),
      '등록과 동시에 사용자에게 배정 (체크 시 상태가 ‘사용중’으로 설정됩니다)');

    assignBox = h('fieldset', { class: 'group' },
      h('legend', {}, '사용자 배정 (선택)'), toggle, inner);
  }

  const remark = h('fieldset', { class: 'group' },
    h('legend', {}, '기타'),
    textareaField({ name: 'remark', label: '비고', value: v.remark || '', rows: 3, maxlength: 1000 }),
    editing
      ? textareaField({ name: 'reason', label: '변경 사유', required: true, rows: 2, maxlength: 200,
          placeholder: '예: RAM 증설 (8GB → 16GB)' })
      : textareaField({ name: 'reason', label: '등록 사유', rows: 2, maxlength: 200,
          placeholder: '예: 2026년 상반기 신규 입고' }));

  const keepGoing = h('label', { class: 'check' },
    h('input', { type: 'checkbox' }), '저장 후 계속 등록 (공통 항목 유지)');

  const submitBtn = h('button', { class: 'btn primary lg', type: 'submit' },
    editing ? '변경 저장' : '자산 등록');

  const form = h('form', { onSubmit: onSubmit },
    warnBox, basic, ops, hw, assignBox, remark,
    h('div', { class: 'flex mt16' },
      submitBtn,
      editing
        ? h('button', { class: 'btn', type: 'button',
            onClick: () => previewChanges().catch(ex => toastErr(ex.message)) }, '변경 내용 확인')
        : null,
      h('button', { class: 'btn ghost', type: 'button', onClick: () =>
        go(editing ? `/assets/${assetId}` : '/assets') }, '취소'),
      h('div', { class: 'spacer' }),
      editing ? null : keepGoing));

  function payload() {
    const raw = formValues(form);
    const out = {};
    for (const [k, val] of Object.entries(raw)) {
      if (k.startsWith('a_')) continue;
      out[k] = val;
    }
    if (!editing) {
      const on = assignBox && assignBox.querySelector('input[type=checkbox]').checked;
      if (on) {
        out.assignment = {
          emp_no: raw.a_emp_no, user_name: raw.a_user_name, dept_code: raw.a_dept_code,
          position_code: raw.a_position_code, issue_date: raw.a_issue_date,
          due_return_date: raw.a_due_return_date, site: raw.site, location: raw.location,
          reason: raw.reason || '등록 시 배정',
        };
      }
    }
    return out;
  }

  function changeTable(changes) {
    return h('table', { class: 'grid-table' },
      h('thead', {}, h('tr', {}, h('th', {}, '항목'), h('th', {}, '이전 값'), h('th', {}, '새 값'))),
      h('tbody', {}, ...changes.map(c => h('tr', {},
        h('td', {}, c.label),
        h('td', { class: 'muted' }, dash(c.before)),
        h('td', {}, h('strong', {}, dash(c.after)))))));
  }

  /** 04-5 — 저장 전 변경 내용 요약. [변경 내용 확인] 버튼과 저장 직전 확인에서 함께 쓴다. */
  async function previewChanges({ confirm = false } = {}) {
    const r = await api.post(`/assets/${assetId}/preview-changes`, payload());
    if (!r.changes.length) {
      toastOk('변경된 항목이 없습니다.');
      return false;
    }
    if (!confirm) {
      modal({
        title: '변경 내용 확인', size: 'wide',
        body: changeTable(r.changes),
        buttons: [{ label: '닫기', class: 'primary' }],
      });
      return false;
    }
    return new Promise((resolve) => {
      let done = false;
      modal({
        title: `변경 내용 확인 (${r.changes.length}개 항목)`, size: 'wide',
        body: h('div', {},
          h('p', { class: 'muted small mb8' }, '아래 내용으로 저장하고 변경 이력을 남깁니다.'),
          changeTable(r.changes),
          h('div', { class: 'alert info mt16' },
            h('strong', {}, '변경 사유: '), (payload().reason || '').trim() || '(없음)')),
        buttons: [
          { label: '돌아가서 수정', onClick: (close) => { done = true; close(); resolve(false); } },
          { label: '저장', class: 'primary', onClick: (close) => { done = true; close(); resolve(true); } },
        ],
        onClose: () => { if (!done) resolve(false); },
      });
    });
  }

  async function onSubmit(e) {
    e.preventDefault();
    clearFieldErrors(form);
    clear(warnBox);
    submitBtn.disabled = true;
    const label = submitBtn.textContent;
    submitBtn.textContent = '저장 중…';
    try {
      const body = payload();
      if (editing) {
        // 04-5 — 저장 전 변경 내용 요약을 보여주고 확인을 받는다
        if (!body.reason || !String(body.reason).trim()) {
          throw Object.assign(new Error('변경 사유를 입력하세요.'), { field: 'reason' });
        }
        const proceed = await previewChanges({ confirm: true });
        if (!proceed) return;
        const r = await api.put(`/assets/${assetId}`, body);
        toastOk(Object.keys(r.changed).length
          ? `${Object.keys(r.changed).length}개 항목이 변경되었습니다.`
          : '변경된 항목이 없어 이력을 남기지 않았습니다.');
        (r.warnings || []).forEach(w => toastWarn(w));
        go(`/assets/${assetId}`);
      } else {
        const r = await api.post('/assets', body);
        toastOk(`${r.asset_no} 자산이 등록되었습니다.`);
        (r.warnings || []).forEach(w => toastWarn(w));
        if (keepGoing.querySelector('input').checked) {
          // 02-9 — 연속 등록: 반복 입력이 적은 항목만 비운다
          ['asset_no', 'serial_no', 'hostname', 'ip_address', 'mac_address'].forEach(n => {
            const el = form.querySelector(`[name="${n}"]`);
            if (el) el.value = '';
          });
          form.querySelector('[name=asset_no]').focus();
          window.scrollTo({ top: 0, behavior: 'smooth' });
        } else {
          go(`/assets/${r.id}`);
        }
      }
    } catch (ex) {
      if (!setFieldError(form, ex.field, ex.message)) {
        warnBox.appendChild(alertBox('error', ex.message));
        window.scrollTo({ top: 0, behavior: 'smooth' });
      }
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = label;
    }
  }

  root.appendChild(h('div', { class: 'page-head' },
    h('h1', {}, editing ? '자산 수정' : '자산 등록'),
    editing ? h('span', { class: 'sub' }, `${asset.asset_no} · ${asset.manufacturer} ${asset.model_name}`) : null));
  root.appendChild(h('div', { class: 'panel' }, h('div', { class: 'panel-body' }, form)));
  return root;
}
