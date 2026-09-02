// SC-03 자산 목록 (FR-03, FR-05, FR-07)

import { api, download } from '../api.js';
import { h, clear, qs, dash, dateOnly, dateTime, num, money, statusBadge } from '../util.js';
import { pref, setPref, resetPref } from '../prefs.js';
import { pager, modal, toastOk, toastErr, emptyRow, selectField, multiSelectField,
         alertBox, confirmDialog } from '../ui.js';
import { go, labelsOf } from '../app.js';
import { assignModal, returnModal, statusModal } from './actions.js';

const QUICK = [
  { key: '',            label: '전체 보유' },
  { key: 'st:사용중',    label: '사용중' },
  { key: 'st:대기',      label: '대기' },
  { key: 'st:수리',      label: '수리' },
  { key: 'st:폐기예정',  label: '폐기예정' },
  { key: 'overdue',     label: '반납예정일 초과' },
  { key: 'unassigned',  label: '사용자 미지정' },
  { key: 'resigned',    label: '퇴사자 미회수' },
  { key: 'aged',        label: '내용연수 초과' },
  { key: 'os_eol_expired', label: 'OS 지원종료' },
];

const QUICK_LABELS = {
  overdue: '반납예정일 초과', due_soon: '7일 내 반납 예정', unassigned: '사용자 미지정',
  resigned: '퇴사자 미회수', long_repair: '30일 이상 수리', to_dispose: '폐기예정',
  aged: '내용연수 초과', os_eol_expired: 'OS 지원종료', os_eol_soon: '1년 내 OS 지원종료',
};

const FILTER_LABELS = {
  q: '검색어', status: '상태', asset_type: '자산구분', manufacturer: '제조사', site: '사업장',
  dept: '부서', os: '운영체제', manager: '담당자', emp_no: '사번', quick: '빠른 필터',
  purchase_from: '구매일 시작', purchase_to: '구매일 종료',
  issue_from: '지급일 시작', issue_to: '지급일 종료',
  disposal_from: '폐기일 시작', disposal_to: '폐기일 종료',
  include_disposed: '폐기 포함',
};

// 복수 선택(OR)이 가능한 필터 (05-2, 05-4)
const MULTI_FILTERS = [
  ['asset_type', '자산구분', 'ASSET_TYPE'],
  ['status', '자산상태', 'STATUS'],
  ['manufacturer', '제조사', 'MANUFACTURER'],
  ['site', '사업장', 'SITE'],
  ['dept', '부서', 'DEPT'],
  ['os', '운영체제', 'OS'],
];

// ---------------------------------------------------------------- 표시 컬럼 (03-2, 03-5, 03-8)
const ALL_COLUMNS = [
  { key: 'asset_no',   label: '자산번호',    sort: 'asset_no',     fixed: true,
    render: (r) => h('span', { class: 'mono' }, r.asset_no) },
  { key: 'asset_type', label: '구분',        sort: 'asset_type',   render: (r) => r.asset_type },
  { key: 'model',      label: '제조사·모델', sort: 'model_name',
    render: (r) => `${r.manufacturer} ${r.model_name}` },
  { key: 'status',     label: '상태',        sort: 'status',       render: (r) => statusBadge(r.status) },
  { key: 'user_name',  label: '사용자',      sort: 'user_name',
    render: (r) => r.cur_user_name
      ? h('span', {}, r.cur_user_name, h('span', { class: 'muted small' }, ` (${r.cur_emp_no || '—'})`))
      : h('span', { class: 'muted' }, '—') },
  { key: 'dept',       label: '소속부서',    sort: 'dept',
    render: (r) => dash(r.dept_label || r.cur_dept) },
  { key: 'site',       label: '사업장',      sort: 'site',         render: (r) => r.site },
  { key: 'location',   label: '위치',        render: (r) => dash(r.location) },
  { key: 'issue_date', label: '지급일',      sort: 'issue_date',
    render: (r) => dateOnly(r.cur_issue_date) },
  // 아래는 기본 미표시. [컬럼 설정]에서 켤 수 있다.
  { key: 'purchase_date', label: '구매일',   sort: 'purchase_date',
    render: (r) => dateOnly(r.purchase_date) },
  { key: 'due_date',   label: '반납예정일',
    render: (r) => dateOnly(r.cur_due_date) },
  { key: 'serial_no',  label: '시리얼번호',  render: (r) => h('span', { class: 'mono' }, dash(r.serial_no)) },
  { key: 'hostname',   label: 'Hostname',    render: (r) => h('span', { class: 'mono' }, dash(r.hostname)) },
  { key: 'ip_address', label: 'IP 주소',     render: (r) => h('span', { class: 'mono' }, dash(r.ip_address)) },
  { key: 'mac_address', label: 'MAC 주소',   render: (r) => h('span', { class: 'mono' }, dash(r.mac_address)) },
  { key: 'cpu',        label: 'CPU',         render: (r) => dash(r.cpu) },
  { key: 'ram_gb',     label: 'RAM(GB)',     render: (r) => r.ram_gb ? num(r.ram_gb) : '—' },
  { key: 'disk',       label: '디스크',
    render: (r) => r.disk_gb ? `${dash(r.disk_type)} ${num(r.disk_gb)}GB` : dash(r.disk_type) },
  { key: 'os',         label: '운영체제',    render: (r) => dash(r.os) },
  { key: 'purchase_amount', label: '취득금액', render: (r) => money(r.purchase_amount) },
  { key: 'manager',    label: '관리 담당자', render: (r) => dash(r.manager_emp_no) },
  { key: 'created_at', label: '등록일시',    sort: 'created_at',   render: (r) => dateTime(r.created_at) },
];

