// 계정별 화면 설정 (03-8 표시 컬럼, 05-8 저장된 검색 조건)
//
// 설정은 서버(`user_pref` 테이블)에 계정 단위로 저장된다.
// 다른 PC·브라우저로 접속해도 같은 설정이 따라오고, 브라우저 데이터를 지워도 남는다.
// 로그인 직후 한 번 내려받아 캐시하고, 이후 화면 렌더링은 캐시를 동기적으로 읽는다.

import { api } from './api.js';

let cache = {};

/** 서버 설정을 불러온다. 로그인 직후 1회 호출. */
export async function loadPrefs() {
  try {
    const res = await api.get('/me/prefs');
    cache = res.prefs || {};
  } catch {
    cache = {};                       // 설정을 못 받아도 기본값으로 화면은 동작해야 한다
  }
  await migrateLocal();
  return cache;
}

export function clearPrefs() { cache = {}; }

/** 캐시에서 동기적으로 읽는다. */
export function pref(key, fallback = null) {
  return Object.prototype.hasOwnProperty.call(cache, key) ? cache[key] : fallback;
}

/** 서버에 저장한다. 실패하면 예외를 던지고 캐시도 되돌린다. */
export async function setPref(key, value) {
  const prev = cache[key];
  const had = Object.prototype.hasOwnProperty.call(cache, key);
  cache[key] = value;
  try {
    await api.put(`/me/prefs/${encodeURIComponent(key)}`, { value });
  } catch (e) {
    if (had) cache[key] = prev; else delete cache[key];
    throw e;
  }
}

/** 설정을 지워 기본값으로 되돌린다. */
export async function resetPref(key) {
  const prev = cache[key];
  const had = Object.prototype.hasOwnProperty.call(cache, key);
  delete cache[key];
  try {
    await api.del(`/me/prefs/${encodeURIComponent(key)}`);
  } catch (e) {
    if (had) cache[key] = prev;
    throw e;
  }
}

// ---------------------------------------------------------------- 기존 브라우저 설정 이관
// 이전 버전은 localStorage에 저장했다. 서버에 값이 없고 브라우저에만 있으면 한 번 올려주고 지운다.
const LEGACY = [
  ['pcams.assetColumns', 'asset_columns'],
  ['pcams.savedSearches', 'saved_searches'],
];

async function migrateLocal() {
  for (const [localKey, prefKey] of LEGACY) {
    if (Object.prototype.hasOwnProperty.call(cache, prefKey)) continue;
    let value = null;
    try {
      const raw = localStorage.getItem(localKey);
      if (raw === null) continue;
      value = JSON.parse(raw);
    } catch {
      continue;
    }
    try {
      await setPref(prefKey, value);
      localStorage.removeItem(localKey);
    } catch {
      // 이관 실패는 조용히 넘긴다. 다음 로그인 때 다시 시도한다.
    }
  }
}
