// SC-05 자산 상세 — 기본정보 / 사용자·배정 / 하드웨어 / 이력 탭 (FR-03-7, FR-10)

import { api } from '../api.js';
import { h, clear, dash, num, money, dateOnly, dateTime, statusBadge, daysBetween } from '../util.js';
import { modal, toastOk, toastErr, reasonDialog, alertBox, emptyRow } from '../ui.js';
import { go } from '../app.js';
import { assignModal, returnModal, statusModal } from './actions.js';

const HIST_FILTERS = [
  ['', '전체'], ['CREATE', '등록'], ['ASSIGN', '배정'], ['RETURN', '회수'],
  ['MOVE', '이동'], ['UPDATE', '정보변경'], ['STATUS', '상태변경'], ['DISPOSE', '폐기'],
];

export async function renderAssetDetail(assetId, query) {
  const a = await api.get(`/assets/${assetId}`);
  const root = h('div', {});
  const reload = () => go(`/assets/${assetId}?t=${Date.now()}`);

  // ---------------- 헤더
  const disposed = a.status === '폐기';
  const actions = h('div', { class: 'actions' });
  if (!disposed) {
    actions.appendChild(h('button', { class: 'btn', onClick: () => go(`/assets/${assetId}/edit`) }, '수정'));
    if (a.status === '대기' || a.assignment) {
      actions.appendChild(h('button', { class: 'btn', onClick: () =>
        assignModal({ asset: a, onDone: reload }) }, a.assignment ? '사용자 교체' : '배정'));
    }
    if (a.status === '사용중' || a.status === '수리') {
      actions.appendChild(h('button', { class: 'btn', onClick: () =>
        returnModal({ asset: a, onDone: reload }) }, '회수'));
    }
    if ((a.allowed_status || []).length) {
      actions.appendChild(h('button', { class: 'btn', onClick: () =>
        statusModal({ asset: a, allowed: a.allowed_status, onDone: reload }) }, '상태 변경'));
    }
    if (a.can_delete) {
      actions.appendChild(h('button', { class: 'btn danger', onClick: () => doDelete(a) }, '삭제'));
    }
  }
  actions.appendChild(h('button', { class: 'btn ghost', onClick: () => go('/assets') }, '목록'));

  root.appendChild(h('div', { class: 'page-head' },
    h('h1', {}, h('span', { class: 'mono' }, a.asset_no), ' ', statusBadge(a.status)),
    h('span', { class: 'sub' }, `${a.manufacturer} ${a.model_name} · ${a.asset_type}`),
    actions));

  if (disposed) {
    root.appendChild(alertBox('warn',
      `폐기 완료된 자산입니다 (${dateOnly(a.disposal_date)} · ${dash(a.disposal_method)}). 조회만 가능합니다.`));
  }
  if (a.assignment && a.assignment.due_return_date && a.assignment.due_return_date < todayStr()) {
    root.appendChild(alertBox('error',
      `반납예정일(${a.assignment.due_return_date})이 지났습니다. 회수 처리가 필요합니다.`));
  }
  if (a.employee && a.employee.employ_status === '퇴사') {
    root.appendChild(alertBox('error',
      `현재 사용자 ${a.employee.name}님은 퇴사 처리되었습니다. 미회수 자산입니다.`));
  }

  // ---------------- 탭
  const panel = h('div', { class: 'panel' });
  const tabBar = h('div', { class: 'tabs' });
  const body = h('div', { class: 'panel-body' });
  panel.append(tabBar, body);
  root.appendChild(panel);

  const TABS = [
    ['basic', '기본정보', () => tabBasic(a)],
    ['assign', '사용자·배정', () => tabAssign(a)],
    ['hw', '하드웨어', () => tabHw(a)],
    ['hist', '이력', () => tabHistory(a)],
  ];
  let current = query.tab || 'basic';

  function paint() {
    clear(tabBar);
    TABS.forEach(([key, label]) => tabBar.appendChild(h('button', {
      type: 'button', class: current === key ? 'on' : '',
      onClick: async () => { current = key; paint(); },
    }, label)));
    clear(body);
    const node = TABS.find(t => t[0] === current)[2]();
    if (node instanceof Promise) node.then(n => { clear(body); body.appendChild(n); });
    else body.appendChild(node);
  }
  paint();

  async function doDelete(asset) {
    const reason = await reasonDialog({
      title: '자산 삭제 (오등록 취소)',
      label: '삭제 사유',
      okLabel: '삭제',
      extra: alertBox('warn',
        '등록 후 24시간 이내, 이력이 등록 하나뿐인 자산만 삭제할 수 있습니다. 삭제 기록은 별도 로그에 남습니다.'),
    });
    if (!reason) return;
    try {
      await api.del(`/assets/${asset.id}?reason=${encodeURIComponent(reason)}`);
      toastOk(`${asset.asset_no} 자산을 삭제했습니다.`);
      go('/assets');
    } catch (e) { toastErr(e.message); }
  }

  return root;
}