// PRD 03-2 기본 표시 컬럼
const DEFAULT_COLUMNS = ['asset_no', 'asset_type', 'model', 'status', 'user_name',
                         'dept', 'site', 'location', 'issue_date'];

function visibleColumns() {
  const saved = pref('asset_columns');
  const valid = new Set(ALL_COLUMNS.map(c => c.key));
  const keys = Array.isArray(saved) && saved.length
    ? saved.filter(k => valid.has(k))
    : DEFAULT_COLUMNS;
  const set = new Set(['asset_no', ...keys]);          // 자산번호는 항상 표시
  return ALL_COLUMNS.filter(c => set.has(c.key));
}

// ---------------------------------------------------------------- 화면
export async function renderAssetList(query) {
  const root = h('div', {});
  const f = { ...query };
  let page = Number(f.page || 1);
  let size = Number(f.size || 20);
  let sort = f.sort || 'created_at';
  let order = f.order || 'desc';
  delete f.page; delete f.size; delete f.sort; delete f.order; delete f.t;

  const selected = new Set();

  const navigate = (patch = {}) => {
    const next = { ...f, ...patch, page, size, sort, order };
    if (patch.page === undefined && Object.keys(patch).length) next.page = 1;
    go('/assets' + qs(next));                                   // 05-7 조건을 URL에 반영
  };

  // ---------------- 검색 바
  const searchInput = h('input', {
    type: 'search', value: f.q || '', placeholder: '자산번호 · S/N · 사용자 · 사번 · Hostname · IP · 모델명',
    style: 'min-width:360px',
  });
  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') navigate({ q: searchInput.value.trim() || undefined });
  });

  const quickBar = h('div', { class: 'quick-filters' }, ...QUICK.map(qf => {
    const on = qf.key.startsWith('st:')
      ? (f.status === qf.key.slice(3) && !f.quick)
      : (qf.key ? f.quick === qf.key : (!f.quick && !f.status));
    return h('button', {
      type: 'button', class: on ? 'on' : '',
      onClick: () => {
        const patch = { quick: undefined, status: undefined };
        if (qf.key.startsWith('st:')) patch.status = qf.key.slice(3);
        else if (qf.key) patch.quick = qf.key;
        navigate(patch);
      },
    }, qf.label);
  }));

  // 05-5 적용 필터 칩 — 복수 선택 값은 콤마로 나열된다
  const chipBar = h('div', { class: 'chips' });
  const activeKeys = Object.keys(f).filter(k => f[k] !== undefined && f[k] !== '' && FILTER_LABELS[k]);
  const chipValue = (k) => {
    if (k === 'quick') return QUICK_LABELS[f[k]] || f[k];
    if (k === 'include_disposed') return '포함';
    return String(f[k]).split(',').join(', ');
  };
  if (activeKeys.length) {
    activeKeys.forEach(k => chipBar.appendChild(h('div', { class: 'chip' },
      h('span', {}, `${FILTER_LABELS[k]}: ${chipValue(k)}`),
      h('button', { type: 'button', title: '해제', onClick: () => navigate({ [k]: undefined }) }, '×'))));
    chipBar.appendChild(h('button', { class: 'btn ghost sm', onClick: () => go('/assets') }, '전체 초기화'));
  }

  const filterPanel = h('div', { class: 'panel' },
    h('div', { class: 'panel-head' },
      h('h2', {}, '검색'),
      h('div', { class: 'right' },
        savedSearchMenu(f, navigate, activeKeys),
        h('button', { class: 'btn sm', onClick: () => detailFilterModal(f, navigate) }, '상세 필터'),
        h('button', { class: 'btn sm', onClick: () => go('/assets') }, '초기화'))),
    h('div', { class: 'panel-body' },
      h('div', { class: 'flex wrap mb8' },
        searchInput,
        h('button', { class: 'btn primary', onClick: () => navigate({ q: searchInput.value.trim() || undefined }) }, '검색'),
        h('label', { class: 'check' },
          h('input', {
            type: 'checkbox', checked: f.include_disposed === '1',
            onChange: (e) => navigate({ include_disposed: e.target.checked ? '1' : undefined }),
          }), '폐기 자산 포함')),
      quickBar,
      activeKeys.length ? h('div', { class: 'mt8' }, chipBar) : null));

  root.appendChild(h('div', { class: 'page-head' },
    h('h1', {}, '자산 목록'),
    h('div', { class: 'actions' },
      h('button', { class: 'btn', onClick: () => go('/import') }, '엑셀 가져오기'),
      h('button', { class: 'btn', onClick: () => exportModal(f, sort, order) }, '엑셀 내보내기'),
      h('button', { class: 'btn primary', onClick: () => go('/assets/new') }, '+ 자산 등록'))));
  root.appendChild(filterPanel);

  // ---------------- 목록
  const listPanel = h('div', { class: 'panel' });
  root.appendChild(listPanel);

  async function load() {
    const columns = visibleColumns();
    clear(listPanel);
    listPanel.appendChild(h('div', { class: 'loading' }, h('span', { class: 'spinner' }), ' 불러오는 중…'));
    let data;
    try {
      data = await api.get('/assets' + qs({ ...f, page, size, sort, order }));
    } catch (e) {
      clear(listPanel);
      listPanel.appendChild(h('div', { class: 'panel-body' }, h('div', { class: 'alert error' }, e.message)));
      return;
    }
    clear(listPanel);

    const bulkBar = h('div', { class: 'panel-head' },
      h('h2', {}, `검색 결과 ${num(data.total)}건`),
      h('div', { class: 'right', id: 'bulk-actions' }));
    listPanel.appendChild(bulkBar);

    const updateBulkBar = () => {
      const box = clear(bulkBar.querySelector('#bulk-actions'));
      if (!selected.size) {
        box.appendChild(h('span', { class: 'muted small' }, '행을 선택하면 일괄 처리를 할 수 있습니다.'));
        box.appendChild(h('button', { class: 'btn sm', onClick: () => columnModal(load) }, '컬럼 설정'));
        return;
      }
      const ids = [...selected];
      box.appendChild(h('span', { class: 'small' }, `${ids.length}건 선택`));
      box.appendChild(h('button', { class: 'btn sm', onClick: () => assignModal({ ids, onDone: load }) }, '일괄 배정'));
      box.appendChild(h('button', { class: 'btn sm', onClick: () => returnModal({ ids, onDone: load }) }, '일괄 회수'));
      box.appendChild(h('button', { class: 'btn sm', onClick: () => statusModal({ ids, onDone: load }) }, '일괄 상태변경'));
      box.appendChild(h('button', { class: 'btn ghost sm', onClick: () => { selected.clear(); load(); } }, '선택 해제'));
    };

    const thead = h('tr', {},
      h('th', { class: 'center', style: 'width:34px' },
        h('input', {
          type: 'checkbox',
          checked: data.items.length > 0 && data.items.every(i => selected.has(i.id)),
          onChange: (e) => {
            data.items.forEach(i => e.target.checked ? selected.add(i.id) : selected.delete(i.id));
            load();
          },
        })),
      ...columns.map(c => h('th', {
        class: c.sort ? 'sortable nowrap' : 'nowrap',
        onClick: c.sort ? () => {
          order = (sort === c.sort && order === 'desc') ? 'asc' : 'desc';
          sort = c.sort; page = 1; navigate({});
        } : null,
      }, c.label, sort === c.sort
        ? h('span', { class: 'arrow' }, order === 'asc' ? ' ▲' : ' ▼') : null)));

    const tbody = h('tbody', {});
    if (!data.items.length) {
      tbody.appendChild(emptyRow(columns.length + 1,
        '조건에 맞는 자산이 없습니다. 검색 조건을 바꾸거나 자산을 등록하세요.'));
    }
    for (const r of data.items) {
      tbody.appendChild(h('tr', { class: 'clickable', onClick: (e) => {
        if (e.target.type === 'checkbox') return;
        go(`/assets/${r.id}`);
      } },
        h('td', { class: 'center' }, h('input', {
          type: 'checkbox', checked: selected.has(r.id),
          onClick: (e) => e.stopPropagation(),
          onChange: (e) => { e.target.checked ? selected.add(r.id) : selected.delete(r.id); updateBulkBar(); },
        })),
        ...columns.map(c => h('td', { class: c.key === 'asset_no' ? 'nowrap' : '' }, c.render(r)))));
    }

    listPanel.appendChild(h('div', { class: 'table-wrap' },
      h('table', { class: 'grid-table' }, h('thead', {}, thead), tbody)));
    listPanel.appendChild(pager({
      total: data.total, page, size,
      onPage: (p) => { page = p; navigate({ page: p }); },
      onSize: (s) => { size = s; page = 1; navigate({ size: s, page: 1 }); },
    }));
    updateBulkBar();
  }

  await load();
  return root;
}

