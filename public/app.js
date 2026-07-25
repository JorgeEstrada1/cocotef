/* App de Producción (frontend Vercel) — consume la API REST del backend Flask. */
const API = window.APP_CONFIG.API_BASE_URL;
const API_KEY = window.APP_CONFIG.API_KEY;
const ESTADOS = ["Diseñando", "Por imprimir", "Imprimiendo", "Terminado", "Entregado"];

const ESTADO_BADGE = {
  "Diseñando": "bg-slate-500/15 text-slate-300 border-slate-500/30",
  "Por imprimir": "bg-indigo-500/15 text-indigo-300 border-indigo-500/30",
  "Imprimiendo": "bg-cyan-500/15 text-cyan-300 border-cyan-500/30",
  "Terminado": "bg-teal-500/15 text-teal-300 border-teal-500/30",
  "Entregado": "bg-green-500/15 text-green-300 border-green-500/30",
};

function headers(json) {
  const h = {};
  if (json) h["Content-Type"] = "application/json";
  if (API_KEY) h["X-API-Key"] = API_KEY;
  return h;
}
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
}
function pad(n) { return String(n).padStart(2, "0"); }

// ---- Navegación entre pestañas ----
const SECCIONES = ["pedidos", "filamentos", "ferias"];
function mostrar(sec) {
  SECCIONES.forEach((s) => {
    const activa = s === sec;
    document.getElementById("sec-" + s).classList.toggle("hidden", !activa);
    document.getElementById("tab-" + s).className =
      "py-3 flex flex-col items-center gap-0.5 " + (activa ? "text-teal-300" : "text-slate-500");
  });
  if (sec === "ferias") cargarFerias();
  window.scrollTo({ top: 0 });
}

// ---- Toast ----
let toastT;
function toast(msg, err) {
  const box = document.querySelector("#toast > div");
  box.textContent = msg;
  box.className = "px-4 py-2 rounded-xl text-sm shadow-2xl border " +
    (err ? "bg-cardh border-rose-500/40 text-rose-200" : "bg-cardh border-teal-500/40 text-teal-200");
  const t = document.getElementById("toast");
  t.classList.remove("hidden");
  clearTimeout(toastT);
  toastT = setTimeout(() => t.classList.add("hidden"), 2600);
}

function estadoConexion(txt, ok) {
  const el = document.getElementById("conexion");
  el.textContent = txt;
  el.className = "text-[11px] " + (ok ? "text-teal-400" : "text-rose-400");
}

// ---- Notificaciones del navegador (timers a cero / stock bajo) ----
const notificados = new Set();   // evita repetir la misma alerta

function pedirPermisoNotif() {
  if (!("Notification" in window)) return;
  if (Notification.permission === "default") {
    try { Notification.requestPermission(); } catch (e) { /* Safari viejo: callback */ }
  }
}

function notificarUnaVez(tag, titulo, cuerpo) {
  if (notificados.has(tag)) return;
  notificados.add(tag);
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  const opts = { body: cuerpo, tag, icon: "/icon.svg", badge: "/icon.svg", vibrate: [120, 60, 120] };
  // Preferimos el Service Worker (funciona con la app en segundo plano).
  if ("serviceWorker" in navigator && navigator.serviceWorker.ready) {
    navigator.serviceWorker.ready.then((reg) => reg.showNotification(titulo, opts)).catch(() => {
      try { new Notification(titulo, opts); } catch (e) {}
    });
  } else {
    try { new Notification(titulo, opts); } catch (e) {}
  }
}

// ---- Modal genérico ----
function abrirModal(titulo, htmlBody) {
  document.getElementById("modal-titulo").textContent = titulo;
  document.getElementById("modal-body").innerHTML = htmlBody;
  document.getElementById("modal").classList.remove("hidden");
}
function cerrarModal() {
  document.getElementById("modal").classList.add("hidden");
  document.getElementById("modal-body").innerHTML = "";
}

