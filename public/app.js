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
function mostrar(sec) {
  const esPed = sec === "pedidos";
  document.getElementById("sec-pedidos").classList.toggle("hidden", !esPed);
  document.getElementById("sec-filamentos").classList.toggle("hidden", esPed);
  document.getElementById("tab-pedidos").className =
    "py-3 flex flex-col items-center gap-0.5 " + (esPed ? "text-teal-300" : "text-slate-500");
  document.getElementById("tab-filamentos").className =
    "py-3 flex flex-col items-center gap-0.5 " + (esPed ? "text-slate-500" : "text-teal-300");
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

// ---- Render de un pedido ----
function tarjetaPedido(p) {
  const foto = p.foto_url
    ? `<img src="${esc(p.foto_url)}" alt="${esc(p.nombre)}" class="w-20 h-20 rounded-xl object-cover border border-edge shrink-0"
            onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'w-20 h-20 rounded-xl bg-base border border-dashed border-edge shrink-0 flex items-center justify-center text-2xl text-slate-600',textContent:'🖼️'}))">`
    : `<div class="w-20 h-20 rounded-xl bg-base border border-dashed border-edge shrink-0 flex items-center justify-center text-2xl text-slate-600">🖼️</div>`;

  const timer = p.fecha_entrega_iso
    ? `<div data-timer data-deadline="${esc(p.fecha_entrega_iso)}T23:59:59"
             class="mt-2 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold border">
         <span data-icon>⏳</span><span data-remaining>—</span></div>`
    : `<div class="mt-2 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs bg-base border border-edge text-slate-500">📅 Sin fecha de entrega</div>`;

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
      </div>
    </div>
    <div class="border-t border-edge bg-base/40 px-3 py-2 flex items-center gap-2">
      <button onclick="cambiarEstado(${p.id},'Terminado',this)" class="flex-1 py-2 rounded-lg text-sm font-semibold text-slate-900 bg-gradient-to-r from-teal-500 to-cyan-500 active:opacity-80 transition">✅ Listo</button>
      <button onclick="cambiarEstado(${p.id},'Entregado',this)" class="flex-1 py-2 rounded-lg text-sm font-semibold text-slate-900 bg-gradient-to-r from-green-500 to-emerald-500 active:opacity-80 transition">📦 Entregado</button>
      <select onchange="cambiarEstado(${p.id},this.value,this)" class="py-2 px-2 rounded-lg text-xs bg-card border border-edge text-slate-300 max-w-[7.5rem]">
        <option value="" disabled selected>Más…</option>${opciones}
      </select>
    </div>
  </article>`;
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

// Esqueleto inicial mientras carga
document.getElementById("lista-pedidos").innerHTML =
  Array.from({ length: 2 }).map(() => `<div class="skeleton h-28 rounded-2xl"></div>`).join("");

cargarTodo();
setInterval(actualizarTimers, 1000);
setInterval(cargarPedidos, 60000);   // auto-refresco cada minuto

// ---- Service Worker (PWA) ----
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
