/* Service Worker — Taller 3D (App de Producción)
   Estrategia: network-first para navegación (datos siempre frescos), con
   respaldo a caché cuando no hay conexión; cache-first para estáticos. */
const CACHE = "taller3d-v1";
const PRECACHE = ["/static/icon.svg", "/static/manifest.json"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(PRECACHE)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((claves) =>
      Promise.all(claves.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  // Solo GET del mismo origen; los POST (cambios de estado) van directos a la red.
  if (req.method !== "GET" || new URL(req.url).origin !== self.location.origin) {
    return;
  }

  // Navegación (abrir pantallas): red primero, respaldo a caché de /mobile.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((resp) => {
          const copia = resp.clone();
          caches.open(CACHE).then((c) => c.put(req, copia)).catch(() => {});
          return resp;
        })
        .catch(() => caches.match(req).then((r) => r || caches.match("/mobile")))
    );
    return;
  }

  // Estáticos (icono, manifest, imágenes): caché primero, si no red.
  event.respondWith(
    caches.match(req).then((cacheado) => {
      return (
        cacheado ||
        fetch(req).then((resp) => {
          const copia = resp.clone();
          caches.open(CACHE).then((c) => c.put(req, copia)).catch(() => {});
          return resp;
        })
      );
    })
  );
});