// ---- Render de un pedido ----
function tarjetaPedido(p) {
  const foto = p.foto_url
    ? `<img src="${esc(p.foto_url)}" alt="${esc(p.nombre)}" class="w-20 h-20 rounded-xl object-cover border border-edge shrink-0"
            onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'w-20 h-20 rounded-xl bg-base border border-dashed border-edge shrink-0 flex items-center justify-center text-2xl text-slate-600',textContent:'🖼️'}))">`
    : `<div class="w-20 h-20 rounded-xl bg-base border border-dashed border-edge shrink-0 flex items-center justify-center text-2xl text-slate-600">🖼️</div>`;

  const timer = p.fecha_entrega_iso
    ? `<div data-timer data-deadline="${esc(p.fecha_entrega_iso)}T23:59:59" data-nombre="${esc(p.nombre)}"
             class="mt-2 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold border">
         <span data-icon>⏳</span><span data-remaining>—</span></div>`
    : `<div class="mt-2 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs bg-base border border-edge text-slate-500">📅 Sin fecha de entrega</div>`;

  // Monitor de impresión: barra + tiempo restante en vivo cuando está "Imprimiendo".
  const printMon = (p.imprimiendo && p.fin_impresion_iso)
    ? `<div data-print data-fin="${esc(p.fin_impresion_iso)}" data-nombre="${esc(p.nombre)}"
            data-tot="${Math.round((p.horas_totales_impresion || 0) * 3600e3)}"
            class="mt-2 rounded-lg border border-cyan-500/30 bg-cyan-500/5 px-2.5 py-1.5">
         <div class="flex items-center justify-between text-[11px]">
           <span class="text-cyan-300 font-semibold">🖨️ Imprimiendo</span>
           <span data-print-rem class="text-cyan-200 font-mono">—</span>
         </div>
         <div class="mt-1 h-1.5 rounded-full bg-base overflow-hidden">
           <div data-print-bar class="h-full rounded-full bg-gradient-to-r from-cyan-500 to-teal-400" style="width:0%"></div>
         </div>
       </div>`
    : "";

  const opciones = ESTADOS.map((e) => `<option value="${e}">${e}</option>`).join("");
  const badgeCls = ESTADO_BADGE[p.estado] || ESTADO_BADGE["Diseñando"];

  return `<article id="card-${p.id}" data-pid="${p.id}" class="bg-card border border-edge rounded-2xl shadow-lg overflow-hidden">
    <div class="flex gap-3 p-3">
      ${foto}
      <div class="min-w-0 flex-1">
        <div class="flex items-start gap-2">
          <h2 class="font-semibold text-slate-100 truncate flex-1">${esc(p.nombre)}</h2>
          <span data-badge class="text-[11px] px-2 py-0.5 rounded-md border whitespace-nowrap ${badgeCls}">${esc(p.estado)}</span>
        </div>
        <p class="text-xs text-slate-400 truncate mt-0.5">👤 ${esc(p.cliente || "Sin cliente")}</p>
        ${timer}
        ${printMon}
      </div>
    </div>
    <div class="border-t border-edge bg-base/40 px-3 py-2 flex items-center gap-2">
      <button onclick="cambiarEstado(${p.id},'Terminado',this)" class="flex-1 py-2 rounded-lg text-sm font-semibold text-slate-900 bg-gradient-to-r from-teal-500 to-cyan-500 active:opacity-80 transition">✅ Listo</button>
      <button onclick="cambiarEstado(${p.id},'Entregado',this)" class="flex-1 py-2 rounded-lg text-sm font-semibold text-slate-900 bg-gradient-to-r from-green-500 to-emerald-500 active:opacity-80 transition">📦 Entregado</button>
      <button onclick="capturarFoto(${p.id})" title="Foto del resultado"
              class="py-2 px-3 rounded-lg text-sm bg-card border border-edge text-slate-300 active:bg-cardh">📸</button>
      <select onchange="cambiarEstado(${p.id},this.value,this)" class="py-2 px-2 rounded-lg text-xs bg-card border border-edge text-slate-300 max-w-[6rem]">
        <option value="" disabled selected>Más…</option>${opciones}
      </select>
    </div>
    <input type="file" accept="image/*" capture="environment" class="hidden"
           id="cam-${p.id}" onchange="subirFoto(${p.id}, this)">
  </article>`;
}

// ---- Captura y subida de foto desde la cámara del celular ----
function capturarFoto(pid) {
  const input = document.getElementById("cam-" + pid);
  if (input) input.click();
}

