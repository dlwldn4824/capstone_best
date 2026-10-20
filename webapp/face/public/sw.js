// 앱 파일과 얼굴 인식 모델(/mediapipe, 약 13MB)을 캐시해 두 번째 실행부터 오프라인으로 동작한다. 외부 호스트는 쓰지 않는다.
const APP_CACHE = 'vity-app-v3';
const MODEL_CACHE = 'vity-model-v1';   // 파일 이름에 버전이 없으니 모델을 바꾸면 이 이름을 올린다

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => ![APP_CACHE, MODEL_CACHE].includes(k)).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  // 모델 · wasm: cache-first
  if (url.pathname.startsWith('/mediapipe/')) {
    e.respondWith(caches.open(MODEL_CACHE).then(async c => {
      const hit = await c.match(e.request); if (hit) return hit;
      const res = await fetch(e.request); if (res.ok) c.put(e.request, res.clone()); return res;
    }));
    return;
  }
  // 앱 파일: network-first, 오프라인이면 캐시
  e.respondWith(fetch(e.request).then(res => {
    if (res.ok) { const copy = res.clone(); caches.open(APP_CACHE).then(c => c.put(e.request, copy)); }
    return res;
  }).catch(() => caches.match(e.request).then(hit => hit || caches.match('/index.html'))));
});
