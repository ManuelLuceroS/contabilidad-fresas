/* Solo guarda el cascarón público. La contabilidad se almacena en IndexedDB. */
const CACHE = 'fresas-mobile-__VERSION__';
const ASSETS = __ASSETS__;
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS)));
  // Las actualizaciones esperan al cierre de las ventanas.
});
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith('fresas-mobile-') && key !== CACHE) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  if (event.request.mode === 'navigate' && url.pathname === '/movil/') {
    event.respondWith(caches.open(CACHE).then(cache => cache.match('/movil/')));
  } else if (ASSETS.includes(url.pathname)) {
    event.respondWith(caches.open(CACHE).then(async cache =>
      (await cache.match(event.request)) || fetch(event.request)));
  }
});