async function subirFoto(pid, input) {
  const file = input.files && input.files[0];
  if (!file) return;
  const card = document.getElementById("card-" + pid);
  toast("Subiendo foto…");
  try {
    const fd = new FormData();
    fd.append("foto", file, file.name || "foto.jpg");
    const h = {};
    if (API_KEY) h["X-API-Key"] = API_KEY;
    const r = await fetch(`${API}/api/v1/pedidos/${pid}/foto`, { method: "POST", headers: h, body: fd });
    const data = await r.json();
    if (!data.ok) { toast(data.error || "No se pudo subir la foto.", true); return; }
    // Refresca la miniatura de la tarjeta sin recargar todo.
    const img = card && card.querySelector("img");
    const url = data.foto_url + (data.foto_url.includes("?") ? "&" : "?") + "t=" + Date.now();
    if (img) img.src = url;
    else if (card) {
      const ph = card.querySelector(".flex.gap-3 > div:first-child");
      if (ph) ph.outerHTML = `<img src="${esc(url)}" class="w-20 h-20 rounded-xl object-cover border border-edge shrink-0">`;
    }
    toast("📸 Foto guardada.");
  } catch (e) {
    toast("Error de red al subir la foto.", true);
  } finally {
    input.value = "";
  }
}

function tarjetaFilamento(f) {
  const pct = f.peso_rollo_g ? Math.min(100, Math.max(0, f.stock_gramos / f.peso_rollo_g * 100)) : 0;
  const bajo = f.alerta_bajo_stock;
  const titulo = [f.marca, f.material, f.color].filter(Boolean).join(" · ");
  return `<article class="bg-card border rounded-2xl p-3 ${bajo ? "border-amber-500/40" : "border-edge"}">
    <div class="flex items-center gap-3">
      <span class="w-9 h-9 rounded-full border-2 border-white/10 shrink-0 shadow-inner" style="background:${esc(f.color_hex)}"></span>
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <p class="font-semibold text-slate-100 truncate">${esc(titulo)}</p>
          <span class="ml-auto text-[11px] px-2 py-0.5 rounded-md whitespace-nowrap border ${bajo ? "bg-amber-500/15 text-amber-300 border-amber-500/40" : "bg-teal-500/10 text-teal-300 border-teal-500/30"}">${bajo ? "⚠️ Bajo" : "OK"}</span>
        </div>
        <div class="mt-1 h-2 rounded-full bg-base overflow-hidden">
          <div class="h-full rounded-full ${bajo ? "bg-amber-400" : "bg-gradient-to-r from-teal-500 to-cyan-500"}" style="width:${pct}%"></div>
        </div>
        <p class="mt-1 text-xs text-slate-400">
          <b class="${bajo ? "text-amber-300" : "text-slate-200"}">${Math.round(f.stock_gramos)} g</b>
          <span class="text-slate-600">/ ${Math.round(f.peso_rollo_g || 0)} g</span>
          · ≈ <b class="text-slate-300">${f.rollos_restantes}</b> rollo(s)
        </p>
      </div>
    </div>
  </article>`;
}

// ---- Cambio de estado con Fetch (PATCH) ----
async function cambiarEstado(pid, estado, ctrl) {
  if (!estado) return;
  if (ctrl) ctrl.disabled = true;
  try {
    const r = await fetch(`${API}/api/v1/pedidos/${pid}/estado`, {
      method: "PATCH", headers: headers(true), body: JSON.stringify({ estado }),
    });
    const data = await r.json();
    if (!data.ok) { toast(data.error || "No se pudo actualizar.", true); return; }

    const card = document.getElementById("card-" + pid);
    const badge = card && card.querySelector("[data-badge]");
    const nuevo = data.pedido.estado;
    if (badge) { badge.textContent = nuevo; badge.className = "text-[11px] px-2 py-0.5 rounded-md border whitespace-nowrap " + (ESTADO_BADGE[nuevo] || ""); }
    toast(`«${data.pedido.nombre}» → ${nuevo}`);

    if (card && !data.activo) {                 // salió de producción (Entregado)
      card.classList.add("fade-out");
      setTimeout(() => { card.remove(); ajustarConteo(); }, 420);
    }
  } catch (e) {
    toast("Error de red. Revisa la conexión con el backend.", true);
  } finally {
    if (ctrl) ctrl.disabled = false;
    if (ctrl && ctrl.tagName === "SELECT") ctrl.selectedIndex = 0;
  }
}

