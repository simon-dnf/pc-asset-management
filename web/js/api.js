// API 클라이언트. 401은 세션 만료로 간주해 로그인 화면으로 보낸다 (FR-01 01-4, 01-5).

export class ApiError extends Error {
  constructor(message, status, field, detail) {
    super(message);
    this.status = status;
    this.field = field;
    this.detail = detail;
  }
}

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

async function request(method, path, { body, raw = false } = {}) {
  const opts = { method, credentials: 'same-origin', headers: {} };
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }

  let res;
  try {
    res = await fetch('/api' + path, opts);
  } catch {
    throw new ApiError('서버에 연결할 수 없습니다. 네트워크 상태를 확인하세요.', 0);
  }

  if (res.status === 401 && path !== '/me' && path !== '/login') {
    onUnauthorized();
    throw new ApiError('세션이 만료되었습니다. 다시 로그인해 주세요.', 401);
  }
  if (raw) {
    if (!res.ok) throw new ApiError('파일을 내려받지 못했습니다.', res.status);
    return res;
  }

  let data = null;
  try { data = await res.json(); } catch { data = null; }

  if (!res.ok) {
    const msg = (data && (data.error || data.message))
      || (data && Array.isArray(data.detail) && data.detail.map(d => d.msg).join(', '))
      || `요청을 처리하지 못했습니다. (HTTP ${res.status})`;
    throw new ApiError(msg, res.status, data && data.field, data && data.detail);
  }
  return data;
}

export const api = {
  get:  (p) => request('GET', p),
  post: (p, body) => request('POST', p, { body }),
  put:  (p, body) => request('PUT', p, { body }),
  del:  (p) => request('DELETE', p),
  raw:  (p) => request('GET', p, { raw: true }),
  upload: (p, formData) => request('POST', p, { body: formData }),
};

/** 서버가 만든 엑셀 파일을 내려받는다. */
export async function download(path) {
  const res = await api.raw(path);
  const blob = await res.blob();
  const cd = res.headers.get('content-disposition') || '';
  let name = 'download.xlsx';
  const m = /filename\*=UTF-8''([^;]+)/i.exec(cd);
  if (m) name = decodeURIComponent(m[1]);
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  return name;
}