function todayStr() {
  const d = new Date(); const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

const kvRow = (label, value) => h('tr', {}, h('th', {}, label), h('td', {}, value));

// ---------------------------------------------------------------- 기본정보
function tabBasic(a) {
  const age = a.purchase_date ? (daysBetween(a.purchase_date, todayStr()) / 365.25) : null;
  const life = a.useful_life_years || 5;
  const aged = age !== null && age >= life;

  return h('div', { class: 'grid c2' },
    h('table', { class: 'kv' },
      kvRow('자산번호', h('span', { class: 'mono' }, a.asset_no)),
      kvRow('자산구분', a.asset_type),
      kvRow('제조사 / 모델', `${a.manufacturer} / ${a.model_name}`),
      kvRow('시리얼번호 (S/N)', h('span', { class: 'mono' }, dash(a.serial_no))),
      kvRow('자산상태', statusBadge(a.status)),
      kvRow('사업장 / 위치', `${a.site} / ${dash(a.location)}`),
      kvRow('자산관리 담당자', dash(a.manager_emp_no))),
    h('table', { class: 'kv' },
      kvRow('구매일', dateOnly(a.purchase_date)),
      kvRow('사용시작일', a.service_start_date
        ? dateOnly(a.service_start_date)
        : h('span', { class: 'muted' }, `${dateOnly(a.purchase_date)} (구매일로 간주)`)),
      kvRow('경과 기간', age === null ? '—' : h('span', {},
        `${age.toFixed(1)}년`,
        aged ? h('span', { class: 'badge amber', style: 'margin-left:6px' }, `내용연수 ${life}년 초과`) : null)),
      kvRow('취득금액', money(a.purchase_amount)),
      kvRow('내용연수', a.useful_life_years ? `${a.useful_life_years}년` : h('span', { class: 'muted' }, '5년 (기본값)')),
      a.disposal_date ? kvRow('폐기일 / 방법', `${dateOnly(a.disposal_date)} / ${dash(a.disposal_method)}`) : null,
      kvRow('비고', h('span', { style: 'white-space:pre-line' }, dash(a.remark))),
      kvRow('등록', `${dateTime(a.created_at)} · ${a.created_by} (${a.created_method})`),
      kvRow('최종 수정', a.updated_at ? `${dateTime(a.updated_at)} · ${dash(a.updated_by)}` : '—')));
}

// ---------------------------------------------------------------- 사용자·배정
function tabAssign(a) {
  const g = a.assignment;
  const cur = g
    ? h('table', { class: 'kv' },
        kvRow('현재 사용자', h('span', {}, h('strong', {}, g.user_name),
          h('span', { class: 'muted' }, ` (사번 ${dash(g.emp_no)})`),
          g.emp_no ? h('a', { href: `#/employees/${encodeURIComponent(g.emp_no)}`, style: 'margin-left:8px' }, '임직원 정보 →') : null)),
        kvRow('소속부서', dash(a.dept_label || g.dept_code)),
        kvRow('직급', dash(g.position_code)),
        kvRow('사업장 · 위치', `${dash(g.site || a.site)} / ${dash(g.location || a.location)}`),
        kvRow('지급일', dateOnly(g.issue_date)),
        kvRow('반납예정일', g.due_return_date
          ? h('span', {}, dateOnly(g.due_return_date),
              g.due_return_date < todayStr() ? h('span', { class: 'badge red', style: 'margin-left:6px' }, '초과') : null)
          : '—'),
        kvRow('사용 기간', `${daysBetween(g.issue_date, todayStr())}일`),
        kvRow('배정 사유', dash(g.assign_reason)))
    : h('div', { class: 'empty' }, '현재 배정된 사용자가 없습니다.');

  // 10-7 사용 이력 뷰
  const past = a.usage_history || [];
  const rows = past.map(u => h('tr', {},
    h('td', {}, u.user_name, h('span', { class: 'muted small' }, ` (${dash(u.emp_no)})`)),
    h('td', {}, dash(u.dept_code)),
    h('td', {}, dateOnly(u.issue_date)),
    h('td', {}, u.return_date ? dateOnly(u.return_date) : h('span', { class: 'badge green' }, '사용 중')),
    h('td', {}, u.return_date ? `${daysBetween(u.issue_date, u.return_date)}일`
      : `${daysBetween(u.issue_date, todayStr())}일`),
    h('td', {}, dash(u.return_reason))));

  return h('div', {},
    h('h3', { class: 'mb8' }, '현재 배정'),
    cur,
    h('h3', { class: 'mb8 mt16' }, '사용 이력'),
    h('div', { class: 'table-wrap' },
      h('table', { class: 'grid-table' },
        h('thead', {}, h('tr', {},
          h('th', {}, '사용자'), h('th', {}, '부서'), h('th', {}, '사용 시작'),
          h('th', {}, '사용 종료'), h('th', {}, '사용 기간'), h('th', {}, '회수 사유'))),
        h('tbody', {}, ...(rows.length ? rows : [emptyRow(6, '배정 이력이 없습니다.')])))));
}

// ---------------------------------------------------------------- 하드웨어
function tabHw(a) {
  return h('div', { class: 'grid c2' },
    h('table', { class: 'kv' },
      kvRow('Hostname', h('span', { class: 'mono' }, dash(a.hostname))),
      kvRow('IP 주소', h('span', { class: 'mono' }, dash(a.ip_address))),
      kvRow('IP 구분', dash(a.ip_type)),
      kvRow('MAC 주소', h('span', { class: 'mono' }, dash(a.mac_address)))),
    h('table', { class: 'kv' },
      kvRow('CPU', dash(a.cpu)),
      kvRow('RAM', a.ram_gb ? `${num(a.ram_gb)} GB` : '—'),
      kvRow('디스크', a.disk_gb ? `${dash(a.disk_type)} ${num(a.disk_gb)} GB` : dash(a.disk_type)),
      kvRow('운영체제', dash(a.os)),
      a.os_eol_date ? kvRow('OS 지원종료일', dateOnly(a.os_eol_date)) : null));
}

// ---------------------------------------------------------------- 이력
async function tabHistory(a) {
  const wrap = h('div', {});
  const listBox = h('div', { class: 'mt16' });
  let filter = '';

  const bar = h('div', { class: 'quick-filters' });
  const paint = () => {
    clear(bar);
    HIST_FILTERS.forEach(([code, label]) => bar.appendChild(h('button', {
      type: 'button', class: filter === code ? 'on' : '',
      onClick: () => { filter = code; paint(); load(); },
    }, label)));
  };

  async function load() {
    clear(listBox);
    listBox.appendChild(h('div', { class: 'loading' }, h('span', { class: 'spinner' })));
    const res = await api.get(`/assets/${a.id}/history${filter ? '?hist_type=' + filter : ''}`);
    clear(listBox);
    if (!res.items.length) {
      listBox.appendChild(h('div', { class: 'empty' }, '해당 조건의 이력이 없습니다.'));
      return;
    }
    const tl = h('div', { class: 'timeline' });
    for (const x of res.items) tl.appendChild(historyItem(x));
    listBox.appendChild(tl);
  }

  paint();
  wrap.append(
    h('div', { class: 'flex wrap' }, bar,
      h('div', { class: 'spacer' }),
      h('span', { class: 'muted small' }, '이력은 수정·삭제할 수 없습니다.')),
    listBox);
  await load();
  return wrap;
}

export function historyItem(x) {
  const changes = (x.changes || []).filter(c => String(c.before ?? '') !== String(c.after ?? ''));
  return h('div', { class: 'tl-item' },
    h('div', { class: 'tl-head' },
      h('span', { class: 'when' }, dateTime(x.occurred_at)),
      h('span', { class: 'badge gray' }, x.hist_type_label),
      h('span', { class: 'who' }, x.actor)),
    x.reason ? h('div', { class: 'tl-reason' }, '사유: ', x.reason) : null,
    x.extra && x.extra.batch_no
      ? h('div', { class: 'tl-reason muted' }, `등록방식: ${x.extra.method || '엑셀'} (배치 ${x.extra.batch_no})`)
      : (x.extra && x.extra.method ? h('div', { class: 'tl-reason muted' }, `등록방식: ${x.extra.method}`) : null),
    changes.length ? h('div', { class: 'tl-changes' }, ...changes.map(c => h('div', { class: 'tl-change' },
      h('span', { class: 'f' }, c.label),
      h('span', {},
        h('span', { class: 'before' }, dash(c.before)),
        h('span', { class: 'arrow' }, '→'),
        h('span', { class: 'after' }, dash(c.after)))))) : null);
}