function ajustarConteo() {
  const n = document.querySelectorAll("#lista-pedidos article").length;
  document.getElementById("conteo-pedidos").textContent = n;
  if (n === 0) {
    document.getElementById("lista-pedidos").innerHTML =
      `<div class="bg-card border border-dashed border-edge rounded-2xl p-8 text-center text-slate-500">🎉 No hay pedidos pendientes en producción.</div>`;
  }
}

// ---- Timers en vivo ----
function actualizarTimers() {
  const ahora = Date.now();
  const H = 3600e3;
  document.querySelectorAll("[data-timer]").forEach((el) => {
    const diff = new Date(el.dataset.deadline).getTime() - ahora;
    const rem = el.querySelector("[data-remaining]");
    const icon = el.querySelector("[data-icon]");
    let clases, txt, ic;
    if (diff <= 0) {
      const v = Math.abs(diff), d = Math.floor(v / 86400e3), h = Math.floor((v % 86400e3) / H);
      txt = "Vencido " + (d > 0 ? d + "d " : "") + h + "h";
      clases = "bg-rose-500/15 text-rose-300 border-rose-500/40 alerta-roja"; ic = "🔴";
      // Notifica una sola vez cuando el timer de entrega cruza a vencido.
      notificarUnaVez("venc-" + el.dataset.nombre, "⏰ Entrega vencida",
                      `«${el.dataset.nombre}» superó su fecha de entrega.`);
    } else {
      const d = Math.floor(diff / 86400e3), h = Math.floor((diff % 86400e3) / H),
            m = Math.floor((diff % H) / 60e3), s = Math.floor((diff % 60e3) / 1000);
      txt = (d > 0 ? d + "d " : "") + pad(h) + ":" + pad(m) + ":" + pad(s);
      if (diff < 3 * H) { clases = "bg-rose-500/15 text-rose-300 border-rose-500/40 alerta-roja"; ic = "🔥"; }
      else if (diff < 12 * H) { clases = "bg-orange-500/15 text-orange-300 border-orange-500/40"; ic = "⚠️"; }
      else { clases = "bg-green-500/15 text-green-300 border-green-500/40"; ic = "⏳"; }
    }
    rem.textContent = txt;
    if (icon) icon.textContent = ic;
    el.className = "mt-2 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold border " + clases;
  });

  // ---- Monitor de impresión (barra de progreso + notificación al terminar) ----
  document.querySelectorAll("[data-print]").forEach((el) => {
    const fin = new Date(el.dataset.fin).getTime();
    const restante = fin - ahora;
    const bar = el.querySelector("[data-print-bar]");
    const rem = el.querySelector("[data-print-rem]");
    if (restante <= 0) {
      if (bar) bar.style.width = "100%";
      if (rem) rem.textContent = "✅ Lista";
      notificarUnaVez("print-" + el.dataset.nombre, "🖨️ Impresión terminada",
                      `«${el.dataset.nombre}» terminó de imprimir.`);
    } else {
      const h = Math.floor(restante / H), m = Math.floor((restante % H) / 60e3),
            s = Math.floor((restante % 60e3) / 1000);
      if (rem) rem.textContent = (h > 0 ? h + "h " : "") + pad(m) + ":" + pad(s);
      // Progreso relativo al tiempo total estimado guardado en el DOM.
      const tot = Number(el.dataset.tot || 0);
      if (bar && tot > 0) bar.style.width = Math.min(100, Math.max(0, (1 - restante / tot) * 100)) + "%";
    }
  });
}

// ---- Carga de datos ----
async function cargarPedidos() {
  const cont = document.getElementById("lista-pedidos");
  try {
    const r = await fetch(`${API}/api/v1/pedidos-activos`, { headers: headers() });
    const data = await r.json();
    if (!data.ok) throw new Error(data.error || "Error");
    document.getElementById("conteo-pedidos").textContent = data.count;
    cont.innerHTML = data.pedidos.length
      ? data.pedidos.map(tarjetaPedido).join("")
      : `<div class="bg-card border border-dashed border-edge rounded-2xl p-8 text-center text-slate-500">🎉 No hay pedidos pendientes en producción.</div>`;
    actualizarTimers();
    return true;
  } catch (e) {
    cont.innerHTML = `<div class="bg-card border border-rose-500/30 rounded-2xl p-6 text-center text-rose-300 text-sm">
      ⚠️ No se pudo conectar con el backend.<br><span class="text-slate-500 text-xs">${esc(API)}</span></div>`;
    return false;
  }
}

