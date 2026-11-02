/*
 * WEEXIONIC Service Worker
 * Minimal + safe: enables PWA install ("Add to Home screen" -> real
 * fullscreen app). ONLY caches /static/ assets. Everything else
 * (pages, APIs, /bot/ trading data, socket.io) passes through untouched
 * so trading features can never be served stale.
 */
const CACHE = "weexionic-static-v1";
const PRECACHE = [
    "/static/img/icon-192.png",
    "/static/img/icon-512.png",
    "/static/img/weexionic-logo.png"
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE)
            .then((c) => c.addAll(PRECACHE))
            .then(() => self.skipWaiting())
            .catch(() => {})
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
            .then(() => self.clients.claim())
            .catch(() => {})
    );
});

self.addEventListener("fetch", (event) => {
    const req = event.request;
    if (req.method !== "GET") return;               // never touch POST/PUT (trading actions)
    const url = new URL(req.url);
    if (url.origin !== self.location.origin) return; // never touch cross-origin
    if (!url.pathname.startsWith("/static/")) return; // only static assets are cached

    event.respondWith(
        caches.match(req).then((hit) => {
            if (hit) return hit;
            return fetch(req).then((resp) => {
                if (resp.ok) {
                    const copy = resp.clone();
                    caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
                }
                return resp;
            });
        }).catch(() => fetch(req))
    );
});
