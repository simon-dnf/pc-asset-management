// SC-11 통합 이력 조회 (FR-10-5, FR-10-6)

import { api, download } from '../api.js';
import { h, clear, qs, num, dateTime } from '../util.js';
import { pager, toastOk, toastErr, emptyRow } from '../ui.js';
import { go } from '../app.js';
import { historyItem } from './assetDetail.js';

const TYPES = [
  ['CREATE', '등록'], ['ASSIGN', '배정'], ['RETURN', '회수'], ['MOVE', '이동'],
  ['UPDATE', '정보변경'], ['STATUS', '상태변경'], ['DISPOSE', '폐기'],
];

export async function renderHistory(query) {
  const f = { ...query };
  let page = Number(f.page || 1);
  let size = Number(f.size || 20);
  delete f.page; delete f.size; delete f.t;

  const navigate = (patch = {}) => {
    const next = { ...f, ...patch, page, size };
    if (patch.page === undefined && Object.keys(patch).length) next.page = 1;
    go('/history' + qs(next));
  };

  const root = h('div', {});
  root.appendChild(h('div', { class: 'page-head' },
    h('h1', {}, '변경 이력'),
    h('span', { class: 'sub' }, '모든 자산 변경의 시간순 기록. 수정·삭제할 수 없습니다.'),
    h('div', { class: 'actions' },
      h('button', { class: 'btn', onClick: async (e) => {
        e.target.disabled = true;
        try {
          const n = await download('/history/export.xlsx' + qs(f));
          toastOk(`${n} 파일을 내려받았습니다.`);
        } catch (ex) { toastErr(ex.message); }
        finally { e.target.disabled = false; }
      } }, '엑셀 내보내기'))));

  // ---------------- 필터
  const inp = (name, ph, type = 'text') => h('input', { type, name, value: f[name] || '', placeholder: ph });
  const assetNo = inp('asset_no', '자산번호');
  const actor = inp('actor', '변경자');
  const kw = inp('q', '사유·값 검색');
  const from = inp('date_from', '', 'date');
  const to = inp('date_to', '', 'date');

  const selected = new Set((f.hist_type || '').split(',').filter(Boolean));
  const typeBar = h('div', { class: 'quick-filters' },
    h('button', {
      type: 'button', class: selected.size === 0 ? 'on' : '',
      onClick: () => navigate({ hist_type: undefined }),
    }, '전체'),
    ...TYPES.map(([code, label]) => h('button', {
      type: 'button', class: selected.has(code) ? 'on' : '',
      onClick: () => {
        selected.has(code) ? selected.delete(code) : selected.add(code);
        navigate({ hist_type: selected.size ? [...selected].join(',') : undefined });
      },
    }, label)));

  const apply = () => navigate({
    asset_no: assetNo.value.trim() || undefined,
    actor: actor.value.trim() || undefined,
    q: kw.value.trim() || undefined,
    date_from: from.value || undefined,
    date_to: to.value || undefined,
  });
  [assetNo, actor, kw].forEach(el => el.addEventListener('keydown', e => { if (e.key === 'Enter') apply(); }));

  root.appendChild(h('div', { class: 'panel' },
    h('div', { class: 'panel-body' },
      h('div', { class: 'flex wrap mb8' },
        assetNo, actor, kw,
        h('span', { class: 'muted small' }, '기간'), from, h('span', { class: 'muted' }, '~'), to,
        h('button', { class: 'btn primary', onClick: apply }, '검색'),
        h('button', { class: 'btn ghost', onClick: () => go('/history') }, '초기화')),
      typeBar)));

  const listPanel = h('div', { class: 'panel' });
  root.appendChild(listPanel);

  async function load() {
    clear(listPanel);
    listPanel.appendChild(h('div', { class: 'loading' }, h('span', { class: 'spinner' })));
    const data = await api.get('/history' + qs({ ...f, page, size }));
    clear(listPanel);
    listPanel.appendChild(h('div', { class: 'panel-head' },
      h('h2', {}, `${num(data.total)}건`)));

    if (!data.items.length) {
      listPanel.appendChild(h('div', { class: 'empty' }, '조건에 맞는 이력이 없습니다.'));
      return;
    }

    // 자산번호를 함께 보여주기 위해 타임라인 항목에 링크를 덧붙인다.
    const items = data.items.map(x => {
      const item = historyItem(x);
      const head = item.querySelector('.tl-head');
      head.insertBefore(h('a', { href: `#/assets/${x.asset_id}`, class: 'mono' }, x.asset_no),
                        head.children[1]);
      return item;
    });
    listPanel.appendChild(h('div', { class: 'panel-body' },
      h('div', { class: 'timeline' }, ...items)));
    listPanel.appendChild(pager({
      total: data.total, page, size,
      onPage: (p) => { page = p; navigate({ page: p }); },
      onSize: (s) => { size = s; page = 1; navigate({ size: s, page: 1 }); },
    }));
  }

  await load();
  return root;
}
