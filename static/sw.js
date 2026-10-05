// Minimale service worker, puur om aan Chrome/Android's installatie-eisen
// voor een PWA te voldoen. Geen caching: dit is een live handelsdashboard,
// verouderde cijfers uit een cache zijn hier erger dan geen offline-modus.
self.addEventListener("install", function (event) {
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  self.clients.claim();
});

self.addEventListener("fetch", function (event) {
  event.respondWith(fetch(event.request));
});
