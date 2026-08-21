/* App de Producción (frontend Vercel) — consume la API REST del backend Flask. */
const API = window.APP_CONFIG.API_BASE_URL;
const API_KEY = window.APP_CONFIG.API_KEY;
const ESTADOS = ["En espera", "Diseñando", "Por imprimir", "Imprimiendo",
                "Terminado", "Entregado", "Cancelado"];

const ESTADO_BADGE = {
  "En espera": "bg-amber-500/15 text-amber-300 border-amber-500/30",
  "Diseñando": "bg-slate-500/15 text-slate-300 border-slate-500/30",
  "Por imprimir": "bg-indigo-500/15 text-indigo-300 border-indigo-500/30",
  "Imprimiendo": "bg-cyan-500/15 text-cyan-300 border-cyan-500/30",
  "Terminado": "bg-teal-500/15 text-teal-300 border-teal-500/30",
  "Entregado": "bg-green-500/15 text-green-300 border-green-500/30",
  "Cancelado": "bg-rose-500/15 text-rose-400 border-rose-500/30",
};

// Cache de socios (para selects de cobrador / gasto).
let SOCIOS = [];
let PEDIDOS = [];   // último set cargado (para filtrar sin re-pedir)

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
const SECCIONES = ["pedidos", "calendario", "filamentos", "ferias", "mas"];
function mostrar(sec) {
  SECCIONES.forEach((s) => {
    const activa = s === sec;
    document.getElementById("sec-" + s).classList.toggle("hidden", !activa);
    document.getElementById("tab-" + s).className =
      "py-3 flex flex-col items-center gap-0.5 " + (activa ? "text-teal-300" : "text-slate-500");
  });
  if (sec === "ferias") cargarFerias();
  if (sec === "calendario") cargarCalendario();
  if (sec === "mas") document.getElementById("mas-contenido").innerHTML = "";
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
    ${bloqueCobro(p)}
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

// ---- Bloque de cobro / dinero / WhatsApp de una tarjeta ----
function bloqueCobro(p) {
  const opcSocios = ['<option value="">¿Quién cobra?</option>']
    .concat(SOCIOS.map((u) =>
      `<option value="${u.id}" ${p.cobrador && p.cobrador.id === u.id ? "selected" : ""}>${esc(u.nombre)}</option>`))
    .join("");

  // Estado del saldo del cliente
  const saldoTxt = p.pagado_completo
    ? `<span class="px-2 py-0.5 rounded-md bg-teal-500/10 text-teal-300 border border-teal-500/30">✓ Pagado</span>`
    : (p.saldo_pendiente > 0
        ? `<span class="px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-300 border border-amber-500/30">Debe ${money(p.saldo_pendiente)}</span>`
        : "");

  // Botón de deuda interna: "me pagó / saldado"
  let saldar = "";
  if (p.cobrador && (p.precio_total || 0) > 0) {
    saldar = p.saldado
      ? `<button onclick="saldarPedido(${p.id},false)" class="px-2 py-0.5 rounded-md bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">✔ ${esc(p.cobrador.nombre)} me pagó</button>`
      : `<button onclick="saldarPedido(${p.id},true)" class="px-2 py-0.5 rounded-md bg-fuchsia-500/15 text-fuchsia-300 border border-fuchsia-500/30">💵 ${esc(p.cobrador.nombre)} me pagó</button>`;
  }

  // WhatsApp: avisar al cliente
  const wa = p.telefono
    ? `<button onclick="avisarWhatsApp(${p.id})" class="px-2 py-0.5 rounded-md bg-green-500/15 text-green-300 border border-green-500/30">📲 Avisar</button>`
    : "";

  const ganancia = (p.precio_total || 0) > 0
    ? `<span class="text-slate-500">📈 ${money(p.ganancia)}</span>` : "";

  return `<div class="px-3 pb-2 flex flex-wrap items-center gap-1.5 text-[11px]">
    <span class="font-semibold text-slate-300">💰 ${money(p.precio_total)}</span>
    ${saldoTxt}${ganancia}
    <select onchange="setCobrador(${p.id}, this.value)"
            class="ml-auto py-1 px-1.5 rounded-md bg-card border border-edge text-slate-300 text-[11px]">${opcSocios}</select>
    ${saldar}${wa}
  </div>`;
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

    const nuevo = data.pedido.estado;
    toast(`«${data.pedido.nombre}» → ${nuevo}`);

    // Entregado/Cancelado: en vez de borrar la tarjeta, recargamos para que
    // se reordene al fondo y los pendientes suban.
    if (!data.activo) {
      const card = document.getElementById("card-" + pid);
      if (card) card.classList.add("fade-out");
      setTimeout(cargarPedidos, 300);
    } else {
      const card = document.getElementById("card-" + pid);
      const badge = card && card.querySelector("[data-badge]");
      if (badge) { badge.textContent = nuevo; badge.className = "text-[11px] px-2 py-0.5 rounded-md border whitespace-nowrap " + (ESTADO_BADGE[nuevo] || ""); }
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
      // Recordatorio: avisa una vez cuando falta menos de 24 h para la entrega.
      if (diff < 24 * H) {
        notificarUnaVez("prox-" + el.dataset.nombre, "📅 Entrega mañana",
                        `«${el.dataset.nombre}» se entrega en menos de 24 h.`);
      }
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
    if (!SOCIOS.length) await cargarSocios();
    const r = await fetch(`${API}/api/v1/pedidos-activos`, { headers: headers() });
    const data = await r.json();
    if (!data.ok) throw new Error(data.error || "Error");
    PEDIDOS = data.pedidos;
    document.getElementById("conteo-pedidos").textContent = data.count;
    renderPedidos();
    renderColaEspera();
    cargarDeuda();
    return true;
  } catch (e) {
    cont.innerHTML = `<div class="bg-card border border-rose-500/30 rounded-2xl p-6 text-center text-rose-300 text-sm">
      ⚠️ No se pudo conectar con el backend.<br><span class="text-slate-500 text-xs">${esc(API)}</span></div>`;
    return false;
  }
}

// Pinta la lista aplicando el buscador y el filtro de estado.
function renderPedidos() {
  const cont = document.getElementById("lista-pedidos");
  const q = (document.getElementById("buscar-pedido")?.value || "").trim().toLowerCase();
  const est = document.getElementById("filtro-estado")?.value || "";
  let lista = PEDIDOS;
  // Los "En espera" se muestran en la cola de arriba: no duplicarlos aquí
  // (salvo que el usuario filtre explícitamente por ese estado).
  if (est !== "En espera") lista = lista.filter((p) => p.estado !== "En espera");
  if (q) lista = lista.filter((p) =>
    (p.nombre || "").toLowerCase().includes(q) || (p.cliente || "").toLowerCase().includes(q));
  if (est) lista = lista.filter((p) => p.estado === est);
  cont.innerHTML = lista.length
    ? lista.map(tarjetaPedido).join("")
    : `<div class="bg-card border border-dashed border-edge rounded-2xl p-8 text-center text-slate-500">🎉 Nada por aquí.</div>`;
  actualizarTimers();
}
function filtrarPedidos() { renderPedidos(); }

// Cola de "En espera": clientes esperando respuesta de diseño.
function renderColaEspera() {
  const box = document.getElementById("cola-espera");
  const cola = PEDIDOS.filter((p) => p.estado === "En espera");
  if (!cola.length) { box.classList.add("hidden"); box.innerHTML = ""; return; }
  box.classList.remove("hidden");
  box.innerHTML = `<div class="bg-amber-500/5 border border-amber-500/30 rounded-2xl p-3">
    <p class="text-sm font-semibold text-amber-300 mb-2">🎨 Esperando respuesta de diseño (${cola.length})</p>
    <div class="space-y-1.5">${cola.map((p) => `
      <div class="flex items-center gap-2 text-xs">
        <span class="flex-1 truncate text-slate-200">${esc(p.nombre)} <span class="text-slate-500">· ${esc(p.cliente || "sin cliente")}</span></span>
        <button onclick="cambiarEstado(${p.id},'Diseñando',this)" class="px-2 py-1 rounded-md bg-teal-500/15 text-teal-300 border border-teal-500/30">▶ Diseñar</button>
      </div>`).join("")}</div></div>`;
}

// Banner de deuda interna entre socios.
async function cargarDeuda() {
  const box = document.getElementById("banner-deuda");
  try {
    const r = await fetch(`${API}/api/v1/resumen-deuda`, { headers: headers() });
    const d = await r.json();
    if (!d.ok || !d.detalle.length) { box.classList.add("hidden"); box.innerHTML = ""; return; }
    box.classList.remove("hidden");
    box.innerHTML = `<div class="bg-fuchsia-500/5 border border-fuchsia-500/30 rounded-2xl p-3 text-sm">
      <p class="font-semibold text-fuchsia-300 mb-1">💸 Deuda entre socios</p>
      ${d.detalle.map((x) => `<p class="text-slate-300 text-xs"><b>${esc(x.cobrador)}</b> te debe <b class="text-fuchsia-300">${money(x.debe)}</b> <span class="text-slate-500">(${x.pedidos} pedido${x.pedidos !== 1 ? "s" : ""})</span></p>`).join("")}
    </div>`;
  } catch (e) { box.classList.add("hidden"); }
}

async function cargarSocios() {
  try {
    const r = await fetch(`${API}/api/v1/usuarios`, { headers: headers() });
    const d = await r.json();
    if (d.ok) SOCIOS = d.usuarios;
  } catch (e) { /* sin socios: los selects quedan vacíos */ }
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

// Conserva los decimales cuando existen (Bs. 120.50) y los omite si es entero.
function money(v) {
  const n = Number(v || 0);
  const dec = Number.isInteger(n) ? 0 : 2;
  return "Bs. " + n.toLocaleString("es-BO", { minimumFractionDigits: dec, maximumFractionDigits: dec });
}

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
    <input id="nf-fecha" type="date" class="w-full px-3 py-2.5 rounded-lg bg-base border border-edge text-slate-100">
    <div class="flex gap-2">
      <input id="nf-costo" type="number" inputmode="decimal" min="0" placeholder="Costo stand" class="flex-1 px-3 py-2.5 rounded-lg bg-base border border-edge text-slate-100 placeholder-slate-500">
      <input id="nf-material" type="number" inputmode="decimal" min="0" placeholder="Costo material" class="flex-1 px-3 py-2.5 rounded-lg bg-base border border-edge text-slate-100 placeholder-slate-500">
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
        costo_material: document.getElementById("nf-material").value || 0,
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
  const set = (id, val) => { const el = document.getElementById(id); if (el && val !== undefined) el.textContent = val; };
  set("pos-caja", money(f.total_recaudado));
  if (f.total_proyectado !== undefined) set("pos-proyectado", money(f.total_proyectado));
  if (f.valor_restante_mesa !== undefined) set("pos-mesa", money(f.valor_restante_mesa));
  set("pos-ganancia", money(f.ganancia_neta));
  set("pos-vendidas", f.unidades_vendidas);
  if (f.unidades_merma !== undefined) set("pos-mermas", f.unidades_merma);
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
  // Íconos táctiles de edición/borrado (ocultos si la feria está finalizada).
  const acciones = finalizada ? "" : `
    <div class="absolute top-1.5 right-1.5 flex gap-1">
      <button onclick="editarProducto(${i.id})" title="Editar"
              class="w-7 h-7 rounded-lg bg-base/80 border border-edge text-slate-300 text-xs active:bg-cardh flex items-center justify-center">✏️</button>
      <button onclick="borrarProducto(${i.id})" title="Eliminar"
              class="w-7 h-7 rounded-lg bg-base/80 border border-rose-500/40 text-rose-300 text-xs active:bg-cardh flex items-center justify-center">🗑️</button>
    </div>`;
  const ventaArea = dis
    ? `<div id="prod-${i.id}" class="rounded-2xl p-4 pt-9 min-h-[120px] flex flex-col justify-between text-left border bg-base border-edge opacity-60">`
    : `<div id="prod-${i.id}" onclick="ventaRapida(${fid},${i.id},this)"
           class="rounded-2xl p-4 pt-9 min-h-[120px] flex flex-col justify-between text-left border transition active:scale-95 cursor-pointer bg-gradient-to-br from-fuchsia-600/20 to-pink-600/10 border-fuchsia-500/40 active:from-fuchsia-600/40">`;
  return `<div class="relative">
    ${acciones}
    ${ventaArea}
      <span class="font-semibold text-slate-100 leading-tight break-words pr-1">${esc(i.producto_nombre)}</span>
      <div>
        <p class="text-teal-300 font-bold text-lg">${money(i.precio_unitario)}</p>
        <p class="text-[11px] text-slate-400">Quedan <b data-rest class="text-slate-200">${i.cantidad_restante}</b> · vend. <b data-vend>${i.cantidad_vendida}</b></p>
      </div>
      ${agotado ? `<span class="absolute inset-0 flex items-center justify-center text-xs font-bold text-rose-300 bg-base/70 rounded-2xl pointer-events-none">AGOTADO</span>` : ""}
    </div>
  </div>`;
}

// ---- Venta rápida: 1 toque ----
async function ventaRapida(fid, itemId, btn) {
  if (btn.dataset.busy) return;      // evita doble toque accidental
  btn.dataset.busy = "1";
  try {
    const data = await feriasFetch(`/${fid}/venta-rapida`, {
      method: "POST", body: JSON.stringify({ inventario_id: itemId }),
    });
    if (!data.ok) { toast(data.error || "No se pudo registrar.", true); return; }
    aplicarTotalesFeria(data);
    // Actualiza el ítem tocado
    const rest = btn.querySelector("[data-rest]"), vend = btn.querySelector("[data-vend]");
    if (rest) rest.textContent = data.item.cantidad_restante;
    if (vend) vend.textContent = data.item.cantidad_vendida;
    if (data.item.cantidad_restante <= 0) marcarAgotado(btn);
    if (navigator.vibrate) navigator.vibrate(40);
    toast(`✅ ${data.venta.producto_nombre} · ${money(data.venta.precio_total)}`);
  } catch (e) { toast("Error de red.", true); }
  finally { delete btn.dataset.busy; }
}

// Aplica los totales que devuelven venta-rápida / combo / merma a la caja y a feriaActual.
function aplicarTotalesFeria(data) {
  if (!feriaActual) return;
  ["total_recaudado", "total_proyectado", "valor_restante_mesa", "ganancia_neta",
   "unidades_vendidas", "unidades_merma"].forEach((k) => {
    if (data[k] !== undefined) feriaActual[k] = data[k];
  });
  actualizarCaja(feriaActual);
}

function marcarAgotado(el) {
  el.onclick = null;
  el.classList.add("opacity-60");
  if (!el.querySelector(".etq-agotado")) {
    el.insertAdjacentHTML("beforeend",
      `<span class="etq-agotado absolute inset-0 flex items-center justify-center text-xs font-bold text-rose-300 bg-base/70 rounded-2xl pointer-events-none">AGOTADO</span>`);
  }
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

// ---- Editar producto (precio / cantidad) ----
function editarProducto(itemId) {
  if (!feriaActual) return;
  const it = (feriaActual.inventario || []).find((x) => x.id === itemId);
  if (!it) return;
  abrirModal("Editar producto", `
    <input id="ed-nombre" value="${esc(it.producto_nombre)}" class="w-full px-3 py-2.5 rounded-lg bg-base border border-edge text-slate-100">
    <div class="flex gap-2">
      <label class="flex-1 text-xs text-slate-400">Cantidad llevada
        <input id="ed-cant" type="number" inputmode="numeric" min="0" value="${it.cantidad_llevada}" class="mt-1 w-full px-3 py-2.5 rounded-lg bg-base border border-edge text-slate-100">
      </label>
      <label class="flex-1 text-xs text-slate-400">Precio c/u
        <input id="ed-precio" type="number" inputmode="decimal" min="0" value="${it.precio_unitario}" class="mt-1 w-full px-3 py-2.5 rounded-lg bg-base border border-edge text-slate-100">
      </label>
    </div>
    <p class="text-[11px] text-slate-500">Ya movidas (vendidas + mermas): <b>${(it.cantidad_vendida || 0) + (it.cantidad_merma || 0)}</b>. La cantidad no puede bajar de ahí.</p>
    <button onclick="guardarProducto(${itemId}, this)" class="w-full py-3 rounded-xl font-semibold text-slate-900 bg-gradient-to-r from-teal-500 to-cyan-500 active:opacity-80">Guardar cambios</button>`);
}

async function guardarProducto(itemId, btn) {
  btn.disabled = true;
  try {
    const data = await feriasFetch(`/${feriaActual.id}/inventario/${itemId}`, {
      method: "PATCH", body: JSON.stringify({
        producto_nombre: document.getElementById("ed-nombre").value.trim(),
        cantidad_llevada: document.getElementById("ed-cant").value,
        precio_unitario: document.getElementById("ed-precio").value,
      }),
    });
    if (!data.ok) { toast(data.error || "No se pudo editar.", true); return; }
    cerrarModal();
    toast("✏️ Producto actualizado.");
    abrirFeriaPOS(feriaActual.id);
  } catch (e) { toast("Error de red.", true); }
  finally { btn.disabled = false; }
}

// ---- Borrar producto ----
function borrarProducto(itemId) {
  if (!feriaActual) return;
  const it = (feriaActual.inventario || []).find((x) => x.id === itemId);
  if (!it) return;
  abrirModal("Eliminar producto", `
    <p class="text-sm text-slate-400">¿Quitar «<b class="text-slate-200">${esc(it.producto_nombre)}</b>» de esta feria? Esta acción no se puede deshacer.</p>
    <button onclick="confirmarBorrado(${itemId}, this)" class="w-full py-3 rounded-xl font-semibold text-slate-900 bg-gradient-to-r from-rose-500 to-red-500 active:opacity-80">🗑️ Sí, eliminar</button>
    <button onclick="cerrarModal()" class="w-full py-2.5 rounded-xl text-sm bg-card border border-edge text-slate-300">Cancelar</button>`);
}

async function confirmarBorrado(itemId, btn) {
  btn.disabled = true;
  try {
    const data = await feriasFetch(`/${feriaActual.id}/inventario/${itemId}`, { method: "DELETE" });
    if (!data.ok) { toast(data.error || "No se pudo eliminar.", true); return; }
    cerrarModal();
    toast("🗑️ Producto eliminado.");
    abrirFeriaPOS(feriaActual.id);
  } catch (e) { toast("Error de red.", true); }
  finally { btn.disabled = false; }
}

// ---- Combo / descuento rápido ----
function abrirCombo() {
  if (!feriaActual) return;
  const inv = (feriaActual.inventario || []).filter((i) => i.cantidad_restante > 0);
  if (!inv.length) { toast("No hay stock disponible para armar un combo.", true); return; }
  const filas = inv.map((i) => `
    <label class="flex items-center gap-2 bg-base rounded-lg px-3 py-2">
      <input type="checkbox" class="combo-chk w-4 h-4 accent-fuchsia-500" data-id="${i.id}" data-nombre="${esc(i.producto_nombre)}">
      <span class="flex-1 text-sm text-slate-200 truncate">${esc(i.producto_nombre)} <span class="text-slate-500">(${i.cantidad_restante})</span></span>
      <input type="number" inputmode="numeric" min="1" value="1" class="combo-cant w-14 px-2 py-1 rounded-md bg-card border border-edge text-slate-100 text-center text-sm">
    </label>`).join("");
  abrirModal("🎁 Combo / descuento", `
    <p class="text-xs text-slate-400">Marca los productos, ajusta cantidades y pon el precio total pactado (ej. 3 Llaveros por 20 Bs).</p>
    <div class="space-y-2 max-h-52 overflow-y-auto">${filas}</div>
    <input id="combo-precio" type="number" inputmode="decimal" min="0" placeholder="Precio total del combo (Bs.)" class="w-full px-3 py-2.5 rounded-lg bg-base border border-edge text-slate-100 placeholder-slate-500">
    <input id="combo-nota" placeholder="Nota (opcional)" class="w-full px-3 py-2.5 rounded-lg bg-base border border-edge text-slate-100 placeholder-slate-500">
    <button onclick="registrarCombo(this)" class="w-full py-3 rounded-xl font-semibold text-slate-900 bg-gradient-to-r from-violet-500 to-fuchsia-500 active:opacity-80">Cobrar combo</button>`);
}

async function registrarCombo(btn) {
  const items = [];
  let descNombres = [];
  document.querySelectorAll(".combo-chk").forEach((chk) => {
    if (chk.checked) {
      const cant = parseInt(chk.closest("label").querySelector(".combo-cant").value) || 1;
      items.push({ inventario_id: Number(chk.dataset.id), cantidad: Math.max(cant, 1) });
      descNombres.push(`${cant}× ${chk.dataset.nombre}`);
    }
  });
  if (!items.length) { toast("Selecciona al menos un producto.", true); return; }
  const precio = document.getElementById("combo-precio").value;
  if (precio === "" || Number(precio) < 0) { toast("Pon el precio total del combo.", true); return; }
  btn.disabled = true;
  try {
    const data = await feriasFetch(`/${feriaActual.id}/venta-combo`, {
      method: "POST", body: JSON.stringify({
        items, precio_total: precio,
        descripcion: descNombres.length > 1 ? "Combo: " + descNombres.join(" + ") : undefined,
        nota: document.getElementById("combo-nota").value.trim() || undefined,
      }),
    });
    if (!data.ok) { toast(data.error || "No se pudo cobrar.", true); return; }
    cerrarModal();
    if (navigator.vibrate) navigator.vibrate(40);
    toast(`🎁 Combo cobrado · ${money(data.venta.precio_total)}`);
    abrirFeriaPOS(feriaActual.id);   // refresca botones con el stock nuevo
  } catch (e) { toast("Error de red.", true); }
  finally { btn.disabled = false; }
}

// ---- Merma / muestra gratis ----
function abrirMerma() {
  if (!feriaActual) return;
  const inv = (feriaActual.inventario || []).filter((i) => i.cantidad_restante > 0);
  if (!inv.length) { toast("No hay stock para registrar merma.", true); return; }
  const opciones = inv.map((i) => `<option value="${i.id}">${esc(i.producto_nombre)} (${i.cantidad_restante})</option>`).join("");
  abrirModal("📉 Merma / muestra gratis", `
    <p class="text-xs text-slate-400">Descuenta unidades del stock SIN sumar dinero a la caja (piezas dañadas, muestras o canjes).</p>
    <select id="mer-item" class="w-full px-3 py-2.5 rounded-lg bg-base border border-edge text-slate-100">${opciones}</select>
    <div class="flex gap-2">
      <input id="mer-cant" type="number" inputmode="numeric" min="1" value="1" class="w-24 px-3 py-2.5 rounded-lg bg-base border border-edge text-slate-100 text-center">
      <input id="mer-motivo" placeholder="Motivo (opcional)" class="flex-1 px-3 py-2.5 rounded-lg bg-base border border-edge text-slate-100 placeholder-slate-500">
    </div>
    <button onclick="registrarMerma(this)" class="w-full py-3 rounded-xl font-semibold text-slate-900 bg-gradient-to-r from-rose-500 to-red-500 active:opacity-80">Registrar merma</button>`);
}

async function registrarMerma(btn) {
  btn.disabled = true;
  try {
    const data = await feriasFetch(`/${feriaActual.id}/merma`, {
      method: "POST", body: JSON.stringify({
        inventario_id: Number(document.getElementById("mer-item").value),
        cantidad: document.getElementById("mer-cant").value || 1,
        motivo: document.getElementById("mer-motivo").value.trim() || undefined,
      }),
    });
    if (!data.ok) { toast(data.error || "No se pudo registrar.", true); return; }
    cerrarModal();
    if (navigator.vibrate) navigator.vibrate([30, 30, 30]);
    toast(`📉 Merma registrada · ${esc(data.merma.producto_nombre)}`);
    abrirFeriaPOS(feriaActual.id);
  } catch (e) { toast("Error de red.", true); }
  finally { btn.disabled = false; }
}

// ---- Cerrar caja (finalizar feria) ----
function cerrarFeria() {
  if (!feriaActual) return;
  const matActual = feriaActual.costo_material || 0;
  abrirModal("Cerrar caja", `
    <p class="text-sm text-slate-400">Se calculará el balance final, se registrarán el costo del stand y del material como gasto, y el stock no vendido volverá al inventario general. Esta acción no se puede deshacer.</p>
    <label class="block text-xs text-slate-400">Costo de material / mercadería (Bs.)
      <input id="ci-material" type="number" inputmode="decimal" min="0" value="${matActual}" class="mt-1 w-full px-3 py-2.5 rounded-lg bg-base border border-edge text-slate-100">
    </label>
    <button onclick="confirmarCierre(this)" class="w-full py-3 rounded-xl font-semibold text-slate-900 bg-gradient-to-r from-amber-500 to-orange-500 active:opacity-80">🏁 Confirmar cierre</button>
    <button onclick="cerrarModal()" class="w-full py-2.5 rounded-xl text-sm bg-card border border-edge text-slate-300">Cancelar</button>`);
}

async function confirmarCierre(btn) {
  btn.disabled = true;
  const material = document.getElementById("ci-material");
  try {
    const data = await feriasFetch(`/${feriaActual.id}/cerrar`, {
      method: "POST",
      body: JSON.stringify({ costo_material: material ? (material.value || 0) : undefined }),
    });
    if (!data.ok) { toast(data.error || "No se pudo cerrar.", true); return; }
    const r = data.reporte || {};
    const dev = data.stock_devuelto || [];
    const estrella = r.producto_estrella;
    const pctV = r.porcentaje_vendido || 0;
    const gananciaColor = (r.ganancia_neta || 0) >= 0 ? "text-emerald-300" : "text-rose-300";
    abrirModal("📊 Reporte de la feria", `
      ${estrella
        ? `<div class="rounded-xl p-3 bg-gradient-to-br from-amber-500/15 to-orange-500/10 border border-amber-500/30">
             <p class="text-[10px] text-amber-300 uppercase tracking-wide">⭐ Producto estrella</p>
             <p class="font-bold text-slate-100 text-lg leading-tight">${esc(estrella.producto_nombre)}</p>
             <p class="text-xs text-slate-400">${estrella.unidades} unidades · ${money(estrella.recaudado)}</p>
           </div>`
        : `<div class="rounded-xl p-3 bg-base border border-edge text-sm text-slate-500">No se registraron ventas.</div>`}

      <div>
        <div class="flex justify-between text-xs mb-1">
          <span class="text-slate-400">Inventario vendido</span>
          <span class="text-slate-200 font-semibold">${pctV}% vendido · ${r.porcentaje_sobrante || 0}% sobra</span>
        </div>
        <div class="h-3 rounded-full bg-base overflow-hidden border border-edge">
          <div class="h-full rounded-full bg-gradient-to-r from-teal-500 to-emerald-500" style="width:${Math.min(100, pctV)}%"></div>
        </div>
        <p class="text-[11px] text-slate-500 mt-1">${r.unidades_vendidas || 0} vendidas · ${r.unidades_restantes || 0} sobrantes · ${r.unidades_merma || 0} mermas de ${r.unidades_llevadas || 0} llevadas</p>
      </div>

      <div class="rounded-xl bg-base border border-edge divide-y divide-edge text-sm">
        <div class="flex justify-between px-3 py-2"><span class="text-slate-400">Recaudado (caja)</span><b class="text-teal-300">${money(r.total_recaudado)}</b></div>
        <div class="flex justify-between px-3 py-2"><span class="text-slate-400">− Costo stand</span><b class="text-slate-300">${money(r.costo_stand)}</b></div>
        <div class="flex justify-between px-3 py-2"><span class="text-slate-400">− Costo material</span><b class="text-slate-300">${money(r.costo_material)}</b></div>
        <div class="flex justify-between px-3 py-2.5 bg-cardh"><span class="text-slate-200 font-semibold">Ganancia neta final</span><b class="${gananciaColor} text-lg">${money(r.ganancia_neta)}</b></div>
      </div>

      <div>
        <p class="text-xs text-slate-400 mb-1">Stock devuelto al inventario:</p>
        ${dev.length
          ? `<ul class="text-sm text-slate-300 space-y-1 max-h-32 overflow-y-auto">${dev.map((d) => `<li class="flex justify-between bg-base rounded-lg px-3 py-1.5"><span class="truncate">${esc(d.producto_nombre)}</span><b>${d.cantidad_devuelta}</b></li>`).join("")}</ul>`
          : `<p class="text-sm text-slate-500">Se vendió todo. 🎉</p>`}
      </div>
      <button onclick="cerrarModal(); cerrarVistaPOS();" class="w-full py-3 rounded-xl font-semibold text-slate-900 bg-gradient-to-r from-teal-500 to-cyan-500">Listo</button>`);
    if (navigator.vibrate) navigator.vibrate([80, 40, 80]);
  } catch (e) { toast("Error de red.", true); }
  finally { btn.disabled = false; }
}

// ==========================================================================
//  COBRO, DEUDA Y WHATSAPP (por pedido)
// ==========================================================================
async function setCobrador(pid, cobradorId) {
  try {
    const r = await fetch(`${API}/api/v1/pedidos/${pid}/cobrador`, {
      method: "PATCH", headers: headers(true),
      body: JSON.stringify({ cobrador_id: cobradorId || null }) });
    const d = await r.json();
    if (!d.ok) { toast(d.error || "No se pudo.", true); return; }
    actualizarPedidoLocal(d.pedido);
    toast(cobradorId ? "Cobrador asignado." : "Cobro sin asignar.");
  } catch (e) { toast("Error de red.", true); }
}

async function saldarPedido(pid, valor) {
  try {
    const r = await fetch(`${API}/api/v1/pedidos/${pid}/saldar`, {
      method: "PATCH", headers: headers(true), body: JSON.stringify({ saldado: valor }) });
    const d = await r.json();
    if (!d.ok) { toast(d.error || "No se pudo.", true); return; }
    actualizarPedidoLocal(d.pedido);
    cargarDeuda();
    toast(valor ? "✔ Marcado como saldado." : "Deuda reactivada.");
  } catch (e) { toast("Error de red.", true); }
}

// Reemplaza un pedido en el cache y repinta sin recargar todo.
function actualizarPedidoLocal(pedido) {
  const i = PEDIDOS.findIndex((p) => p.id === pedido.id);
  if (i >= 0) PEDIDOS[i] = pedido;
  renderPedidos();
}

function avisarWhatsApp(pid) {
  const p = PEDIDOS.find((x) => x.id === pid);
  if (!p || !p.telefono) return;
  const tel = p.telefono.replace(/[^0-9]/g, "");
  let msg;
  if (p.estado === "Terminado") msg = `¡Hola! Tu pedido «${p.nombre}» ya está listo para recoger 🎉`;
  else if (p.estado === "Entregado") msg = `¡Hola! Gracias por tu compra de «${p.nombre}» 🙌`;
  else msg = `¡Hola! Te escribo por tu pedido «${p.nombre}». `;
  if (p.saldo_pendiente > 0) msg += ` Saldo pendiente: ${money(p.saldo_pendiente)}.`;
  window.open(`https://wa.me/${tel}?text=${encodeURIComponent(msg)}`, "_blank");
}

// ==========================================================================
//  NUEVO PEDIDO (con cotizador automático)
// ==========================================================================
let FILAMENTOS = [];
async function abrirNuevoPedido() {
  if (!SOCIOS.length) await cargarSocios();
  try {
    const r = await fetch(`${API}/api/v1/filamentos-stock`, { headers: headers() });
    const d = await r.json();
    FILAMENTOS = d.ok ? d.filamentos : [];
  } catch (e) { FILAMENTOS = []; }

  const optEstados = ESTADOS.map((e) => `<option ${e === "En espera" ? "selected" : ""}>${e}</option>`).join("");
  const optSocios = ['<option value="">¿Quién cobra? (opcional)</option>']
    .concat(SOCIOS.map((u) => `<option value="${u.id}">${esc(u.nombre)}</option>`)).join("");
  const optFil = ['<option value="">— Filamento —</option>']
    .concat(FILAMENTOS.map((f) => `<option value="${f.id}">${esc([f.material, f.color].filter(Boolean).join(" "))}</option>`)).join("");
  const inp = "w-full bg-base border border-edge rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-600 outline-none focus:border-teal-400";

  abrirModal("Nuevo pedido", `
    <input id="np-nombre" placeholder="Nombre de la pieza *" class="${inp}">
    <div class="grid grid-cols-2 gap-2">
      <input id="np-cliente" placeholder="Cliente" class="${inp}">
      <input id="np-telefono" placeholder="WhatsApp (ej. 591…)" class="${inp}">
    </div>
    <div class="grid grid-cols-2 gap-2">
      <input id="np-peso" type="number" step="0.1" placeholder="Peso (g)" class="${inp}" oninput="npCotizar()">
      <input id="np-horas" type="number" step="0.1" placeholder="Horas" class="${inp}" oninput="npCotizar()">
    </div>
    <select id="np-filamento" class="${inp}" onchange="npCotizar()">${optFil}</select>
    <div class="grid grid-cols-2 gap-2">
      <input id="np-precio" type="number" step="0.01" placeholder="Precio (Bs.)" class="${inp}">
      <input id="np-adelanto" type="number" step="0.01" placeholder="Adelanto (Bs.)" class="${inp}">
    </div>
    <button type="button" onclick="npAplicarSugerido()" id="np-sugerido"
            class="w-full py-2 rounded-lg text-xs bg-cyan-500/10 text-cyan-300 border border-cyan-500/30">🧮 Sugerir precio</button>
    <div class="grid grid-cols-2 gap-2">
      <select id="np-estado" class="${inp}">${optEstados}</select>
      <select id="np-cobrador" class="${inp}">${optSocios}</select>
    </div>
    <label class="text-xs text-slate-500 block">Fecha de entrega
      <input id="np-fecha" type="date" class="${inp}"></label>
    <button onclick="guardarNuevoPedido(this)" class="w-full py-3 rounded-xl font-semibold text-slate-900 bg-gradient-to-r from-teal-500 to-cyan-500">Guardar pedido</button>
  `);
}

let npSug = 0;
async function npCotizar() {
  const peso = document.getElementById("np-peso")?.value || 0;
  const horas = document.getElementById("np-horas")?.value || 0;
  const fid = document.getElementById("np-filamento")?.value || "";
  if (!peso && !horas) return;
  try {
    const r = await fetch(`${API}/api/v1/cotizar?peso=${peso}&horas=${horas}&filamento_id=${fid}`, { headers: headers() });
    const d = await r.json();
    if (d.ok) {
      npSug = d.precio_sugerido;
      const b = document.getElementById("np-sugerido");
      if (b) b.textContent = `🧮 Sugerido: ${money(d.precio_sugerido)} (toca para usar)`;
    }
  } catch (e) { /* ignora */ }
}
function npAplicarSugerido() {
  if (npSug) document.getElementById("np-precio").value = npSug;
}

async function guardarNuevoPedido(btn) {
  const nombre = document.getElementById("np-nombre").value.trim();
  if (!nombre) { toast("El nombre es obligatorio.", true); return; }
  btn.disabled = true;
  const body = {
    nombre,
    cliente: document.getElementById("np-cliente").value.trim(),
    telefono: document.getElementById("np-telefono").value.trim(),
    peso_g: document.getElementById("np-peso").value || 0,
    tiempo_estimado_h: document.getElementById("np-horas").value || 0,
    filamento_id: document.getElementById("np-filamento").value || null,
    precio_total: document.getElementById("np-precio").value || 0,
    adelanto: document.getElementById("np-adelanto").value || 0,
    estado: document.getElementById("np-estado").value,
    cobrador_id: document.getElementById("np-cobrador").value || null,
    fecha_entrega: document.getElementById("np-fecha").value || null,
  };
  try {
    const r = await fetch(`${API}/api/v1/pedidos`, { method: "POST", headers: headers(true), body: JSON.stringify(body) });
    const d = await r.json();
    if (!d.ok) { toast(d.error || "No se pudo crear.", true); btn.disabled = false; return; }
    cerrarModal();
    toast("✅ Pedido creado.");
    cargarPedidos();
  } catch (e) { toast("Error de red.", true); btn.disabled = false; }
}

// ==========================================================================
//  GASTO RÁPIDO
// ==========================================================================
async function abrirGastoRapido() {
  if (!SOCIOS.length) await cargarSocios();
  const cats = ["Filamento", "Resina", "Cajas/Empaque", "Envíos", "Luz/Servicios", "Repuestos", "Herramientas", "Otro"];
  const inp = "w-full bg-base border border-edge rounded-lg px-3 py-2 text-sm text-slate-100 outline-none focus:border-teal-400";
  abrirModal("Gasto rápido", `
    <input id="g-monto" type="number" step="0.01" placeholder="Monto (Bs.) *" class="${inp}">
    <input id="g-desc" placeholder="Descripción" class="${inp}">
    <div class="grid grid-cols-2 gap-2">
      <select id="g-cat" class="${inp}">${cats.map((c) => `<option>${c}</option>`).join("")}</select>
      <select id="g-quien" class="${inp}"><option value="">¿Quién pagó?</option>${SOCIOS.map((u) => `<option value="${u.id}">${esc(u.nombre)}</option>`).join("")}</select>
    </div>
    <button onclick="guardarGasto(this)" class="w-full py-3 rounded-xl font-semibold text-slate-900 bg-gradient-to-r from-amber-500 to-orange-500">Registrar gasto</button>
  `);
}
async function guardarGasto(btn) {
  const monto = parseFloat(document.getElementById("g-monto").value || 0);
  if (monto <= 0) { toast("Monto inválido.", true); return; }
  btn.disabled = true;
  try {
    const r = await fetch(`${API}/api/v1/gastos`, { method: "POST", headers: headers(true),
      body: JSON.stringify({ monto, descripcion: document.getElementById("g-desc").value.trim(),
        categoria: document.getElementById("g-cat").value, usuario_id: document.getElementById("g-quien").value || null }) });
    const d = await r.json();
    if (!d.ok) { toast(d.error || "No se pudo.", true); btn.disabled = false; return; }
    cerrarModal(); toast("💸 Gasto registrado.");
  } catch (e) { toast("Error de red.", true); btn.disabled = false; }
}

// ==========================================================================
//  CLIENTES · IMPRESORAS · RESUMEN (sección "Más")
// ==========================================================================
async function abrirClientes() {
  const box = document.getElementById("mas-contenido");
  box.innerHTML = `<div class="skeleton h-24 rounded-2xl"></div>`;
  try {
    const r = await fetch(`${API}/api/v1/clientes`, { headers: headers() });
    const d = await r.json();
    box.innerHTML = `<h2 class="text-sm font-semibold text-slate-300">👥 Clientes (${d.clientes.length})</h2>` +
      (d.clientes.length ? d.clientes.map((c) => `
      <div class="bg-card border border-edge rounded-2xl p-3 flex items-center gap-3">
        <div class="min-w-0 flex-1">
          <p class="font-semibold text-slate-100 truncate">${esc(c.cliente)}</p>
          <p class="text-xs text-slate-500">${c.pedidos} pedido(s) · ${c.activos} activo(s) · gastó ${money(c.total_gastado)}</p>
        </div>
        ${c.telefono ? `<a href="https://wa.me/${c.telefono.replace(/[^0-9]/g, "")}" target="_blank" class="px-2.5 py-1.5 rounded-lg bg-green-500/15 text-green-300 border border-green-500/30 text-xs">📲</a>` : ""}
      </div>`).join("") : `<p class="text-slate-500 text-sm">Aún no hay clientes con nombre.</p>`);
  } catch (e) { box.innerHTML = `<p class="text-rose-300 text-sm">No se pudo cargar.</p>`; }
}

async function abrirImpresoras() {
  const box = document.getElementById("mas-contenido");
  box.innerHTML = `<div class="skeleton h-24 rounded-2xl"></div>`;
  try {
    const r = await fetch(`${API}/api/v1/impresoras`, { headers: headers() });
    const d = await r.json();
    box.innerHTML = `<div class="flex items-center justify-between">
        <h2 class="text-sm font-semibold text-slate-300">🖨️ Impresoras</h2>
        <button onclick="abrirNuevaImpresora()" class="text-xs px-2 py-1 rounded-lg bg-card border border-edge text-slate-300">＋ Nueva</button></div>` +
      (d.impresoras.length ? d.impresoras.map((m) => `
      <div class="bg-card border ${m.necesita_mant ? "border-amber-500/40" : "border-edge"} rounded-2xl p-3">
        <div class="flex items-center justify-between">
          <p class="font-semibold text-slate-100">${esc(m.nombre)}</p>
          ${m.necesita_mant ? `<span class="text-[11px] px-2 py-0.5 rounded-md bg-amber-500/15 text-amber-300 border border-amber-500/30">⚠️ Revisar boquilla</span>` : ""}
        </div>
        <p class="text-xs text-slate-500 mt-1">${m.horas_totales} h totales · ${m.horas_desde_mant} h desde el último mantenimiento (cada ${m.intervalo_mant_h} h)</p>
        <div class="flex gap-2 mt-2">
          <button onclick="sumarHoras(${m.id})" class="flex-1 py-1.5 rounded-lg text-xs bg-base border border-edge text-slate-300">＋ Horas</button>
          <button onclick="hacerMantenimiento(${m.id})" class="flex-1 py-1.5 rounded-lg text-xs bg-teal-500/15 text-teal-300 border border-teal-500/30">🔧 Mantenimiento hecho</button>
        </div>
      </div>`).join("") : `<p class="text-slate-500 text-sm">Sin impresoras. Agrega una.</p>`);
  } catch (e) { box.innerHTML = `<p class="text-rose-300 text-sm">No se pudo cargar.</p>`; }
}
function abrirNuevaImpresora() {
  const inp = "w-full bg-base border border-edge rounded-lg px-3 py-2 text-sm text-slate-100 outline-none focus:border-teal-400";
  abrirModal("Nueva impresora", `
    <input id="im-nombre" placeholder="Nombre (ej. Bambu A1) *" class="${inp}">
    <div class="grid grid-cols-2 gap-2">
      <input id="im-horas" type="number" step="1" placeholder="Horas actuales" class="${inp}">
      <input id="im-intervalo" type="number" step="1" placeholder="Mant. cada (h)" value="250" class="${inp}">
    </div>
    <button onclick="guardarImpresora(this)" class="w-full py-3 rounded-xl font-semibold text-slate-900 bg-gradient-to-r from-teal-500 to-cyan-500">Guardar</button>`);
}
async function guardarImpresora(btn) {
  const nombre = document.getElementById("im-nombre").value.trim();
  if (!nombre) { toast("Nombre obligatorio.", true); return; }
  btn.disabled = true;
  try {
    const r = await fetch(`${API}/api/v1/impresoras`, { method: "POST", headers: headers(true),
      body: JSON.stringify({ nombre,
        horas_totales: document.getElementById("im-horas").value || 0,
        intervalo_mant_h: document.getElementById("im-intervalo").value || 250 }) });
    const d = await r.json();
    if (!d.ok) { toast(d.error || "No se pudo.", true); btn.disabled = false; return; }
    cerrarModal(); toast("🖨️ Impresora agregada."); abrirImpresoras();
  } catch (e) { toast("Error de red.", true); btn.disabled = false; }
}
async function sumarHoras(mid) {
  const h = prompt("¿Cuántas horas sumar?");
  if (!h) return;
  const r = await fetch(`${API}/api/v1/impresoras/${mid}/horas`, { method: "POST", headers: headers(true), body: JSON.stringify({ horas: parseFloat(h) || 0 }) });
  if ((await r.json()).ok) { toast("Horas sumadas."); abrirImpresoras(); }
}
async function hacerMantenimiento(mid) {
  const r = await fetch(`${API}/api/v1/impresoras/${mid}/mantenimiento`, { method: "POST", headers: headers(true) });
  if ((await r.json()).ok) { toast("🔧 Mantenimiento registrado."); abrirImpresoras(); }
}

async function abrirDashboard() {
  const box = document.getElementById("mas-contenido");
  box.innerHTML = `<div class="skeleton h-24 rounded-2xl"></div>`;
  try {
    const r = await fetch(`${API}/api/v1/dashboard`, { headers: headers() });
    const d = await r.json();
    const tile = (t, v, c) => `<div class="bg-card border border-edge rounded-2xl p-3 text-center"><p class="text-[10px] text-slate-500 uppercase">${t}</p><p class="text-xl font-bold ${c}">${v}</p></div>`;
    box.innerHTML = `<h2 class="text-sm font-semibold text-slate-300 mb-1">📊 Resumen</h2>
      <div class="grid grid-cols-2 gap-2">
        ${tile("Activos", d.activos, "text-slate-100")}
        ${tile("Urgentes", d.urgentes, "text-rose-300")}
        ${tile("En espera", d.en_espera, "text-amber-300")}
        ${tile("Entregados (mes)", d.entregados_mes, "text-green-300")}
      </div>
      <div class="bg-card border border-teal-500/30 rounded-2xl p-3 text-center mt-2">
        <p class="text-[10px] text-slate-500 uppercase">Ingreso reconocido este mes</p>
        <p class="text-2xl font-bold text-teal-300">${money(d.ingreso_mes)}</p></div>`;
  } catch (e) { box.innerHTML = `<p class="text-rose-300 text-sm">No se pudo cargar.</p>`; }
}

// ==========================================================================
//  CALENDARIO (agenda mensual por fecha de entrega)
// ==========================================================================
const CAL_MESES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];
let calAnio, calMes;
async function cargarCalendario() {
  const hoy = new Date();
  if (!calAnio) { calAnio = hoy.getFullYear(); calMes = hoy.getMonth() + 1; }
  try {
    const r = await fetch(`${API}/api/v1/pedidos-calendario?anio=${calAnio}&mes=${calMes}`, { headers: headers() });
    const d = await r.json();
    renderCalendario(d.dias || {});
  } catch (e) { renderCalendario({}); }
}
function calMover(delta) {
  calMes += delta;
  if (calMes < 1) { calMes = 12; calAnio--; }
  if (calMes > 12) { calMes = 1; calAnio++; }
  document.getElementById("cal-detalle").innerHTML = "";
  cargarCalendario();
}
function renderCalendario(dias) {
  document.getElementById("cal-titulo").textContent = `${CAL_MESES[calMes]} ${calAnio}`;
  const primero = new Date(calAnio, calMes - 1, 1);
  const offset = (primero.getDay() + 6) % 7;   // lunes = 0
  const nDias = new Date(calAnio, calMes, 0).getDate();
  const hoy = new Date();
  const esHoy = (dia) => hoy.getFullYear() === calAnio && hoy.getMonth() + 1 === calMes && hoy.getDate() === dia;
  const dow = ["L", "M", "M", "J", "V", "S", "D"];
  let html = dow.map((x) => `<div class="text-center text-[10px] text-slate-600 py-1">${x}</div>`).join("");
  for (let i = 0; i < offset; i++) html += `<div></div>`;
  for (let dia = 1; dia <= nDias; dia++) {
    const iso = `${calAnio}-${String(calMes).padStart(2, "0")}-${String(dia).padStart(2, "0")}`;
    const items = dias[iso] || [];
    const urg = items.some((x) => x.urgente && !x.entregado);
    const dot = items.length
      ? `<span class="absolute bottom-1 left-1/2 -translate-x-1/2 w-1.5 h-1.5 rounded-full ${urg ? "bg-rose-400" : "bg-teal-400"}"></span>` : "";
    html += `<button onclick='calDia(${JSON.stringify(iso)})' class="relative aspect-square rounded-lg text-xs flex items-center justify-center border ${esHoy(dia) ? "border-teal-400 text-teal-300" : "border-edge text-slate-300"} ${items.length ? "bg-card" : "bg-base/40"}">${dia}${dot}</button>`;
  }
  document.getElementById("cal-grid").innerHTML = html;
  window._calDias = dias;
}
function calDia(iso) {
  const items = (window._calDias || {})[iso] || [];
  const box = document.getElementById("cal-detalle");
  const f = new Date(iso + "T12:00:00");
  box.innerHTML = `<h3 class="text-sm font-semibold text-slate-300">${f.getDate()} de ${CAL_MESES[calMes]}</h3>` +
    (items.length ? items.map((x) => `
      <div class="bg-card border border-edge rounded-xl p-2.5 flex items-center gap-2">
        <span class="w-2 h-2 rounded-full ${x.entregado ? "bg-green-400" : x.urgente ? "bg-rose-400" : "bg-teal-400"}"></span>
        <span class="flex-1 truncate text-sm text-slate-200">${esc(x.nombre)} <span class="text-slate-500 text-xs">· ${esc(x.cliente || "")}</span></span>
        <span class="text-[11px] text-slate-400">${esc(x.estado)}</span>
      </div>`).join("") : `<p class="text-slate-500 text-sm">Sin entregas este día.</p>`);
}

// Llena el filtro de estado una vez.
(function initFiltros() {
  const sel = document.getElementById("filtro-estado");
  if (sel) ESTADOS.forEach((e) => sel.insertAdjacentHTML("beforeend", `<option value="${e}">${e}</option>`));
})();

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
