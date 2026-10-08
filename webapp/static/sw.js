// 시스템 알림(상단 알림창)을 띄우는 서비스 워커.
// 안드로이드 Chrome 은 페이지에서 new Notification() 을 막고 서비스 워커로만 허용한다.
// 앱이 열려 있는 동안(백그라운드 탭 포함) 서버가 보낸 알림을 알림창으로 올린다.
// 앱을 완전히 닫았을 때까지 받으려면 Web Push(VAPID) 서버가 필요하다 — 아직 없다.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of all) {
      if (new URL(c.url).pathname === new URL(url, self.location.origin).pathname) return c.focus();
    }
    return self.clients.openWindow(url);
  })());
});
