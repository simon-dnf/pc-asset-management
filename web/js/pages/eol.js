// OS 지원종료일(EOL) 연동 — 설정 > OS 지원종료 관리
//
// endoflife.date 공개 API에서 OS 릴리스별 지원종료일을 받아 자산의 os_eol_date에 반영한다.
// 외부 호출은 [최신 정보 갱신]을 눌렀을 때만 일어난다. 화면 진입 시에는 캐시만 읽는다.

import { api } from '../api.js';
import { h, clear, num, dash, dateTime, qs } from '../util.js';
import { modal, toastOk, toastErr, toastWarn, alertBox, emptyRow, confirmDialog } from '../ui.js';
import { go } from '../app.js';

export async function renderEol() {
  const root = h('div', {});
  const body = h('div', {});

  root.appendChild(h('div', { class: 'page-head' },
    h('h1', {}, 'OS 지원종료 관리'),
    h('span', { class: 'sub' }, '공개 API에서 지원종료일을 받아 자산에 반영합니다.')));
  root.appendChild(body);

  async function load(refresh = false) {
    clear(body);
    body.appendChild(h('div', { class: 'loading' }, h('span', { class: 'spinner' }),
      refresh ? ' 외부에서 최신 정보를 받아오는 중…' : ' 불러오는 중…'));
    let d;
    try {
      d = await api.get('/eol' + qs({ refresh: refresh ? 'true' : undefined }));
    } catch (e) {
      clear(body);
      body.appendChild(h('div', { class: 'panel' }, h('div', { class: 'panel-body' },
        h('div', { class: 'alert error' }, e.message))));
      return;
    }
    clear(body);
    paint(d);
  }

  function paint(d) {
    // ---------------- 연동 상태
    const failed = d.source === 'failed';
    const stale = d.source === 'cache_fallback';
    const errs = Object.entries(d.errors || {});

    if (failed) {
      body.appendChild(alertBox('error',
        '외부 지원종료일 정보를 받아오지 못했고, 사용할 캐시도 없습니다.',
        errs.map(([p, m]) => `${p}: ${m}`).concat([
          `방화벽에서 ${new URL(d.api).host} 도메인이 열려 있는지 확인하세요.`,
          '자산 등록·조회 등 다른 기능은 영향받지 않습니다.'])));
    } else if (stale) {
      body.appendChild(alertBox('warn',
        '외부 연결에 실패해 이전에 받아둔 정보를 표시합니다.',
        errs.map(([p, m]) => `${p}: ${m}`)));
    } else if (errs.length) {
      body.appendChild(alertBox('warn', '일부 제품 정보를 받아오지 못했습니다.',
        errs.map(([p, m]) => `${p}: ${m}`)));
    }

    const sourceLabel = { live: '방금 받아옴', cache: '저장된 정보', cache_fallback: '저장된 정보(연결 실패)', failed: '없음' };
    body.appendChild(h('div', { class: 'panel' },
      h('div', { class: 'panel-head' },
        h('h2', {}, '연동 상태'),
        h('div', { class: 'right' },
          h('button', { class: 'btn sm', onClick: () => load(true) }, '최신 정보 갱신'))),
      h('div', { class: 'panel-body' },
        h('table', { class: 'kv' },
          h('tr', {}, h('th', {}, '데이터 출처'),
            h('td', {}, h('a', { href: 'https://endoflife.date', target: '_blank', rel: 'noreferrer' },
              'endoflife.date'), ' (공개 API)')),
          h('tr', {}, h('th', {}, '마지막 수신'),
            h('td', {}, dateTime(d.fetched_at), ' · ', h('span', { class: 'muted' },
              sourceLabel[d.source] || d.source))),
          h('tr', {}, h('th', {}, '전송 데이터'),
            h('td', {}, h('span', { class: 'badge green' }, '없음'),
              h('span', { class: 'muted small' },
                ' 공개 JSON을 내려받기만 합니다. 사번·성명 등 사내 정보는 전송하지 않습니다.')))))));

    // ---------------- OS별 매핑
    const selects = {};
    const rows = d.items.map(it => {
      const optLabel = (c) => {
        const when = !c.eol ? '종료일 미정'
          : c.expired ? `${c.eol} 지원종료됨`
          : `${c.eol} 종료 예정`;
        return `${c.cycle} — ${when}${c.lts ? ' (LTS)' : ''}`;
      };
      const opts = it.cycles.map(c => h('option', {
        value: c.cycle, selected: c.cycle === it.cycle,
      }, optLabel(c)));
      const sel = h('select', { style: 'min-width:230px' },
        h('option', { value: '' }, '— 반영 안 함 —'), ...opts);
      selects[it.os] = sel;

      const eolCell = !it.cycle ? h('span', { class: 'muted' }, '—')
        : !it.eol ? h('span', { class: 'badge gray' }, '종료일 미정')
        : it.expired ? h('span', { class: 'badge red' }, `${it.eol} 지원종료`)
        : h('span', {}, it.eol);

      return h('tr', {},
        h('td', {}, h('strong', {}, it.os),
          it.is_manual ? h('span', { class: 'badge blue', style: 'margin-left:6px' }, '수동 지정') : null),
        h('td', {}, sel),
        h('td', {}, eolCell),
        h('td', { class: 'num' }, it.asset_count ? `${num(it.asset_count)}대` : h('span', { class: 'muted' }, '—')),
        h('td', { class: 'num' }, it.need_update
          ? h('strong', {}, `${num(it.need_update)}건`)
          : h('span', { class: 'muted' }, '최신')));
    });

    const applyBtn = h('button', { class: 'btn primary', onClick: apply }, '자산에 반영');

    body.appendChild(h('div', { class: 'panel' },
      h('div', { class: 'panel-head' },
        h('h2', {}, 'OS별 기준 릴리스'),
        h('div', { class: 'right muted small' },
          '자동 추천은 "최신 릴리스" 기준입니다. 사내 표준이 다르면 직접 고르세요.')),
      h('div', { class: 'table-wrap' },
        h('table', { class: 'grid-table' },
          h('thead', {}, h('tr', {},
            h('th', { style: 'width:150px' }, '운영체제'),
            h('th', { style: 'width:260px' }, '기준 릴리스'),
            h('th', { style: 'width:170px' }, '지원종료일'),
            h('th', { class: 'right', style: 'width:100px' }, '보유 자산'),
            h('th', { class: 'right', style: 'width:100px' }, '반영 필요'))),
          h('tbody', {}, ...(rows.length ? rows : [emptyRow(5)])))),
      h('div', { class: 'panel-body' },
        d.unmapped_os.length
          ? h('p', { class: 'muted small' },
              `연동 대상이 아닌 코드: ${d.unmapped_os.join(', ')} — 이 OS의 자산은 지원종료일이 채워지지 않습니다.`)
          : null,
        h('div', { class: 'btn-row' }, applyBtn))));

    async function apply() {
      const mapping = {};
      for (const [os, sel] of Object.entries(selects)) {
        if (sel.value) mapping[os] = sel.value;
      }
      if (!Object.keys(mapping).length) { toastErr('반영할 OS를 하나 이상 선택하세요.'); return; }
      const total = d.items.filter(i => mapping[i.os]).reduce((s, i) => s + i.need_update, 0);
      const ok = await confirmDialog(
        `선택한 기준으로 자산 ${total}건의 OS 지원종료일을 갱신합니다.\n각 자산에 정보변경 이력이 남습니다.\n계속할까요?`,
        { title: '자산에 반영', okLabel: '반영' });
      if (!ok) return;

      applyBtn.disabled = true; applyBtn.textContent = '반영 중…';
      try {
        const r = await api.post('/eol/apply', { mapping });
        toastOk(`${r.updated}건의 지원종료일을 갱신했습니다.`);
        (r.detail || []).filter(x => x.skipped)
          .forEach(x => toastWarn(`${x.os}: ${x.skipped}`));
        load();
      } catch (e) {
        toastErr(e.message);
        applyBtn.disabled = false; applyBtn.textContent = '자산에 반영';
      }
    }

    // ---------------- 현황
    body.appendChild(h('div', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('h2', {}, '교체 대상 현황'),
        h('div', { class: 'right muted small' }, '저장된 지원종료일 기준 (외부 연결 불필요)')),
      h('div', { class: 'panel-body tight' }, h('div', { class: 'loading' },
        h('span', { class: 'spinner' })))));
    const summaryPanel = body.lastChild;

    api.get('/eol/summary').then(s => {
      const b = clear(summaryPanel.querySelector('.panel-body'));

      const jump = (quick, label, count, tone) => h('button', {
        class: 'btn', onClick: () => go('/assets' + qs({ quick })),
      }, label + ' ', h('span', { class: `badge ${tone}` }, `${num(count)}건`));

      b.appendChild(h('div', { class: 'flex wrap', style: 'padding:14px 16px' },
        jump('os_eol_expired', '지원종료 자산', s.expired_total, 'red'),
        jump('os_eol_soon', '1년 내 종료', s.soon_total, 'amber')));

      const cell = (v, tone) => v
        ? h('span', { class: `badge ${tone}` }, num(v))
        : h('span', { class: 'muted' }, '—');

      const rows = s.items.map(i => h('tr', {},
        h('td', {}, i.os),
        h('td', { class: 'num' }, num(i.total)),
        h('td', { class: 'num' }, cell(i.expired, 'red')),
        h('td', { class: 'num' }, cell(i.soon, 'amber')),
        h('td', {}, dash(i.earliest_eol))));

      const head = h('tr', {},
        h('th', {}, '운영체제'),
        h('th', { class: 'right' }, '보유'),
        h('th', { class: 'right' }, '지원종료'),
        h('th', { class: 'right' }, '1년 내 종료'),
        h('th', {}, '가장 이른 종료일'));

      const table = h('table', { class: 'grid-table' },
        h('thead', {}, head),
        h('tbody', {}, ...(rows.length ? rows : [emptyRow(5)])));

      b.appendChild(h('div', { class: 'table-wrap' }, table));
    }).catch(() => {
      clear(summaryPanel.querySelector('.panel-body'))
        .appendChild(h('div', { class: 'empty' }, '현황을 불러오지 못했습니다.'));
    });
  }

  await load(false);
  return root;
}