// ---------------------------------------------------------------- 표시 컬럼 설정 (03-8)
function columnModal(onDone) {
  const current = new Set(visibleColumns().map(c => c.key));
  const picker = h('div', { class: 'column-picker' },
    ...ALL_COLUMNS.map(c => h('label', { class: 'check' + (c.fixed ? ' fixed' : '') },
      h('input', {
        type: 'checkbox', value: c.key,
        checked: current.has(c.key), disabled: c.fixed,
      }), c.label, c.fixed ? h('span', { class: 'muted small' }, ' (고정)') : null)));

  modal({
    title: '표시 컬럼 설정', size: 'wide',
    body: h('div', {},
      alertBox('info', '선택한 컬럼은 내 계정에 저장됩니다. 다른 PC에서 접속해도 그대로 유지됩니다.'),
      picker),
    buttons: [
      { label: '기본값으로', onClick: async (close, foot) => {
        const btn = foot.querySelectorAll('.btn')[0];
        btn.disabled = true;
        try {
          await resetPref('asset_columns');
          close(); toastOk('기본 컬럼으로 되돌렸습니다.'); onDone();
        } catch (e) { toastErr(e.message); btn.disabled = false; }
      } },
      { label: '취소' },
      { label: '적용', class: 'primary', onClick: async (close, foot) => {
        const btn = foot.querySelector('.btn.primary');
        const keys = [...picker.querySelectorAll('input:checked')].map(i => i.value);
        btn.disabled = true; btn.textContent = '저장 중…';
        try {
          // ALL_COLUMNS 순서를 유지한다
          await setPref('asset_columns', ALL_COLUMNS.filter(c => keys.includes(c.key)).map(c => c.key));
          close(); onDone();
        } catch (e) {
          toastErr(e.message);
          btn.disabled = false; btn.textContent = '적용';
        }
      } },
    ],
  });
}

