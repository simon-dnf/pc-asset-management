// SC-12 임직원 목록 / 상세 (FR-14)

import { api } from '../api.js';
import { h, clear, qs, num, dash, dateOnly, statusBadge, formValues, setFieldError, clearFieldErrors } from '../util.js';
import { pager, modal, toastOk, toastErr, toastWarn, alertBox, emptyRow, selectField, textField,
         confirmDialog } from '../ui.js';
import { go, labelsOf } from '../app.js';
import { returnModal } from './actions.js';

const EMPLOY_BADGE = { '재직': 'green', '휴직': 'amber', '퇴사': 'red' };

// ---------------------------------------------------------------- 목록
export async function renderEmployees(query) {
  const f = { ...query };
  let page = Number(f.page || 1);
  let size = Number(f.size || 20);
  delete f.page; delete f.size; delete f.t;

  const navigate = (patch = {}) => {
    const next = { ...f, ...patch, page, size };
    if (patch.page === undefined && Object.keys(patch).length) next.page = 1;
    go('/employees' + qs(next));
  };

  const root = h('div', {});
  root.appendChild(h('div', { class: 'page-head' },
    h('h1', {}, '임직원'),
    h('span', { class: 'sub' }, '사번 기준 마스터. 배정 시 이름·부서가 자동으로 채워집니다.'),
    h('div', { class: 'actions' },
      h('button', { class: 'btn', onClick: () => go('/import?kind=employee') }, '엑셀 가져오기'),
      h('button', { class: 'btn primary', onClick: () => employeeModal(null, () => navigate({ t: Date.now() })) }, '+ 임직원 등록'))));

  const search = h('input', { type: 'search', value: f.q || '', placeholder: '사번 또는 이름', style: 'min-width:240px' });
  search.addEventListener('keydown', e => { if (e.key === 'Enter') navigate({ q: search.value.trim() || undefined }); });

  root.appendChild(h('div', { class: 'panel' }, h('div', { class: 'panel-body' },
    h('div', { class: 'flex wrap' },
      search,
      selectField({ name: 'dept', options: labelsOf('DEPT'), value: f.dept, placeholder: '부서 전체',
        onChange: (e) => navigate({ dept: e.target.value || undefined }) }),
      selectField({ name: 'site', options: labelsOf('SITE'), value: f.site, placeholder: '사업장 전체',
        onChange: (e) => navigate({ site: e.target.value || undefined }) }),
      selectField({ name: 'employ_status', options: ['재직', '휴직', '퇴사'], value: f.employ_status,
        placeholder: '재직상태 전체', onChange: (e) => navigate({ employ_status: e.target.value || undefined }) }),
      h('button', { class: 'btn primary', onClick: () => navigate({ q: search.value.trim() || undefined }) }, '검색'),
      h('button', { class: 'btn ghost', onClick: () => go('/employees') }, '초기화')))));

  const listPanel = h('div', { class: 'panel' });
  root.appendChild(listPanel);

  const data = await api.get('/employees' + qs({ ...f, page, size }));
  clear(listPanel);
  listPanel.appendChild(h('div', { class: 'panel-head' }, h('h2', {}, `${num(data.total)}명`)));

  const rows = data.items.map(e => h('tr', { class: 'clickable',
    onClick: () => go(`/employees/${encodeURIComponent(e.emp_no)}`) },
    h('td', { class: 'mono nowrap' }, e.emp_no),
    h('td', {}, h('strong', {}, e.name)),
    h('td', {}, dash(e.dept_label || e.dept_code)),
    h('td', {}, dash(e.position_code)),
    h('td', {}, dash(e.site_code)),
    h('td', {}, h('span', { class: `badge ${EMPLOY_BADGE[e.employ_status] || 'gray'}` }, e.employ_status)),
    h('td', { class: 'num' }, e.asset_count
      ? h('strong', {}, `${e.asset_count}대`)
      : h('span', { class: 'muted' }, '—'))));

  listPanel.appendChild(h('div', { class: 'table-wrap' },
    h('table', { class: 'grid-table' },
      h('thead', {}, h('tr', {},
        h('th', {}, '사번'), h('th', {}, '성명'), h('th', {}, '소속부서'), h('th', {}, '직급'),
        h('th', {}, '사업장'), h('th', {}, '재직상태'), h('th', { class: 'right' }, '보유 자산'))),
      h('tbody', {}, ...(rows.length ? rows : [emptyRow(7, '등록된 임직원이 없습니다.')])))));

  listPanel.appendChild(pager({
    total: data.total, page, size,
    onPage: (p) => { page = p; navigate({ page: p }); },
    onSize: (s) => { size = s; page = 1; navigate({ size: s, page: 1 }); },
  }));

  return root;
}