async function cargarFilamentos() {
  const cont = document.getElementById("lista-filamentos");
  try {
    const r = await fetch(`${API}/api/v1/filamentos-stock`, { headers: headers() });
    const data = await r.json();
    if (!data.ok) throw new Error(data.error || "Error");
    cont.innerHTML = data.filamentos.length
      ? data.filamentos.map(tarjetaFilamento).join("")
      : `<div class="bg-card border border-dashed border-edge rounded-2xl p-8 text-center text-slate-500">Sin filamentos registrados.</div>`;
    // Notifica el filamento con stock crítico (< 100 g).
    data.filamentos.forEach((f) => {
      if ((f.stock_gramos || 0) < 100) {
        const etiqueta = [f.material, f.color].filter(Boolean).join(" ");
        notificarUnaVez("fil-" + f.id, "🧵 Filamento por agotarse",
                        `${etiqueta}: quedan ${Math.round(f.stock_gramos)} g.`);
      }
    });
  } catch (e) {
    cont.innerHTML = `<div class="bg-card border border-rose-500/30 rounded-2xl p-6 text-center text-rose-300 text-sm">⚠️ No se pudo cargar el stock.</div>`;
  }
}

async function cargarTodo() {
  const btn = document.getElementById("btn-refrescar");
  btn.classList.add("animate-spin");
  const ok = await cargarPedidos();
  await cargarFilamentos();
  estadoConexion(ok ? "● En línea" : "● Sin conexión", ok);
  btn.classList.remove("animate-spin");
}

// ==========================================================================
//  FERIAS — POS móvil (vender en vivo con un toque)
// ==========================================================================
let feriaActual = null;   // {id, ...} de la feria abierta en el POS

function money(v) { return "Bs. " + Math.round(Number(v || 0)).toLocaleString("es-BO"); }

async function feriasFetch(path, opts) {
  const o = opts || {};
  o.headers = Object.assign(headers(o.body && typeof o.body === "string"), o.headers || {});
  const r = await fetch(`${API}/api/v1/ferias${path}`, o);
  return r.json();
}

// ---- Lista de ferias ----
async function cargarFerias() {
  const cont = document.getElementById("lista-ferias");
  if (!feriaActual) cont.innerHTML = `<div class="skeleton h-24 rounded-2xl"></div>`;
  try {
    const data = await feriasFetch("");
    if (!data.ok) throw new Error(data.error);
    cont.innerHTML = data.ferias.length
      ? data.ferias.map(tarjetaFeria).join("")
      : `<div class="bg-card border border-dashed border-edge rounded-2xl p-8 text-center text-slate-500">Sin ferias todavía. Crea una con ＋ Nueva.</div>`;
  } catch (e) {
    cont.innerHTML = `<div class="bg-card border border-rose-500/30 rounded-2xl p-6 text-center text-rose-300 text-sm">⚠️ No se pudieron cargar las ferias.</div>`;
  }
}

function tarjetaFeria(f) {
  const activa = f.estado === "Activa";
  const badge = activa
    ? "bg-teal-500/15 text-teal-300 border-teal-500/30"
    : "bg-slate-500/15 text-slate-400 border-slate-500/30";
  return `<button onclick="abrirFeriaPOS(${f.id})" class="w-full text-left bg-card border ${activa ? "border-fuchsia-500/30" : "border-edge"} rounded-2xl p-3 active:bg-cardh transition">
    <div class="flex items-center gap-2">
      <span class="text-xl">🎪</span>
      <div class="min-w-0 flex-1">
        <p class="font-semibold text-slate-100 truncate">${esc(f.nombre)}</p>
        <p class="text-xs text-slate-500">${esc(f.fecha_iso || "")} · ${f.unidades_vendidas} vendidas</p>
      </div>
      <span class="text-[11px] px-2 py-0.5 rounded-md border whitespace-nowrap ${badge}">${esc(f.estado)}</span>
    </div>
    <div class="mt-2 flex items-center gap-4 text-sm">
      <span class="text-teal-300 font-bold">${money(f.total_recaudado)}</span>
      <span class="text-slate-500 text-xs">Ganancia <b class="text-emerald-300">${money(f.ganancia_neta)}</b></span>
    </div>
  </button>`;
}