// ---------------------------------------------------------------- 검색 조건 저장 (05-8)
function savedSearchMenu(f, navigate, activeKeys) {
  const list = pref('saved_searches', []) || [];
  const wrap = h('div', { class: 'saved-search' });

  const sel = h('select', { style: 'width:auto;min-width:132px', onChange: (e) => {
    const item = list[Number(e.target.value)];
    if (!item) return;
    const patch = Object.fromEntries(Object.keys(FILTER_LABELS).map(k => [k, undefined]));
    navigate({ ...patch, ...item.filters });
  } },
    h('option', { value: '' }, list.length ? '저장된 조건…' : '저장된 조건 없음'),
    ...list.map((s, i) => h('option', { value: i }, s.name)));

  wrap.append(sel,
    h('button', {
      class: 'btn sm', title: '현재 검색 조건을 이름을 붙여 저장합니다',
      onClick: () => saveModal(f, activeKeys),
    }, '조건 저장'),
    list.length ? h('button', {
      class: 'btn ghost sm', title: '저장된 조건 관리', onClick: () => manageModal(),
    }, '관리') : null);
  return wrap;
}

function saveModal(f, activeKeys) {
  if (!activeKeys.length) { toastErr('저장할 검색 조건이 없습니다. 먼저 조건을 지정하세요.'); return; }
  const input = h('input', { type: 'text', placeholder: '예: 시화 생산기술팀 노트북', maxlength: 40 });
  const summary = activeKeys.map(k => `${FILTER_LABELS[k]}: ${String(f[k]).split(',').join(', ')}`).join(' / ');

  modal({
    title: '검색 조건 저장',
    body: h('div', {},
      h('div', { class: 'field' }, h('label', {}, '이름'), input),
      h('div', { class: 'alert info' }, summary)),
    buttons: [
      { label: '취소' },
      { label: '저장', class: 'primary', onClick: async (close, foot) => {
        const btn = foot.querySelector('.btn.primary');
        const name = input.value.trim();
        if (!name) { toastErr('이름을 입력하세요.'); return; }
        const list = [...(pref('saved_searches', []) || [])];
        const filters = Object.fromEntries(activeKeys.map(k => [k, f[k]]));
        const idx = list.findIndex(s => s.name === name);
        if (idx >= 0) list[idx] = { name, filters }; else list.push({ name, filters });
        btn.disabled = true; btn.textContent = '저장 중…';
        try {
          await setPref('saved_searches', list);
          close();
          toastOk(`'${name}' 조건을 저장했습니다.`);
        } catch (e) {
          toastErr(e.message);
          btn.disabled = false; btn.textContent = '저장';
        }
      } },
    ],
  });
}

