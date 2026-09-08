// Tasas service worker: app shell cached for offline; rates.json network-first with cached fallback.
const VERSION = 'tasas-v4';
const SHELL = ['./', './index.html', './manifest.webmanifest', './icons/icon-192.png', './icons/icon-512.png', './icons/maskable-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return; // third-party APIs: let the page handle failures itself
  if (url.pathname.endsWith('/rates.json')) {
    // network-first, fall back to last cached copy
    e.respondWith(fetch(e.request, { cache: 'no-store' }).then(r => {
      const copy = r.clone(); caches.open(VERSION).then(c => c.put('./rates.json', copy)); return r;
    }).catch(() => caches.match('./rates.json')));
    return;
  }
  // app shell: stale-while-revalidate so updates arrive on the next open
  e.respondWith(caches.match(e.request, { ignoreSearch: true }).then(cached => {
    const net = fetch(e.request).then(r => { if (r.ok) caches.open(VERSION).then(c => c.put(e.request, r.clone())); return r; }).catch(() => cached);
    return cached || net;
  }));
});
