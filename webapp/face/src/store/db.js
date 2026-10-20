// IndexedDB 저장. 측정 숫자(scans)와 내 정보(kv)만. 영상 · 픽셀 · 랜드마크는 절대 저장하지 않는다.
const DB = 'vity-face', VER = 1;
let dbp = null;

function open() {
  dbp ||= new Promise((res, rej) => {
    const r = indexedDB.open(DB, VER);
    r.onupgradeneeded = () => {
      const db = r.result;
      if (!db.objectStoreNames.contains('scans')) db.createObjectStore('scans', { keyPath: 'id' }).createIndex('ts', 'ts');
      if (!db.objectStoreNames.contains('kv')) db.createObjectStore('kv');
    };
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
  return dbp;
}
async function run(store, mode, fn) {
  const db = await open();
  return new Promise((res, rej) => {
    const t = db.transaction(store, mode);
    const req = fn(t.objectStore(store));
    t.oncomplete = () => res(req?.result);
    t.onerror = () => rej(t.error);
  });
}

export async function persistStorage() {
  try { if (navigator.storage?.persist) return await navigator.storage.persist(); } catch { /* 무시 */ }
  return false;
}

export const putScan = scan => run('scans', 'readwrite', s => s.put(scan));
export const putScans = async scans => { for (const x of scans) await putScan(x); };
export const listScans = async () => ((await run('scans', 'readonly', s => s.getAll())) || []).sort((a, b) => b.ts - a.ts);
export const clearScans = () => run('scans', 'readwrite', s => s.clear());

export const kvGet = k => run('kv', 'readonly', s => s.get(k));
export const kvSet = (k, v) => run('kv', 'readwrite', s => s.put(v, k));

// 내 정보: { consent, nick, height, weight, birth_year }
export async function getProfile() { return { consent: false, nick: '', ...((await kvGet('profile')) || {}) }; }
export async function setProfile(patch) { const p = { ...(await getProfile()), ...patch }; await kvSet('profile', p); return p; }
export async function wipeAll() { await clearScans(); await run('kv', 'readwrite', s => s.clear()); }