// ---- Crear feria ----
function abrirNuevaFeria() {
  abrirModal("Nueva feria", `
    <input id="nf-nombre" placeholder="Nombre (ej. Feria Navideña)" class="w-full px-3 py-2.5 rounded-lg bg-base border border-edge text-slate-100 placeholder-slate-500">
    <div class="flex gap-2">
      <input id="nf-fecha" type="date" class="flex-1 px-3 py-2.5 rounded-lg bg-base border border-edge text-slate-100">
      <input id="nf-costo" type="number" inputmode="decimal" min="0" placeholder="Costo stand" class="flex-1 px-3 py-2.5 rounded-lg bg-base border border-edge text-slate-100 placeholder-slate-500">
    </div>
    <button onclick="crearFeria(this)" class="w-full py-3 rounded-xl font-semibold text-slate-900 bg-gradient-to-r from-fuchsia-500 to-pink-500 active:opacity-80">Crear feria</button>`);
  const hoy = new Date().toISOString().slice(0, 10);
  document.getElementById("nf-fecha").value = hoy;
}

async function crearFeria(btn) {
  const nombre = document.getElementById("nf-nombre").value.trim();
  if (!nombre) { toast("Ponle un nombre a la feria.", true); return; }
  btn.disabled = true;
  try {
    const data = await feriasFetch("", {
      method: "POST", body: JSON.stringify({
        nombre,
        fecha: document.getElementById("nf-fecha").value || undefined,
        costo_stand: document.getElementById("nf-costo").value || 0,
      }),
    });
    if (!data.ok) { toast(data.error || "No se pudo crear.", true); return; }
    cerrarModal();
    toast("🎪 Feria creada.");
    await cargarFerias();
    abrirFeriaPOS(data.feria.id);
  } catch (e) { toast("Error de red.", true); }
  finally { btn.disabled = false; }
}

// ---- Vista POS ----
async function abrirFeriaPOS(fid) {
  try {
    const data = await feriasFetch("/" + fid);
    if (!data.ok) { toast(data.error || "No se pudo abrir.", true); return; }
    feriaActual = data.feria;
    document.getElementById("ferias-lista-wrap").classList.add("hidden");
    document.getElementById("ferias-pos-wrap").classList.remove("hidden");
    renderPOS(data.feria);
    window.scrollTo({ top: 0 });
  } catch (e) { toast("Error de red.", true); }
}

function cerrarVistaPOS() {
  feriaActual = null;
  document.getElementById("ferias-pos-wrap").classList.add("hidden");
  document.getElementById("ferias-lista-wrap").classList.remove("hidden");
  cargarFerias();
}

function actualizarCaja(f) {
  document.getElementById("pos-caja").textContent = money(f.total_recaudado);
  document.getElementById("pos-ganancia").textContent = money(f.ganancia_neta);
  document.getElementById("pos-vendidas").textContent = f.unidades_vendidas;
}

function renderPOS(f) {
  document.getElementById("pos-nombre").textContent = f.nombre;
  const finalizada = f.estado !== "Activa";
  const estEl = document.getElementById("pos-estado");
  estEl.textContent = f.estado;
  estEl.className = "text-[11px] px-2 py-0.5 rounded-md border " +
    (finalizada ? "bg-slate-500/15 text-slate-400 border-slate-500/30"
                : "bg-teal-500/15 text-teal-300 border-teal-500/30");
  actualizarCaja(f);

  const cont = document.getElementById("pos-productos");
  cont.innerHTML = (f.inventario && f.inventario.length)
    ? f.inventario.map((i) => botonProducto(i, f.id, finalizada)).join("")
    : `<div class="col-span-2 bg-card border border-dashed border-edge rounded-2xl p-8 text-center text-slate-500">
         Sin productos. Agrega stock con ＋ Producto.</div>`;
}