function manageModal() {
  const list = [...(pref('saved_searches', []) || [])];
  const box = h('div', {});
  const paint = () => {
    clear(box);
    if (!list.length) { box.appendChild(h('div', { class: 'empty' }, '저장된 조건이 없습니다.')); return; }
    list.forEach((s, i) => box.appendChild(h('div', { class: 'saved-row' },
      h('span', { class: 'name' }, s.name),
      h('span', { class: 'cond' }, Object.entries(s.filters)
        .map(([k, v]) => `${FILTER_LABELS[k] || k}: ${String(v).split(',').join(', ')}`).join(' / ')),
      h('button', { class: 'btn sm danger', onClick: async () => {
        const ok = await confirmDialog(`'${s.name}' 조건을 삭제할까요?`,
          { title: '검색 조건 삭제', okLabel: '삭제', danger: true });
        if (!ok) return;
        const backup = [...list];
        list.splice(i, 1);
        try {
          await setPref('saved_searches', list);
          paint();
        } catch (ex) {
          list.splice(0, list.length, ...backup);
          toastErr(ex.message);
        }
      } }, '삭제'))));
  };
  paint();
  modal({ title: '저장된 검색 조건', size: 'wide', body: box, buttons: [{ label: '닫기', class: 'primary' }] });
}

// ---------------------------------------------------------------- 상세 필터 (05-2, 05-3, 05-4)
function detailFilterModal(f, navigate) {
  const multis = MULTI_FILTERS.map(([key, label, group]) => ({
    key,
    field: multiSelectField({
      label, options: labelsOf(group),
      values: String(f[key] || '').split(',').filter(Boolean),
    }),
  }));

  const textInputs = h('div', { class: 'form-grid' },
    h('div', { class: 'field' }, h('label', {}, '관리 담당자'),
      h('input', { type: 'text', name: 'manager', value: f.manager || '' })),
    h('div', { class: 'field' }, h('label', {}, '사번'),
      h('input', { type: 'text', name: 'emp_no', value: f.emp_no || '' })),
    h('div', {}),
    ...dateRange('구매일', 'purchase_from', 'purchase_to', f),
    ...dateRange('지급일', 'issue_from', 'issue_to', f),
    ...dateRange('폐기일', 'disposal_from', 'disposal_to', f));

  const body = h('div', {},
    alertBox('info', '같은 항목에서 여러 값을 고르면 OR로, 서로 다른 항목끼리는 AND로 걸립니다.'),
    h('div', { class: 'form-grid' }, ...multis.map(m => m.field)),
    textInputs);

  modal({
    title: '상세 필터', size: 'xwide', body,
    buttons: [
      { label: '조건 비우기', onClick: (close) => {
        close();
        navigate(Object.fromEntries(
          Object.keys(FILTER_LABELS).filter(k => k !== 'q').map(k => [k, undefined])));
      } },
      { label: '취소' },
      { label: '적용', class: 'primary', onClick: (close) => {
        const patch = {};
        for (const m of multis) {
          const vals = m.field.values();
          patch[m.key] = vals.length ? vals.join(',') : undefined;
        }
        for (const el of textInputs.querySelectorAll('input')) {
          patch[el.name] = el.value ? el.value : undefined;
        }
        // 상세 필터를 적용하면 빠른 필터와 충돌하지 않도록 해제한다
        patch.quick = undefined;
        close();
        navigate(patch);
      } },
    ],
  });
}

