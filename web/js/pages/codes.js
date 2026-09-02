// SC-13 공통코드 관리 (FR-13)

import { api } from '../api.js';
import { h, clear, num, dash, formValues } from '../util.js';
import { modal, toastOk, toastErr, confirmDialog, alertBox, emptyRow, selectField, textField } from '../ui.js';
import { go, invalidateCodes, codes as loadCodes } from '../app.js';

export async function renderCodes(query) {
  const groups = (await api.get('/codes/groups')).items;
  let current = query.group || groups[0].group_code;

  const root = h('div', {});
  root.appendChild(h('div', { class: 'page-head' },
    h('h1', {}, '공통코드 관리'),
    h('span', { class: 'sub' }, '사용 중인 코드는 삭제할 수 없고 비활성화만 가능합니다.')));

  const tabs = h('div', { class: 'tabs' });
  const panel = h('div', { class: 'panel' }, tabs, h('div', { class: 'panel-body tight', id: 'code-body' }));
  root.appendChild(panel);
  const bodyBox = panel.querySelector('#code-body');

  function paintTabs() {
    clear(tabs);
    groups.forEach(g => tabs.appendChild(h('button', {
      type: 'button', class: current === g.group_code ? 'on' : '',
      onClick: () => { current = g.group_code; go(`/codes?group=${g.group_code}`); },
    }, g.label)));
  }

  async function load() {
    clear(bodyBox);
    bodyBox.appendChild(h('div', { class: 'loading' }, h('span', { class: 'spinner' })));
    const data = await api.get(`/codes?group=${encodeURIComponent(current)}`);
    clear(bodyBox);

    const isDept = current === 'DEPT';
    const isStatus = current === 'STATUS';

    const head = h('div', { class: 'panel-head', style: 'border-top:0' },
      h('h2', {}, `${groups.find(g => g.group_code === current).label} · ${num(data.items.length)}개`),
      h('div', { class: 'right' },
        isStatus
          ? h('span', { class: 'muted small' }, '자산상태는 시스템이 사용하는 코드라 추가·삭제할 수 없습니다.')
          : h('button', { class: 'btn sm primary', onClick: () => codeModal(null) }, '+ 코드 추가')));
    bodyBox.appendChild(head);

    const rows = data.items.map(c => h('tr', { class: c.is_active ? '' : 'row-skip' },
      isDept ? h('td', {}, c.parent_code
        ? h('span', { class: 'muted small' }, `└ ${c.parent_code}`)
        : h('span', { class: 'badge blue' }, '사업부')) : null,
      h('td', {}, h('strong', { style: isDept && c.parent_code ? 'padding-left:14px' : '' }, c.label)),
      h('td', { class: 'num' }, c.sort_order),
      h('td', { class: 'num' }, c.usage_count ? `${num(c.usage_count)}건` : h('span', { class: 'muted' }, '—')),
      h('td', {}, c.is_active
        ? h('span', { class: 'badge green' }, '사용')
        : h('span', { class: 'badge gray' }, '비활성')),
      h('td', { class: 'nowrap' },
        isStatus ? h('span', { class: 'muted small' }, '시스템 코드') : h('div', { class: 'flex' },
          h('button', { class: 'btn sm', onClick: () => codeModal(c) }, '수정'),
          h('button', { class: 'btn sm', onClick: () => toggle(c) }, c.is_active ? '비활성화' : '활성화'),
          c.usage_count ? null : h('button', { class: 'btn sm danger', onClick: () => remove(c) }, '삭제')))));

    bodyBox.appendChild(h('div', { class: 'table-wrap' },
      h('table', { class: 'grid-table' },
        h('thead', {}, h('tr', {},
          isDept ? h('th', { style: 'width:110px' }, '계층') : null,
          h('th', {}, '코드값'),
          h('th', { class: 'right', style: 'width:80px' }, '정렬'),
          h('th', { class: 'right', style: 'width:100px' }, '사용 건수'),
          h('th', { style: 'width:80px' }, '상태'),
          h('th', { style: 'width:210px' }, ''))),
        h('tbody', {}, ...(rows.length ? rows : [emptyRow(isDept ? 6 : 5, '등록된 코드가 없습니다.')])))));
  }

  async function toggle(c) {
    if (c.is_active && c.usage_count) {
      const ok = await confirmDialog(
        `'${c.label}'을(를) 사용 중인 데이터가 ${c.usage_count}건 있습니다.\n비활성화하면 신규 입력 선택지에서만 제외되고 기존 데이터는 그대로 유지됩니다.\n계속할까요?`,
        { title: '코드 비활성화', okLabel: '비활성화' });
      if (!ok) return;
    }
    try {
      await api.put(`/codes/${c.id}`, { is_active: !c.is_active });
      invalidateCodes(); await loadCodes(true);
      toastOk(c.is_active ? '비활성화했습니다.' : '활성화했습니다.');
      load();
    } catch (e) { toastErr(e.message); }
  }

  async function remove(c) {
    const ok = await confirmDialog(`'${c.label}' 코드를 삭제합니다. 계속할까요?`,
      { title: '코드 삭제', okLabel: '삭제', danger: true });
    if (!ok) return;
    try {
      await api.del(`/codes/${c.id}`);
      invalidateCodes(); await loadCodes(true);
      toastOk('삭제했습니다.');
      load();
    } catch (e) { toastErr(e.message); }
  }

  async function codeModal(c) {
    const editing = !!c;
    const isDept = current === 'DEPT';
    let parents = [];
    if (isDept) {
      const all = await api.get('/codes?group=DEPT');
      parents = all.items.filter(x => !x.parent_code).map(x => x.label);
    }
    const form = h('form', { class: 'form-grid c2', onSubmit: e => e.preventDefault() },
      textField({ name: 'label', label: '코드값', required: true, value: c ? c.label : '',
        hint: editing ? '사용 중인 코드는 이름을 바꿀 수 없습니다.' : '' }),
      textField({ name: 'sort_order', label: '정렬 순서', type: 'number', value: c ? c.sort_order : '' }),
      isDept ? selectField({ name: 'parent_code', label: '상위 사업부', options: parents,
        value: c ? c.parent_code : '', placeholder: '(사업부로 등록)' }) : null);

    modal({
      title: editing ? '코드 수정' : '코드 추가',
      body: h('div', {},
        isDept ? alertBox('info', '부서는 사업부 > 팀 2단계까지 지원합니다. 상위 사업부를 비우면 사업부로 등록됩니다.') : null,
        form),
      buttons: [
        { label: '취소' },
        { label: '저장', class: 'primary', onClick: async (close, foot) => {
          const btn = foot.querySelector('.btn.primary');
          const v = formValues(form);
          btn.disabled = true; btn.textContent = '저장 중…';
          try {
            if (editing) {
              await api.put(`/codes/${c.id}`, {
                label: v.label, sort_order: v.sort_order ? Number(v.sort_order) : null,
                parent_code: v.parent_code || null,
              });
            } else {
              await api.post('/codes', {
                group_code: current, label: v.label,
                sort_order: v.sort_order ? Number(v.sort_order) : 0,
                parent_code: v.parent_code || null,
              });
            }
            close();
            invalidateCodes(); await loadCodes(true);
            toastOk('저장했습니다.');
            load();
          } catch (ex) {
            toastErr(ex.message);
            btn.disabled = false; btn.textContent = '저장';
          }
        } },
      ],
    });
  }

  paintTabs();
  await load();
  return root;
}
