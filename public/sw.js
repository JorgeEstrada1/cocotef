/* Service Worker — Taller 3D App (frontend Vercel).
   Cachea el "app shell" (cache-first) para arranque rápido/offline. Las llamadas
   a la API (otro origen: PythonAnywhere) van siempre a la red. */
const CACHE = "taller3d-app-v2";
const SHELL = ["/", "/index.html", "/app.js", "/config.js", "/manifest.json", "/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;                 // POST/PATCH -> directo a red

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;  // API cross-origin -> red

  // App shell: cache-first con actualización en segundo plano.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).then((resp) => {
        const copia = resp.clone();
        caches.open(CACHE).then((c) => c.put(req, copia)).catch(() => {});
        return resp;
      }).catch(() => caches.match(req).then((r) => r || caches.match("/index.html")))
    );
    return;
  }

  event.respondWith(
    caches.match(req).then((hit) =>
      hit || fetch(req).then((resp) => {
        const copia = resp.clone();
        caches.open(CACHE).then((c) => c.put(req, copia)).catch(() => {});
        return resp;
      })
    )
  );
});

/* ----- Notificaciones (Notification API) -----
   Las alertas locales (timer a cero, filamento < 100 g) se disparan desde la
   página con reg.showNotification(). Aquí manejamos el clic para enfocar la app
   y, opcionalmente, notificaciones push si en el futuro se envían desde el backend. */
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((cs) => {
      for (const c of cs) { if ("focus" in c) return c.focus(); }
      if (self.clients.openWindow) return self.clients.openWindow("/");
    })
  );
});

self.addEventListener("push", (event) => {
  let data = { title: "Taller 3D", body: "Tienes una alerta nueva." };
  try { if (event.data) data = Object.assign(data, event.data.json()); } catch (e) {}
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body, icon: "/icon.svg", badge: "/icon.svg",
      tag: data.tag || "taller3d", vibrate: [120, 60, 120],
    })
  );
});
