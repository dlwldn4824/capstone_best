// 앱 파일과 얼굴 인식 모델(/face/mediapipe, 약 13MB)을 캐시해 두 번째 실행부터 오프라인으로 동작한다. 외부 호스트는 쓰지 않는다.
// 범위는 /face/ (등록할 때 scope 로 준다). 이 페이지가 부르는 /assets/…(캐릭터 · 글꼴)도 여기서 받는다.
const APP_CACHE = 'vity-face-app-v1';
const MODEL_CACHE = 'vity-face-model-v1';   // 파일 이름에 버전이 없으니 모델을 바꾸면 이 이름을 올린다
const BASE = new URL(self.registration.scope).pathname;   // '/face/'

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => {
  // 같은 출처의 다른 앱(/check 등) 캐시는 건드리지 않는다
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith('vity-face-') && ![APP_CACHE, MODEL_CACHE].includes(k)).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  // 모델 · wasm · 캐릭터 · 글꼴: cache-first
  if (url.pathname.startsWith(BASE + 'mediapipe/') || url.pathname.startsWith('/assets/')) {
    e.respondWith(caches.open(MODEL_CACHE).then(async c => {
      const hit = await c.match(e.request); if (hit) return hit;
      const res = await fetch(e.request); if (res.ok) c.put(e.request, res.clone()); return res;
    }));
    return;
  }
  if (!url.pathname.startsWith(BASE)) return;
  // 앱 파일: network-first, 오프라인이면 캐시
  e.respondWith(fetch(e.request).then(res => {
    if (res.ok) { const copy = res.clone(); caches.open(APP_CACHE).then(c => c.put(e.request, copy)); }
    return res;
  }).catch(async () => (await caches.match(e.request)) || (await caches.match(BASE)) || Response.error()));
});