function botonProducto(i, fid, finalizada) {
  const agotado = i.cantidad_restante <= 0;
  const dis = finalizada || agotado;
  return `<button id="prod-${i.id}" ${dis ? "disabled" : `onclick="ventaRapida(${fid},${i.id},this)"`}
      class="relative rounded-2xl p-4 min-h-[110px] flex flex-col justify-between text-left border transition active:scale-95
             ${dis ? "bg-base border-edge opacity-60" : "bg-gradient-to-br from-fuchsia-600/20 to-pink-600/10 border-fuchsia-500/40 active:from-fuchsia-600/40"}">
    <span class="font-semibold text-slate-100 leading-tight break-words">${esc(i.producto_nombre)}</span>
    <div>
      <p class="text-teal-300 font-bold text-lg">${money(i.precio_unitario)}</p>
      <p class="text-[11px] text-slate-400">Quedan <b data-rest class="text-slate-200">${i.cantidad_restante}</b> · vend. <b data-vend>${i.cantidad_vendida}</b></p>
    </div>
    ${agotado ? `<span class="absolute inset-0 flex items-center justify-center text-xs font-bold text-rose-300 bg-base/70 rounded-2xl">AGOTADO</span>` : ""}
  </button>`;
}

// ---- Venta rápida: 1 toque ----
async function ventaRapida(fid, itemId, btn) {
  btn.disabled = true;
  try {
    const data = await feriasFetch(`/${fid}/venta-rapida`, {
      method: "POST", body: JSON.stringify({ inventario_id: itemId }),
    });
    if (!data.ok) { toast(data.error || "No se pudo registrar.", true); return; }
    // Actualiza caja global
    feriaActual.total_recaudado = data.total_recaudado;
    feriaActual.unidades_vendidas = (feriaActual.unidades_vendidas || 0) + data.venta.cantidad;
    actualizarCaja({ total_recaudado: data.total_recaudado, ganancia_neta: data.ganancia_neta,
                     unidades_vendidas: feriaActual.unidades_vendidas });
    // Actualiza el botón
    const rest = btn.querySelector("[data-rest]"), vend = btn.querySelector("[data-vend]");
    if (rest) rest.textContent = data.item.cantidad_restante;
    if (vend) vend.textContent = data.item.cantidad_vendida;
    if (data.item.cantidad_restante <= 0) {
      btn.disabled = true;
      btn.insertAdjacentHTML("beforeend",
        `<span class="absolute inset-0 flex items-center justify-center text-xs font-bold text-rose-300 bg-base/70 rounded-2xl">AGOTADO</span>`);
    }
    // Feedback táctil
    if (navigator.vibrate) navigator.vibrate(40);
    toast(`✅ ${data.venta.producto_nombre} · ${money(data.venta.precio_total)}`);
  } catch (e) { toast("Error de red.", true); }
  finally { if (!btn.disabled) btn.disabled = false; }
}

// ---- Agregar producto al inventario de la feria ----
function abrirAgregarProducto() {
  if (!feriaActual) return;
  abrirModal("Agregar producto", `
    <input id="ap-nombre" placeholder="Producto (ej. Llavero Pikachu)" class="w-full px-3 py-2.5 rounded-lg bg-base border border-edge text-slate-100 placeholder-slate-500">
    <div class="flex gap-2">
      <input id="ap-cant" type="number" inputmode="numeric" min="1" placeholder="Cantidad" class="flex-1 px-3 py-2.5 rounded-lg bg-base border border-edge text-slate-100 placeholder-slate-500">
      <input id="ap-precio" type="number" inputmode="decimal" min="0" placeholder="Precio c/u" class="flex-1 px-3 py-2.5 rounded-lg bg-base border border-edge text-slate-100 placeholder-slate-500">
    </div>
    <button onclick="agregarProducto(this)" class="w-full py-3 rounded-xl font-semibold text-slate-900 bg-gradient-to-r from-teal-500 to-cyan-500 active:opacity-80">Agregar al stock</button>`);
}