// ---------------------------------------------------------------- 상세
export async function renderEmployeeDetail(empNo) {
  const e = await api.get(`/employees/${encodeURIComponent(empNo)}`);
  const root = h('div', {});
  const reload = () => go(`/employees/${encodeURIComponent(empNo)}?t=${Date.now()}`);

  root.appendChild(h('div', { class: 'page-head' },
    h('h1', {}, e.name, ' ', h('span', { class: `badge ${EMPLOY_BADGE[e.employ_status]}` }, e.employ_status)),
    h('span', { class: 'sub' }, `사번 ${e.emp_no}`),
    h('div', { class: 'actions' },
      h('button', { class: 'btn', onClick: () => employeeModal(e, reload) }, '수정'),
      h('button', { class: 'btn ghost', onClick: () => go('/employees') }, '목록'))));

  if (e.employ_status === '퇴사' && e.assets.length) {
    root.appendChild(alertBox('error',
      `퇴사자에게 배정된 자산 ${e.assets.length}건이 회수되지 않았습니다.`,
      e.assets.map(a => `${a.asset_no} · ${a.manufacturer} ${a.model_name}`)));
  }

  // 14-5 부서 불일치 안내
  if (e.dept_mismatch.length) {
    const box = h('div', { class: 'alert warn' },
      h('strong', {}, `부서 정보가 다른 자산 ${e.dept_mismatch.length}건`),
      h('div', { class: 'small mt8' },
        '임직원 부서를 바꿔도 자산 배정 부서는 자동으로 바뀌지 않습니다. (이력 소급 변조 방지)'),
      h('div', { class: 'mt8' },
        h('button', { class: 'btn sm', onClick: async () => {
          const ok = await confirmDialog(
            `자산 ${e.dept_mismatch.join(', ')}의 배정 부서를 '${dash(e.dept_label || e.dept_code)}'(으)로 갱신합니다.\n각 자산에 이동 이력이 남습니다.`,
            { title: '부서 정보 일괄 갱신', okLabel: '갱신' });
          if (!ok) return;
          try {
            const r = await api.post(`/employees/${encodeURIComponent(empNo)}/sync-dept`,
              { reason: `임직원 부서 변경 반영 (${e.name})` });
            toastOk(`${r.updated.length}건 갱신했습니다.`);
            reload();
          } catch (ex) { toastErr(ex.message); }
        } }, '자산 부서 일괄 갱신')));
    root.appendChild(box);
  }

  root.appendChild(h('div', { class: 'panel' },
    h('div', { class: 'panel-head' }, h('h2', {}, '기본정보')),
    h('div', { class: 'panel-body' },
      h('table', { class: 'kv' },
        h('tr', {}, h('th', {}, '사번'), h('td', { class: 'mono' }, e.emp_no)),
        h('tr', {}, h('th', {}, '성명'), h('td', {}, e.name)),
        h('tr', {}, h('th', {}, '소속부서'), h('td', {}, dash(e.dept_label || e.dept_code))),
        h('tr', {}, h('th', {}, '직급'), h('td', {}, dash(e.position_code))),
        h('tr', {}, h('th', {}, '사업장'), h('td', {}, dash(e.site_code))),
        h('tr', {}, h('th', {}, '이메일 / 연락처'), h('td', {}, `${dash(e.email)} / ${dash(e.phone)}`))))));

  // 14-3 배정 자산
  const selected = new Set();
  const bulkBox = h('div', { class: 'right' });
  const assetRows = e.assets.map(a => h('tr', {},
    h('td', { class: 'center' }, h('input', { type: 'checkbox', onChange: (ev) => {
      ev.target.checked ? selected.add(a.id) : selected.delete(a.id);
      paintBulk();
    } })),
    h('td', { class: 'mono' }, h('a', { href: `#/assets/${a.id}` }, a.asset_no)),
    h('td', {}, `${a.manufacturer} ${a.model_name}`),
    h('td', {}, a.asset_type),
    h('td', {}, statusBadge(a.status)),
    h('td', {}, `${a.site} / ${dash(a.location)}`),
    h('td', {}, dateOnly(a.issue_date)),
    h('td', {}, a.due_return_date ? dateOnly(a.due_return_date) : '—')));

  function paintBulk() {
    clear(bulkBox);
    if (!selected.size) {
      bulkBox.appendChild(h('span', { class: 'muted small' }, '자산을 선택하면 일괄 회수할 수 있습니다.'));
      return;
    }
    bulkBox.appendChild(h('span', { class: 'small' }, `${selected.size}건 선택`));
    bulkBox.appendChild(h('button', { class: 'btn sm primary', onClick: () =>
      returnModal({ ids: [...selected], onDone: reload }) }, '일괄 회수'));
  }
  paintBulk();

  root.appendChild(h('div', { class: 'panel' },
    h('div', { class: 'panel-head' }, h('h2', {}, `배정 자산 ${e.assets.length}건`), bulkBox),
    h('div', { class: 'table-wrap' },
      h('table', { class: 'grid-table' },
        h('thead', {}, h('tr', {},
          h('th', { class: 'center', style: 'width:34px' }, ''),
          h('th', {}, '자산번호'), h('th', {}, '제조사·모델'), h('th', {}, '구분'),
          h('th', {}, '상태'), h('th', {}, '사업장/위치'), h('th', {}, '지급일'), h('th', {}, '반납예정일'))),
        h('tbody', {}, ...(assetRows.length ? assetRows : [emptyRow(8, '배정된 자산이 없습니다.')]))))));

  const pastRows = (e.past_assets || []).map(p => h('tr', {},
    h('td', { class: 'mono' }, p.asset_no),
    h('td', {}, p.model_name),
    h('td', {}, dateOnly(p.issue_date)),
    h('td', {}, dateOnly(p.return_date)),
    h('td', {}, dash(p.return_reason))));

  root.appendChild(h('div', { class: 'panel' },
    h('div', { class: 'panel-head' }, h('h2', {}, '과거 사용 자산')),
    h('div', { class: 'table-wrap' },
      h('table', { class: 'grid-table' },
        h('thead', {}, h('tr', {},
          h('th', {}, '자산번호'), h('th', {}, '모델'), h('th', {}, '지급일'),
          h('th', {}, '회수일'), h('th', {}, '회수 사유'))),
        h('tbody', {}, ...(pastRows.length ? pastRows : [emptyRow(5, '과거 사용 이력이 없습니다.')]))))));

  return root;
}

