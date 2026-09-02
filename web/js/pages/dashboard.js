// SC-02 대시보드 (FR-11, FR-15)

import { api } from '../api.js';
import { h, num, dateOnly, dateTime, statusBadge, qs } from '../util.js';
import { go } from '../app.js';

const TYPE_COLORS = ['#2e5c8a', '#5b8db8', '#8fb4d4', '#b9d0e5', '#d6e3f0'];

const ACTIONS = [
  { key: 'overdue',     icon: '⏰', label: '반납예정일 초과',    quick: 'overdue',     tone: 'red' },
  { key: 'resigned',    icon: '👤', label: '퇴사자 미회수 자산', quick: 'resigned',    tone: 'red' },
  { key: 'unassigned',  icon: '❓', label: '사용자 미지정 (사용중)', quick: 'unassigned', tone: 'amber' },
  { key: 'long_repair', icon: '🔧', label: '30일 이상 수리 중',  quick: 'long_repair', tone: 'amber' },
  { key: 'to_dispose',  icon: '📦', label: '폐기예정 미처리',    quick: 'to_dispose',  tone: 'amber' },
  { key: 'due_soon',    icon: '📅', label: '7일 내 반납 예정',   quick: 'due_soon',    tone: 'blue' },
  { key: 'aged',        icon: '🕰', label: '내용연수 초과 자산',  quick: 'aged',        tone: 'blue' },
];

