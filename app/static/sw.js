const CACHE = "live-twin-v2";
const ASSETS = ["/", "/static/styles.css", "/static/app.js", "/manifest.webmanifest"];
self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.map((k) => caches.delete(k)))).then(() =>
      caches.open(CACHE).then((c) => c.addAll(ASSETS))
    )
  );
  self.skipWaiting();
});
self.addEventListener("activate", (e) => {
  e.waitUntil(self.clients.claim());
});
self.addEventListener("fetch", (e) => {
  // network-first for app shell so demos always get fresh JS
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