function dateRange(label, fromKey, toKey, f) {
  return [
    h('div', { class: 'field span2' },
      h('label', {}, `${label} 기간`),
      h('div', { class: 'flex' },
        h('input', { type: 'date', name: fromKey, value: f[fromKey] || '' }),
        h('span', { class: 'muted' }, '~'),
        h('input', { type: 'date', name: toKey, value: f[toKey] || '' }))),
    h('div', {}),
  ];
}

// ---------------------------------------------------------------- 내보내기 (FR-07)
const EXPORT_FIELDS = [
  ['asset_no', '자산번호'], ['asset_type', '자산구분'], ['manufacturer', '제조사'],
  ['model_name', '모델명'], ['serial_no', '시리얼번호'], ['purchase_date', '구매일'],
  ['status', '자산상태'], ['purchase_amount', '취득금액'], ['site', '사업장'],
  ['location', '위치'], ['manager_emp_no', '관리 담당자'], ['hostname', 'Hostname'],
  ['ip_address', 'IP 주소'], ['mac_address', 'MAC 주소'], ['cpu', 'CPU'], ['ram_gb', 'RAM(GB)'],
  ['disk_type', '디스크 유형'], ['disk_gb', '디스크 용량(GB)'], ['os', '운영체제'],
  ['cur_emp_no', '사번'], ['cur_user_name', '사용자명'], ['cur_dept', '소속부서'],
  ['cur_issue_date', '지급일'], ['cur_due_date', '반납예정일'],
  ['disposal_date', '폐기일'], ['disposal_method', '폐기방법'], ['remark', '비고'],
];

function exportModal(f, sort, order) {
  const custom = h('div', { class: 'hidden mt8', style: 'columns:3; column-gap:16px' },
    ...EXPORT_FIELDS.map(([k, l]) => h('label', { class: 'check', style: 'display:flex;margin-bottom:4px' },
      h('input', { type: 'checkbox', value: k, checked: ['asset_no', 'asset_type', 'model_name', 'status', 'cur_user_name'].includes(k) }), l)));

  const radios = [];
  const scopeSel = h('div', { class: 'field' },
    h('label', {}, '내보낼 항목'),
    ...[['basic', '기본 항목 (자산번호·구분·모델·상태·사용자·부서·사업장·지급일)'],
        ['full', '전체 항목 (하드웨어·등록 정보 포함)'],
        ['custom', '사용자 지정']].map(([v, l]) => {
      const radio = h('input', { type: 'radio', name: 'scope', value: v, checked: v === 'basic',
        onChange: () => custom.classList.toggle('hidden', v !== 'custom') });
      radios.push(radio);
      return h('label', { class: 'check', style: 'display:flex;margin-bottom:5px' }, radio, l);
    }));

  const withHistory = h('label', { class: 'check' },
    h('input', { type: 'checkbox' }), '자산별 변경 이력을 별도 시트로 포함');

  modal({
    title: '엑셀 내보내기', size: 'wide',
    body: h('div', {},
      alertBox('info', '현재 검색·필터 조건이 그대로 적용됩니다. (페이징 무관, 최대 10,000행)'),
      scopeSel, custom,
      h('div', { class: 'mt16' }, withHistory)),
    buttons: [
      { label: '취소' },
      { label: '내려받기', class: 'primary', onClick: async (close, foot) => {
        const btn = foot.querySelector('.btn.primary');
        const scope = (radios.find(r => r.checked) || {}).value || 'basic';
        const columns = [...custom.querySelectorAll('input:checked')].map(i => i.value).join(',');
        btn.disabled = true; btn.textContent = '생성 중…';
        try {
          const name = await download('/assets/export.xlsx' + qs({
            ...f, scope, columns, sort, order,
            with_history: withHistory.querySelector('input').checked ? 'true' : undefined,
          }));
          close();
          toastOk(`${name} 파일을 내려받았습니다.`);
        } catch (e) {
          toastErr(e.message);
          btn.disabled = false; btn.textContent = '내려받기';
        }
      } },
    ],
  });
}