export async function renderDashboard(query = {}) {
  const from = query.date_from || '';
  const to = query.date_to || '';
  const d = await api.get('/dashboard' + qs({ date_from: from, date_to: to }));
  const root = h('div', {});
  const periodOn = !!(from || to);

  // 11-8 기간 필터 — 구매일 기준. 기본은 전체.
  const fromInput = h('input', { type: 'date', value: from, style: 'width:auto' });
  const toInput = h('input', { type: 'date', value: to, style: 'width:auto' });
  const applyPeriod = () => go('/dashboard' + qs({
    date_from: fromInput.value || undefined, date_to: toInput.value || undefined,
  }));

  root.appendChild(h('div', { class: 'page-head' },
    h('h1', {}, '대시보드'),
    h('span', { class: 'sub' }, `${d.generated_at} 기준`),
    h('div', { class: 'actions' },
      h('span', { class: 'muted small' }, '구매일 기준'),
      fromInput, h('span', { class: 'muted' }, '~'), toInput,
      h('button', { class: 'btn', onClick: applyPeriod }, '기간 적용'),
      periodOn ? h('button', { class: 'btn ghost', onClick: () => go('/dashboard') }, '전체') : null,
      h('button', { class: 'btn', onClick: () => go('/import') }, '엑셀 가져오기'),
      h('button', { class: 'btn primary', onClick: () => go('/assets/new') }, '+ 자산 등록'))));

  if (periodOn) {
    root.appendChild(h('div', { class: 'alert info' },
      h('strong', {}, `구매일 ${from || '처음'} ~ ${to || '오늘'} 범위의 자산만 집계했습니다. `),
      '아래 [조치 필요] 목록은 지금 처리해야 할 일이므로 기간과 무관하게 전체를 보여줍니다.'));
  }

  // 기간 필터를 목록 화면으로 그대로 넘긴다 (구매일 조건)
  const withPeriod = (filter) => ({
    ...filter,
    purchase_from: from || undefined,
    purchase_to: to || undefined,
  });

  // 11-1 요약 카드
  const card = (label, value, filter, accent) => h('div', {
    class: 'stat-card' + (accent ? ' accent' : ''),
    onClick: () => go('/assets' + qs(withPeriod(filter))),
  }, h('div', { class: 'label' }, label), h('div', { class: 'value' }, num(value)));

  root.appendChild(h('div', { class: 'stat-cards' },
    card('전체 보유', d.summary.holding, {}, true),
    card('사용중', d.summary['사용중'], { status: '사용중' }),
    card('대기', d.summary['대기'], { status: '대기' }),
    card('수리', d.summary['수리'], { status: '수리' }),
    card('폐기예정', d.summary['폐기예정'], { status: '폐기예정' }),
    card('폐기(누적)', d.summary['폐기'], { status: '폐기', include_disposed: 1 })));

  // 11-2 사업장별 / 11-5 조치 필요
  const maxSite = Math.max(1, ...d.sites.map(s => s.total));
  const siteBars = h('div', { class: 'panel-body' },
    ...(d.sites.length ? d.sites.map(s => h('div', { class: 'bar-row' },
      h('div', {}, h('a', { href: '#/assets' + qs(withPeriod({ site: s.site })) }, s.site)),
      h('div', { class: 'bar-track', title:
        `사용중 ${s['사용중']} · 대기 ${s['대기']} · 수리 ${s['수리']} · 폐기예정 ${s['폐기예정']}` },
        h('div', { class: 'bar-fill', style: `width:${Math.round(s.total / maxSite * 100)}%` })),
      h('div', { class: 'n' }, num(s.total))))
      : [h('div', { class: 'empty' }, '등록된 자산이 없습니다.')]));

  const actionList = h('div', { class: 'action-list' });
  for (const a of ACTIONS) {
    const info = d.actions[a.key] || { count: 0 };
    actionList.appendChild(h('div', {
      class: 'action-row' + (info.count ? '' : ' zero'),
      onClick: () => go('/assets' + qs({ quick: a.quick })),
    },
      h('span', { class: 'icon' }, a.icon),
      h('span', { class: 't' }, a.label),
      h('span', { class: 'c' }, info.count ? h('span', { class: `badge ${a.tone}` }, `${num(info.count)}건`) : '0건')));
  }

  root.appendChild(h('div', { class: 'grid c2' },
    h('div', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('h2', {}, '사업장별 보유 현황'),
        h('div', { class: 'right' }, h('span', { class: 'muted small' }, '폐기 제외'))),
      siteBars),
    h('div', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('h2', {}, '조치 필요'),
        h('div', { class: 'right' }, h('span', { class: 'muted small' }, '클릭하면 해당 목록으로 이동'))),
      h('div', { class: 'panel-body tight' }, actionList))));

  // 11-3 부서별 / 11-4 자산구분 비율
  const topDepts = d.depts.slice(0, 10);
  const maxDept = Math.max(1, ...topDepts.map(x => x.count));
  const deptPanel = h('div', { class: 'panel' },
    h('div', { class: 'panel-head' }, h('h2', {}, '부서별 보유 대수'),
      h('div', { class: 'right' }, h('span', { class: 'muted small' }, `상위 10개 / 전체 ${d.depts.length}개`))),
    h('div', { class: 'panel-body' },
      ...(topDepts.length ? topDepts.map(x => h('div', { class: 'bar-row', style: 'grid-template-columns:118px 1fr 52px' },
        h('div', { class: 'small', title: x.dept },
          x.dept === '(미지정)' ? h('span', { class: 'muted' }, x.dept)
            : h('a', { href: '#/assets' + qs(withPeriod({ dept: x.dept })) }, x.dept)),
        h('div', { class: 'bar-track' },
          h('div', { class: 'bar-fill', style: `width:${Math.round(x.count / maxDept * 100)}%` })),
        h('div', { class: 'n' }, num(x.count))))
        : [h('div', { class: 'empty' }, '데이터가 없습니다.')])));

  const typePanel = h('div', { class: 'panel' },
    h('div', { class: 'panel-head' }, h('h2', {}, '자산구분별 비율')),
    h('div', { class: 'panel-body' },
      d.types.length ? h('div', { class: 'donut-wrap' },
        donut(d.types),
        h('div', { class: 'legend' }, ...d.types.map((t, i) => h('div', { class: 'legend-row' },
          h('span', { class: 'legend-dot', style: `background:${TYPE_COLORS[i % TYPE_COLORS.length]}` }),
          h('a', { href: '#/assets' + qs(withPeriod({ asset_type: t.type })) }, t.type),
          h('strong', {}, `${t.ratio}%`),
          h('span', { class: 'muted' }, `(${num(t.count)}대)`)))))
        : h('div', { class: 'empty' }, '데이터가 없습니다.')));

  root.appendChild(h('div', { class: 'grid c2' }, deptPanel, typePanel));

  // 11-7 최근 변경 이력
  const rows = d.recent_history.map(x => h('tr', {
    class: 'clickable', onClick: () => go(`/assets/${x.asset_id}`),
  },
    h('td', { class: 'nowrap muted' }, dateTime(x.occurred_at)),
    h('td', {}, h('span', { class: 'badge gray' }, x.hist_type_label)),
    h('td', { class: 'mono' }, x.asset_no),
    h('td', {}, x.reason || x.summary || '—'),
    h('td', { class: 'nowrap muted' }, x.actor)));

  root.appendChild(h('div', { class: 'panel' },
    h('div', { class: 'panel-head' }, h('h2', {}, '최근 변경 이력'),
      h('div', { class: 'right' }, h('a', { href: '#/history' }, '전체 이력 보기 →'))),
    h('div', { class: 'panel-body tight' },
      h('div', { class: 'table-wrap' },
        h('table', { class: 'grid-table' },
          h('thead', {}, h('tr', {},
            h('th', { style: 'width:130px' }, '일시'),
            h('th', { style: 'width:80px' }, '유형'),
            h('th', { style: 'width:140px' }, '자산번호'),
            h('th', {}, '내용'),
            h('th', { style: 'width:90px' }, '변경자'))),
          h('tbody', {}, ...(rows.length ? rows
            : [h('tr', {}, h('td', { colspan: 5, class: 'empty' }, '최근 7일간 변경 이력이 없습니다.'))])))))));

  return root;
}

/** 외부 차트 라이브러리 없이 conic-gradient로 도넛을 그린다 (NFR-01). */
function donut(types) {
  const total = types.reduce((s, t) => s + t.count, 0) || 1;
  let acc = 0;
  const stops = types.map((t, i) => {
    const from = acc / total * 100;
    acc += t.count;
    const to = acc / total * 100;
    return `${TYPE_COLORS[i % TYPE_COLORS.length]} ${from}% ${to}%`;
  }).join(', ');
  return h('div', {
    style: `width:118px;height:118px;border-radius:50%;flex:0 0 auto;
            background:conic-gradient(${stops});
            mask:radial-gradient(circle, transparent 52%, #000 53%);
            -webkit-mask:radial-gradient(circle, transparent 52%, #000 53%);`,
  });
}