async function agregarProducto(btn) {
  const nombre = document.getElementById("ap-nombre").value.trim();
  const cant = document.getElementById("ap-cant").value;
  const precio = document.getElementById("ap-precio").value;
  if (!nombre) { toast("Nombre del producto requerido.", true); return; }
  btn.disabled = true;
  try {
    const data = await feriasFetch(`/${feriaActual.id}/inventario`, {
      method: "POST", body: JSON.stringify({
        producto_nombre: nombre, cantidad_llevada: cant || 0, precio_unitario: precio || 0,
      }),
    });
    if (!data.ok) { toast(data.error || "No se pudo agregar.", true); return; }
    cerrarModal();
    toast("＋ Producto agregado.");
    abrirFeriaPOS(feriaActual.id);   // recarga el POS con el nuevo producto
  } catch (e) { toast("Error de red.", true); }
  finally { btn.disabled = false; }
}

// ---- Cerrar caja (finalizar feria) ----
function cerrarFeria() {
  if (!feriaActual) return;
  abrirModal("Cerrar caja", `
    <p class="text-sm text-slate-400">Se calculará el balance final, se registrará el costo del stand como gasto y el stock no vendido volverá al inventario general. Esta acción no se puede deshacer.</p>
    <button onclick="confirmarCierre(this)" class="w-full py-3 rounded-xl font-semibold text-slate-900 bg-gradient-to-r from-amber-500 to-orange-500 active:opacity-80">🏁 Confirmar cierre</button>
    <button onclick="cerrarModal()" class="w-full py-2.5 rounded-xl text-sm bg-card border border-edge text-slate-300">Cancelar</button>`);
}

async function confirmarCierre(btn) {
  btn.disabled = true;
  try {
    const data = await feriasFetch(`/${feriaActual.id}/cerrar`, { method: "POST", body: "{}" });
    if (!data.ok) { toast(data.error || "No se pudo cerrar.", true); return; }
    const b = data.balance;
    const dev = data.stock_devuelto || [];
    abrirModal("🏁 Feria cerrada", `
      <div class="grid grid-cols-2 gap-2 text-center">
        <div class="bg-base rounded-xl py-3"><p class="text-[10px] text-slate-500 uppercase">Recaudado</p><p class="font-bold text-teal-300 text-lg">${money(b.total_recaudado)}</p></div>
        <div class="bg-base rounded-xl py-3"><p class="text-[10px] text-slate-500 uppercase">Ganancia neta</p><p class="font-bold text-emerald-300 text-lg">${money(b.ganancia_neta)}</p></div>
        <div class="bg-base rounded-xl py-3"><p class="text-[10px] text-slate-500 uppercase">Costo stand</p><p class="font-bold text-slate-200">${money(b.costo_stand)}</p></div>
        <div class="bg-base rounded-xl py-3"><p class="text-[10px] text-slate-500 uppercase">Vendidas</p><p class="font-bold text-slate-100">${b.unidades_vendidas}/${b.unidades_llevadas}</p></div>
      </div>
      <div>
        <p class="text-xs text-slate-400 mb-1">Stock devuelto al inventario:</p>
        ${dev.length
          ? `<ul class="text-sm text-slate-300 space-y-1 max-h-40 overflow-y-auto">${dev.map((d) => `<li class="flex justify-between bg-base rounded-lg px-3 py-1.5"><span class="truncate">${esc(d.producto_nombre)}</span><b>${d.cantidad_devuelta}</b></li>`).join("")}</ul>`
          : `<p class="text-sm text-slate-500">Se vendió todo. 🎉</p>`}
      </div>
      <button onclick="cerrarModal(); cerrarVistaPOS();" class="w-full py-3 rounded-xl font-semibold text-slate-900 bg-gradient-to-r from-teal-500 to-cyan-500">Listo</button>`);
    if (navigator.vibrate) navigator.vibrate([80, 40, 80]);
  } catch (e) { toast("Error de red.", true); }
  finally { btn.disabled = false; }
}

// Esqueleto inicial mientras carga
document.getElementById("lista-pedidos").innerHTML =
  Array.from({ length: 2 }).map(() => `<div class="skeleton h-28 rounded-2xl"></div>`).join("");

cargarTodo();
setInterval(actualizarTimers, 1000);
setInterval(cargarPedidos, 60000);   // auto-refresco cada minuto

// Pide permiso de notificaciones al primer toque del usuario (requisito de gesto en móvil).
document.addEventListener("pointerdown", function pedir() {
  pedirPermisoNotif();
  document.removeEventListener("pointerdown", pedir);
}, { once: true });

// ---- Service Worker (PWA) ----
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