// ---------------------------------------------------------------- 등록/수정 모달
function employeeModal(emp, onDone) {
  const editing = !!emp;
  const v = emp || {};
  const form = h('form', { class: 'form-grid c2', onSubmit: e => e.preventDefault() },
    textField({ name: 'emp_no', label: '사번', required: true, value: v.emp_no || '', disabled: editing }),
    textField({ name: 'name', label: '성명', required: true, value: v.name || '' }),
    selectField({ name: 'dept_code', label: '소속부서', options: labelsOf('DEPT'), value: v.dept_code }),
    selectField({ name: 'position_code', label: '직급', options: labelsOf('POSITION'), value: v.position_code }),
    selectField({ name: 'site_code', label: '사업장', options: labelsOf('SITE'), value: v.site_code }),
    selectField({ name: 'employ_status', label: '재직상태', required: true, placeholder: '',
      options: ['재직', '휴직', '퇴사'], value: v.employ_status || '재직' }),
    textField({ name: 'email', label: '이메일', value: v.email || '' }),
    textField({ name: 'phone', label: '연락처', value: v.phone || '' }));

  modal({
    title: editing ? '임직원 수정' : '임직원 등록',
    size: 'wide',
    body: h('div', {},
      editing ? null : h('p', { class: 'muted small mb16' },
        '대량 등록은 [엑셀 가져오기 → 임직원 명단]을 이용하세요.'),
      form),
    buttons: [
      { label: '취소' },
      { label: '저장', class: 'primary', onClick: async (close, foot) => {
        const btn = foot.querySelector('.btn.primary');
        clearFieldErrors(form);
        const body = formValues(form);
        if (editing) body.emp_no = emp.emp_no;
        btn.disabled = true; btn.textContent = '저장 중…';
        try {
          const r = editing
            ? await api.put(`/employees/${encodeURIComponent(emp.emp_no)}`, body)
            : await api.post('/employees', body);
          close();
          toastOk(editing ? '임직원 정보를 수정했습니다.' : '임직원을 등록했습니다.');
          (r.warnings || []).forEach(w => toastWarn(w, '미회수 자산'));
          onDone && onDone();
        } catch (ex) {
          if (!setFieldError(form, ex.field, ex.message)) toastErr(ex.message);
          btn.disabled = false; btn.textContent = '저장';
        }
      } },
    ],
  });
}
