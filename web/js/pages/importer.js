// SC-10 엑셀 가져오기 마법사 3단계 (FR-06)

import { api, download } from '../api.js';
import { h, clear, num, dateTime } from '../util.js';
import { modal, toastOk, toastErr, toastWarn, alertBox, confirmDialog, emptyRow } from '../ui.js';
import { go } from '../app.js';

export async function renderImport(query) {
  const kind = query.kind === 'employee' ? 'employee' : 'asset';
  const root = h('div', {});
  const stepBar = h('div', { class: 'steps' });
  const stage = h('div', {});

  const st = {
    kind,
    step: 1,
    token: null,
    filename: '',
    totalRows: 0,
    header: [],
    mapping: {},
    fields: [],
    preview: [],
    dupPolicy: 'skip',
    mode: 'all_or_nothing',
    validation: null,
  };

  function paintSteps() {
    clear(stepBar);
    [['파일 업로드'], ['컬럼 매핑 · 미리보기'], ['검증 결과 · 확정']].forEach(([label], i) => {
      const n = i + 1;
      stepBar.appendChild(h('div', {
        class: 'step' + (st.step === n ? ' on' : '') + (st.step > n ? ' done' : ''),
      }, h('span', { class: 'n' }, st.step > n ? '✓' : n), label));
    });
  }

  function paint() {
    paintSteps();
    clear(stage);
    stage.appendChild(st.step === 1 ? step1() : st.step === 2 ? step2() : step3());
  }

  // ---------------------------------------------------------------- 1단계
  function step1() {
    const fileInput = h('input', { type: 'file', accept: '.xlsx,.xls,.csv,.xlsm' });
    const status = h('div', { class: 'mt8' });

    const kindSel = h('div', { class: 'flex mb16' },
      ...[['asset', '자산 대장'], ['employee', '임직원 명단']].map(([v, l]) =>
        h('label', { class: 'check' },
          h('input', { type: 'radio', name: 'kind', value: v, checked: st.kind === v,
            onChange: () => { st.kind = v; } }), l)));

    const dupSel = h('div', { class: 'flex' },
      ...[['skip', '신규 등록 건너뛰기 (기존 데이터 유지)'], ['update', '기존 정보 갱신']].map(([v, l]) =>
        h('label', { class: 'check' },
          h('input', { type: 'radio', name: 'dup', value: v, checked: st.dupPolicy === v,
            onChange: () => { st.dupPolicy = v; } }), l)));

    async function upload() {
      const file = fileInput.files[0];
      if (!file) { toastErr('업로드할 파일을 선택하세요.'); return; }
      clear(status);
      status.appendChild(h('div', {}, h('span', { class: 'spinner' }), ' 파일을 읽는 중…'));
      const fd = new FormData();
      fd.append('kind', st.kind);
      fd.append('file', file);
      try {
        const r = await api.upload('/imports/upload', fd);
        Object.assign(st, {
          token: r.token, filename: r.filename, totalRows: r.total_rows,
          header: r.header, mapping: r.mapping, fields: r.fields, preview: r.preview, step: 2,
        });
        paint();
      } catch (e) {
        clear(status);
        status.appendChild(alertBox('error', e.message));
      }
    }

    return h('div', { class: 'grid c2' },
      h('div', { class: 'panel' },
        h('div', { class: 'panel-head' }, h('h2', {}, '1. 파일 업로드')),
        h('div', { class: 'panel-body' },
          h('div', { class: 'field' }, h('label', {}, '가져올 데이터'), kindSel),
          h('div', { class: 'field' },
            h('label', {}, '파일 선택'),
            fileInput,
            h('div', { class: 'hint' }, '.xlsx / .xls / .csv · 최대 5,000행 · 10MB')),
          h('div', { class: 'field' },
            h('label', {}, '기존 자산번호(사번)와 중복되는 행 처리'),
            dupSel),
          h('div', { class: 'btn-row mt16' },
            h('button', { class: 'btn primary', onClick: upload }, '업로드하고 다음 →'),
            h('button', { class: 'btn', onClick: async () => {
              try {
                const n = await download(`/imports/template.xlsx?kind=${st.kind}`);
                toastOk(`${n} 파일을 내려받았습니다.`);
              } catch (e) { toastErr(e.message); }
            } }, '표준 템플릿 다운로드')),
          status)),
      h('div', {},
        h('div', { class: 'panel' },
          h('div', { class: 'panel-head' }, h('h2', {}, '가져오기 절차')),
          h('div', { class: 'panel-body small' },
            h('ol', { style: 'padding-left:18px;margin:0' },
              h('li', {}, '표준 템플릿을 내려받아 기존 대장을 정리합니다.'),
              h('li', {}, '헤더가 달라도 2단계에서 직접 매핑할 수 있습니다.'),
              h('li', {}, '전체 행을 검증해 ', h('strong', {}, '행번호 / 컬럼 / 입력값 / 오류사유'), ' 리포트를 제공합니다.'),
              h('li', {}, '오류가 1건이라도 있으면 기본값(All-or-Nothing)에서는 전체가 취소됩니다.'),
              h('li', {}, '등록 후에도 배치 단위로 되돌릴 수 있습니다.')))),
        batchPanel()));
  }

  // ---------------------------------------------------------------- 2단계
  function step2() {
    const rows = st.header.map((col, i) => {
      const sel = h('select', {
        onChange: (e) => { st.mapping[col] = e.target.value || null; },
      },
        h('option', { value: '' }, '— 사용 안 함 —'),
        ...st.fields.map(f => h('option', {
          value: f.field, selected: st.mapping[col] === f.field,
        }, f.header + (f.required ? ' *' : ''))));
      return h('tr', {},
        h('td', { class: 'nowrap' }, h('strong', {}, col)),
        h('td', { class: 'muted small' }, (st.preview[0] && st.preview[0][i]) || ''),
        h('td', { style: 'width:260px' }, sel));
    });

    const missingBox = h('div', {});
    const checkRequired = () => {
      clear(missingBox);
      const mapped = new Set(Object.values(st.mapping).filter(Boolean));
      const missing = st.fields.filter(f => f.required && !mapped.has(f.field)).map(f => f.header);
      if (missing.length) {
        missingBox.appendChild(alertBox('warn', '아직 매핑되지 않은 필수 컬럼이 있습니다.', missing));
      }
      return missing.length === 0;
    };
    checkRequired();
    rows.forEach(r => r.querySelector('select').addEventListener('change', checkRequired));

    const previewTable = h('div', { class: 'preview-scroll' },
      h('table', { class: 'grid-table' },
        h('thead', {}, h('tr', {}, h('th', {}, '#'), ...st.header.map(c => h('th', {}, c)))),
        h('tbody', {}, ...st.preview.map((row, i) =>
          h('tr', {}, h('td', { class: 'muted' }, i + 2), ...row.map(v => h('td', { title: v }, v)))))));

    return h('div', {},
      h('div', { class: 'panel' },
        h('div', { class: 'panel-head' },
          h('h2', {}, '2. 컬럼 매핑'),
          h('div', { class: 'right muted small' },
            `${st.filename} · ${num(st.totalRows)}행`)),
        h('div', { class: 'panel-body' },
          missingBox,
          h('p', { class: 'muted small' }, '엑셀 컬럼을 시스템 필드에 연결합니다. 헤더명이 표준과 다르면 직접 지정하세요. (* 필수)'),
          h('div', { class: 'table-wrap mapping-table' },
            h('table', { class: 'grid-table' },
              h('thead', {}, h('tr', {},
                h('th', {}, '엑셀 컬럼'), h('th', {}, '첫 행 값'), h('th', {}, '시스템 필드'))),
              h('tbody', {}, ...rows))))),
      h('div', { class: 'panel' },
        h('div', { class: 'panel-head' }, h('h2', {}, `미리보기 (첫 ${st.preview.length}행)`)),
        h('div', { class: 'panel-body' }, previewTable)),
      h('div', { class: 'btn-row' },
        h('button', { class: 'btn', onClick: () => { st.step = 1; paint(); } }, '← 이전'),
        h('button', { class: 'btn primary', onClick: async (e) => {
          if (!checkRequired()) { toastErr('필수 컬럼을 모두 매핑해야 검증할 수 있습니다.'); return; }
          const btn = e.target; btn.disabled = true; btn.textContent = '검증 중…';
          try {
            st.validation = await api.post('/imports/validate', {
              token: st.token, mapping: st.mapping, dup_policy: st.dupPolicy,
            });
            st.step = 3; paint();
          } catch (ex) {
            toastErr(ex.message);
            btn.disabled = false; btn.textContent = '전체 검증 →';
          }
        } }, '전체 검증 →')));
  }

  // ---------------------------------------------------------------- 3단계
  function step3() {
    const v = st.validation;
    const c = v.counts;
    const hasError = c.error > 0;

    const summary = h('div', { class: 'stat-cards', style: 'grid-template-columns:repeat(4,1fr)' },
      statCard('총 행', c.total),
      statCard('정상', c.ok, 'green'),
      statCard('오류', c.error, c.error ? 'red' : ''),
      statCard('건너뜀(중복)', c.skip, c.skip ? 'amber' : ''));

    const errorTable = h('div', { class: 'panel' },
      h('div', { class: 'panel-head' },
        h('h2', {}, `오류 ${num(v.error_total)}건 · ${num(c.error)}개 행`),
        h('div', { class: 'right' },
          v.error_total ? h('button', { class: 'btn sm', onClick: async () => {
            try {
              const n = await download(`/imports/errors.xlsx?token=${st.token}`);
              toastOk(`${n} 파일을 내려받았습니다.`);
            } catch (e) { toastErr(e.message); }
          } }, '오류 리포트 받기') : null)),
      h('div', { class: 'panel-body tight' },
        h('div', { class: 'preview-scroll', style: 'border:0' },
          h('table', { class: 'grid-table' },
            h('thead', {}, h('tr', {},
              h('th', { style: 'width:70px' }, '행번호'),
              h('th', { style: 'width:130px' }, '컬럼'),
              h('th', { style: 'width:150px' }, '입력값'),
              h('th', {}, '오류 사유'))),
            h('tbody', {}, ...(v.errors.length
              ? v.errors.map(e => h('tr', { class: 'row-error' },
                  h('td', { class: 'num' }, e.row),
                  h('td', {}, e.column),
                  h('td', { class: 'mono' }, String(e.value ?? '')),
                  h('td', {}, e.message)))
              : [emptyRow(4, '오류가 없습니다.')]))))));

    const warnTable = v.warning_total ? h('div', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('h2', {}, `경고 ${num(v.warning_total)}건`),
        h('div', { class: 'right muted small' }, '등록은 진행되지만 확인이 필요합니다.')),
      h('div', { class: 'panel-body tight' },
        h('div', { class: 'preview-scroll', style: 'border:0;max-height:200px' },
          h('table', { class: 'grid-table' },
            h('thead', {}, h('tr', {}, h('th', { style: 'width:70px' }, '행번호'),
              h('th', { style: 'width:130px' }, '컬럼'), h('th', { style: 'width:150px' }, '입력값'), h('th', {}, '내용'))),
            h('tbody', {}, ...v.warnings.map(e => h('tr', {},
              h('td', { class: 'num' }, e.row), h('td', {}, e.column),
              h('td', { class: 'mono' }, String(e.value ?? '')), h('td', {}, e.message)))))))) : null;

    const modeSel = h('div', { class: 'field' },
      h('label', {}, '반영 모드'),
      ...[['all_or_nothing', 'All-or-Nothing — 오류가 1건이라도 있으면 전체 취소 (권장)'],
          ['partial', '부분 반영 — 정상 행만 등록']].map(([val, label]) =>
        h('label', { class: 'check', style: 'display:flex;margin-bottom:5px' },
          h('input', { type: 'radio', name: 'mode', value: val, checked: st.mode === val,
            onChange: () => { st.mode = val; } }), label)));

    return h('div', {},
      hasError
        ? alertBox('warn', `오류 ${c.error}건이 있습니다.`, [
            '오류 리포트를 내려받아 엑셀에서 수정한 뒤 다시 업로드하는 것을 권장합니다.',
            '지금 진행하려면 반영 모드를 ‘부분 반영’으로 바꾸세요.'])
        : alertBox('ok', `오류 없이 ${c.ok}건을 등록할 수 있습니다.`),
      summary,
      errorTable,
      warnTable,
      h('div', { class: 'panel' },
        h('div', { class: 'panel-head' }, h('h2', {}, '3. 확정')),
        h('div', { class: 'panel-body' },
          modeSel,
          h('p', { class: 'muted small' },
            `중복 처리: ${st.dupPolicy === 'skip' ? '신규 등록 건너뛰기' : '기존 정보 갱신'}`),
          h('div', { class: 'btn-row mt16' },
            h('button', { class: 'btn', onClick: () => { st.step = 2; paint(); } }, '← 매핑 다시'),
            h('button', { class: 'btn primary', onClick: commit }, '등록 실행')))));
  }

  async function commit(e) {
    const btn = e.target;
    if (st.mode === 'partial' && st.validation.counts.error > 0) {
      const ok = await confirmDialog(
        `오류 ${st.validation.counts.error}건을 제외하고 ${st.validation.counts.ok}건만 등록합니다.\n계속할까요?`,
        { title: '부분 반영 확인', okLabel: '등록 실행' });
      if (!ok) return;
    }
    btn.disabled = true; btn.textContent = '등록 중…';
    try {
      const r = await api.post('/imports/commit', {
        token: st.token, mapping: st.mapping, dup_policy: st.dupPolicy, mode: st.mode,
      });
      modal({
        title: '가져오기 완료',
        body: h('div', {},
          alertBox('ok', `배치번호 ${r.batch_no}`),
          h('table', { class: 'kv' },
            h('tr', {}, h('th', {}, '총 행'), h('td', {}, num(r.total))),
            h('tr', {}, h('th', {}, '성공'), h('td', {}, h('strong', {}, num(r.success)))),
            h('tr', {}, h('th', {}, '갱신'), h('td', {}, num(r.updated))),
            h('tr', {}, h('th', {}, '실패'), h('td', {}, num(r.failed))),
            h('tr', {}, h('th', {}, '건너뜀'), h('td', {}, num(r.skipped))))),
        buttons: [
          { label: '가져오기 계속', onClick: (close) => { close(); go('/import?kind=' + st.kind); } },
          { label: st.kind === 'asset' ? '자산 목록으로' : '임직원 목록으로', class: 'primary',
            onClick: (close) => { close(); go(st.kind === 'asset' ? '/assets' : '/employees'); } },
        ],
      });
    } catch (ex) {
      toastErr(ex.message, '등록 실패');
      btn.disabled = false; btn.textContent = '등록 실행';
    }
  }

  // ---------------------------------------------------------------- 배치 이력 (06-12)
  function batchPanel() {
    const box = h('div', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('h2', {}, '최근 가져오기 배치')),
      h('div', { class: 'panel-body tight' }, h('div', { class: 'loading' }, h('span', { class: 'spinner' }))));

    (async () => {
      try {
        const r = await api.get('/imports/batches?limit=10');
        const body = clear(box.querySelector('.panel-body'));
        const rows = r.items.map(b => h('tr', {},
          h('td', { class: 'mono nowrap' }, b.batch_no),
          h('td', { class: 'nowrap muted' }, dateTime(b.created_at)),
          h('td', {}, b.kind === 'asset' ? '자산' : '임직원'),
          h('td', { class: 'num' }, num(b.success_rows)),
          h('td', {}, b.reverted_at
            ? h('span', { class: 'badge gray', title: b.revert_note || '' }, '되돌림')
            : (b.kind === 'asset'
              ? h('button', { class: 'btn sm', onClick: () => revert(b) }, '되돌리기')
              : h('span', { class: 'muted small' }, '—')))));
        body.appendChild(h('div', { class: 'table-wrap' },
          h('table', { class: 'grid-table' },
            h('thead', {}, h('tr', {}, h('th', {}, '배치'), h('th', {}, '일시'), h('th', {}, '종류'),
              h('th', {}, '성공'), h('th', {}, ''))),
            h('tbody', {}, ...(rows.length ? rows : [emptyRow(5, '가져오기 이력이 없습니다.')])))));
      } catch {
        clear(box.querySelector('.panel-body')).appendChild(
          h('div', { class: 'empty' }, '배치 이력을 불러오지 못했습니다.'));
      }
    })();

    async function revert(b) {
      const ok = await confirmDialog(
        `배치 ${b.batch_no}로 등록된 자산을 삭제합니다.\n등록 이후 변경 이력이 생긴 자산은 유지됩니다.\n계속할까요?`,
        { title: '가져오기 되돌리기', okLabel: '되돌리기', danger: true });
      if (!ok) return;
      try {
        const r = await api.post(`/imports/batches/${b.id}/revert`);
        toastOk(r.note, '되돌리기 완료');
        if (r.kept && r.kept.length) toastWarn(`유지된 자산: ${r.kept.join(', ')}`);
        go('/import?kind=' + st.kind + '&t=' + Date.now());
      } catch (e) { toastErr(e.message); }
    }

    return box;
  }

  root.appendChild(h('div', { class: 'page-head' },
    h('h1', {}, '엑셀 가져오기'),
    h('span', { class: 'sub' }, '기존 대장을 템플릿에 맞춰 일괄 등록합니다.')));
  root.append(stepBar, stage);
  paint();
  return root;
}

function statCard(label, value, tone = '') {
  return h('div', { class: 'stat-card', style: 'cursor:default' },
    h('div', { class: 'label' }, label),
    h('div', { class: 'value', style: tone === 'red' ? 'color:#b42318'
      : tone === 'green' ? 'color:#157347' : tone === 'amber' ? 'color:#9a6700' : '' }, num(value)));
}
