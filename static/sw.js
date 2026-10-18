// Minimal service worker for installability.
// Network-first: always fetch fresh from the server, no caching.
self.addEventListener("fetch", (event) => {
    event.respondWith(fetch(event.request));
});
