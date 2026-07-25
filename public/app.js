/* =====================================================================
   Ferias 3D · POS Móvil  —  lógica de la PWA
   ===================================================================== */

const App = (() => {
  // API base: si la PWA se sirve desde el mismo Flask (/app) usa origen actual.
  // Si se despliega en Vercel, se guarda la URL del servidor en Ajustes.
  function apiBase() {
    let b = localStorage.getItem('apiBase') || '';
    if (!b && location.pathname.startsWith('/app')) b = location.origin; // Flask local
    return b.replace(/\/$/, '');
  }

  async function api(path, opts = {}) {
    const url = apiBase() + path;
    const res = await fetch(url, {
      credentials: 'include',
      headers: opts.body && !(opts.body instanceof FormData)
        ? { 'Content-Type': 'application/json' } : undefined,
      ...opts,
    });
    net(true);
    if (!res.ok) {
      let msg = 'Error ' + res.status;
      try { const j = await res.json(); msg = j.error || msg; } catch {}
      throw new Error(msg);
    }
    return res.json();
  }

  function net(ok) {
    const dot = document.getElementById('netDot');
    dot.className = 'w-2.5 h-2.5 rounded-full ' + (ok ? 'bg-emerald-500' : 'bg-rose-500');
  }

  function saveConfig() {
    const v = document.getElementById('cfgApi').value.trim();
    localStorage.setItem('apiBase', v);
    UI.toast('Guardado ✓', 'ok');
    App.refreshFerias();
  }

  function refreshFerias() { UI.loadFerias(); }

  return { api, apiBase, net, saveConfig, refreshFerias };
})();

/* --------------------------- Utilidades --------------------------- */
const bs = n => 'Bs ' + (Math.round((n || 0) * 100) / 100).toLocaleString('es-BO');
const el = id => document.getElementById(id);

/* ============================ UI / Vistas ============================ */
const UI = (() => {
  let feriaActual = null;      // objeto feria en POS
  let inventario = [];
  let ventas = [];

  function toast(msg, type = 'ok') {
    const t = el('toast');
    t.textContent = msg;
    t.className = 'fixed top-3 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-xl text-sm font-semibold shadow-lg ' +
      (type === 'err' ? 'bg-rose-600 text-white' : type === 'warn' ? 'bg-amber-500 text-slate-900' : 'bg-emerald-600 text-white');
    t.classList.remove('hidden');
    clearTimeout(t._t);
    t._t = setTimeout(() => t.classList.add('hidden'), 2600);
  }

  function show(view) {
    ['ferias', 'pos', 'monitor', 'config'].forEach(v =>
      el('view-' + v).classList.toggle('hidden', v !== view));
    document.querySelectorAll('.navbtn').forEach(b =>
      b.classList.toggle('text-brand', b.dataset.nav === view || (view === 'pos' && b.dataset.nav === 'ferias')));
  }

  function nav(view) {
    if (view === 'ferias') { show('ferias'); loadFerias(); el('hdrTitle').textContent = 'Ferias 3D'; el('hdrSub').textContent = 'POS Móvil'; }
    if (view === 'monitor') { show('monitor'); loadMonitor(); el('hdrTitle').textContent = 'Monitor'; el('hdrSub').textContent = 'Impresión en vivo'; }
    if (view === 'config') { show('config'); el('cfgApi').value = localStorage.getItem('apiBase') || ''; el('hdrTitle').textContent = 'Ajustes'; el('hdrSub').textContent = ''; }
  }

  /* ---------------------------- FERIAS ---------------------------- */
  async function loadFerias() {
    try {
      const { ferias } = await App.api('/api/v1/ferias');
      const cont = el('listaFerias'); cont.innerHTML = '';
      el('feriasEmpty').classList.toggle('hidden', ferias.length > 0);
      ferias.forEach(f => {
        const activa = f.estado === 'Activa';
        const div = document.createElement('div');
        div.className = 'bg-slate-900 rounded-2xl p-4 flex items-center justify-between tap';
        div.onclick = () => openPOS(f.id);
        div.innerHTML = `
          <div>
            <p class="font-bold">${esc(f.nombre)}</p>
            <p class="text-xs text-slate-400">${f.fecha || ''} · ${f.unidades_vendidas} ventas</p>
          </div>
          <div class="text-right">
            <p class="font-extrabold text-emerald-400">${bs(f.total_recaudado)}</p>
            <span class="text-[10px] px-2 py-0.5 rounded-full ${activa ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-700 text-slate-300'}">${f.estado}</span>
          </div>`;
        cont.appendChild(div);
      });
    } catch (e) { App.net(false); toast(e.message, 'err'); }
  }

  function openNuevaFeria() {
    openModal('Nueva feria', `
      <input id="mNombre" placeholder="Nombre de la feria" class="w-full bg-slate-800 rounded-xl px-3 py-3">
      <input id="mFecha" type="date" class="w-full bg-slate-800 rounded-xl px-3 py-3">
      <input id="mCosto" type="number" inputmode="decimal" placeholder="Costo del stand (Bs)" class="w-full bg-slate-800 rounded-xl px-3 py-3">
    `, async () => {
      const nombre = el('mNombre').value.trim();
      if (!nombre) return toast('Poné un nombre', 'warn');
      await App.api('/api/v1/ferias', { method: 'POST', body: JSON.stringify({
        nombre, fecha: el('mFecha').value || undefined, costo_stand: el('mCosto').value || 0 }) });
      closeModal(); toast('Feria creada 🎪'); loadFerias();
    });
    el('mFecha').valueAsDate = new Date();
  }

  /* ------------------------------ POS ------------------------------ */
  async function openPOS(id) {
    try {
      const { feria } = await App.api('/api/v1/ferias/' + id);
      feriaActual = feria; inventario = feria.inventario || []; ventas = feria.ventas || [];
      el('hdrTitle').textContent = feria.nombre;
      el('hdrSub').textContent = feria.estado === 'Activa' ? '🟢 Vendiendo' : '⚪ Finalizada';
      show('pos'); renderPOS();
    } catch (e) { toast(e.message, 'err'); }
  }
  function backToFerias() { feriaActual = null; nav('ferias'); }

  function renderPOS() {
    const grid = el('posGrid'); grid.innerHTML = '';
    el('posEmpty').classList.toggle('hidden', inventario.length > 0);
    const cerrada = feriaActual.estado !== 'Activa';

    inventario.forEach(it => {
      const sinStock = it.cantidad_restante <= 0;
      const btn = document.createElement('button');
      btn.className = 'tap rounded-2xl p-4 text-left ' +
        (sinStock || cerrada ? 'bg-slate-800 opacity-50' : 'bg-brand/90 active:bg-brand');
      btn.disabled = sinStock || cerrada;
      btn.onclick = () => ventaRapida(it.id, btn);
      btn.innerHTML = `
        <p class="font-bold leading-tight">${esc(it.producto_nombre)}</p>
        <p class="text-xl font-extrabold mt-1">${bs(it.precio_unitario)}</p>
        <p class="text-[11px] mt-1 opacity-80">Quedan ${it.cantidad_restante} · vend. ${it.cantidad_vendida}</p>`;
      grid.appendChild(btn);
    });

    // resumen
    el('posCaja').textContent = bs(feriaActual.total_recaudado);
    el('posUnidades').textContent = inventario.reduce((s, i) => s + i.cantidad_vendida, 0);
    el('posStock').textContent = inventario.reduce((s, i) => s + i.cantidad_restante, 0);
    renderVentas();
  }

  function renderVentas() {
    const c = el('posVentas'); c.innerHTML = '';
    ventas.slice(0, 8).forEach(v => {
      const d = document.createElement('div');
      d.className = 'flex justify-between bg-slate-900 rounded-lg px-3 py-1.5';
      const hora = v.fecha_hora ? new Date(v.fecha_hora).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' }) : '';
      d.innerHTML = `<span>${esc(v.producto_nombre)} ×${v.cantidad}</span><span class="text-emerald-400 font-semibold">${bs(v.precio_total)} <span class="text-slate-500 text-xs">${hora}</span></span>`;
      c.appendChild(d);
    });
  }

  async function ventaRapida(invId, btn) {
    if (navigator.vibrate) navigator.vibrate(15);
    btn.classList.add('pop'); setTimeout(() => btn.classList.remove('pop'), 260);
    try {
      const r = await App.api('/api/v1/ferias/' + feriaActual.id + '/venta-rapida',
        { method: 'POST', body: JSON.stringify({ inventario_id: invId, cantidad: 1 }) });
      feriaActual.total_recaudado = r.total_recaudado;
      const it = inventario.find(i => i.id === invId);
      if (it) { it.cantidad_vendida = r.item.cantidad_vendida; }
      ventas.unshift(r.venta);
      renderPOS();
      toast('✔ ' + bs(r.venta.precio_total));
    } catch (e) { toast(e.message, 'err'); }
  }

  function openNuevoProducto() {
    if (feriaActual.estado !== 'Activa') return toast('Feria finalizada', 'warn');
    openModal('Cargar producto', `
      <input id="pNombre" placeholder="Nombre del producto" class="w-full bg-slate-800 rounded-xl px-3 py-3">
      <div class="grid grid-cols-2 gap-2">
        <input id="pCant" type="number" inputmode="numeric" placeholder="Cant. llevada" class="bg-slate-800 rounded-xl px-3 py-3">
        <input id="pPrecio" type="number" inputmode="decimal" placeholder="Precio Bs" class="bg-slate-800 rounded-xl px-3 py-3">
      </div>
      <input id="pCosto" type="number" inputmode="decimal" placeholder="Costo unitario (opcional)" class="w-full bg-slate-800 rounded-xl px-3 py-3">
    `, async () => {
      const nombre = el('pNombre').value.trim();
      if (!nombre) return toast('Falta el nombre', 'warn');
      const { item } = await App.api('/api/v1/ferias/' + feriaActual.id + '/inventario', {
        method: 'POST', body: JSON.stringify({
          producto_nombre: nombre,
          cantidad_llevada: el('pCant').value || 0,
          precio_unitario: el('pPrecio').value || 0,
          costo_unitario: el('pCosto').value || 0 }) });
      inventario.push(item); closeModal(); renderPOS(); toast('Producto cargado');
    });
  }

  function confirmarCierre() {
    if (feriaActual.estado !== 'Activa') return toast('Ya está cerrada', 'warn');
    openModal('Cerrar caja', `
      <p class="text-sm text-slate-300">Se calculará el balance final y se marcará la feria como <b>Finalizada</b>. El stock no vendido se devuelve al inventario.</p>
    `, async () => {
      const r = await App.api('/api/v1/ferias/' + feriaActual.id + '/cerrar', { method: 'POST' });
      closeModal();
      const b = r.balance, dev = r.stock_devuelto;
      openModal('🧾 Balance final', `
        <div class="space-y-1 text-sm">
          <div class="flex justify-between"><span>Recaudado</span><b class="text-emerald-400">${bs(b.total_recaudado)}</b></div>
          <div class="flex justify-between"><span>Costo stand</span><span>- ${bs(b.costo_stand)}</span></div>
          <div class="flex justify-between"><span>Costo mercadería</span><span>- ${bs(b.costo_mercaderia)}</span></div>
          <hr class="border-slate-700 my-1">
          <div class="flex justify-between text-base"><span>Ganancia neta</span><b class="${b.ganancia_neta >= 0 ? 'text-emerald-400' : 'text-rose-400'}">${bs(b.ganancia_neta)}</b></div>
          <p class="text-xs text-slate-400 mt-2">${dev.length ? 'Devuelto al inventario: ' + dev.map(d => esc(d.producto_nombre) + ' ×' + d.cantidad_devuelta).join(', ') : 'Sin stock sobrante.'}</p>
        </div>`, () => { closeModal(); backToFerias(); }, 'Listo');
    }, 'Cerrar caja');
  }

  /* ---------------------------- MONITOR ---------------------------- */
  async function loadMonitor() {
    try {
      const { pedidos, filamento_bajo } = await App.api('/api/v1/monitor');
      // Filamento bajo
      const fc = el('monitorFilamento'); fc.innerHTML = '';
      if (filamento_bajo.length) {
        fc.innerHTML = `<div class="bg-amber-500/15 border border-amber-500/40 rounded-2xl p-3">
          <p class="font-bold text-amber-300 text-sm mb-1">🧵 Filamento bajo (&lt;100g)</p>
          ${filamento_bajo.map(f => `<p class="text-xs">${esc(f.tipo)} ${esc(f.color || '')} — <b>${f.peso_restante}g</b></p>`).join('')}
        </div>`;
        Notif.check(filamento_bajo);
      }
      // Pedidos activos con estado de impresión + timer
      const pc = el('monitorPedidos'); pc.innerHTML = '';
      el('monitorEmpty').classList.toggle('hidden', pedidos.length > 0);
      pedidos.forEach(p => pc.appendChild(pedidoCard(p)));
      Timers.rehidratar();
    } catch (e) { App.net(false); toast(e.message, 'err'); }
  }

  function pedidoCard(p) {
    const t = Timers.get(p.id);
    const div = document.createElement('div');
    div.className = 'bg-slate-900 rounded-2xl p-4';
    const estadoColor = p.estado === 'en_impresion' ? 'bg-sky-500/20 text-sky-300' : 'bg-slate-700 text-slate-300';
    div.innerHTML = `
      <div class="flex justify-between items-start">
        <div>
          <p class="font-bold leading-tight">${esc(p.modelo)}</p>
          <p class="text-xs text-slate-400">${esc(p.cliente)} · ${p.impresora || 'sin impresora'}</p>
        </div>
        <span class="text-[10px] px-2 py-0.5 rounded-full ${estadoColor}">${p.estado === 'en_impresion' ? '🖨️ Imprimiendo' : '⏳ Pendiente'}</span>
      </div>
      <div class="flex items-center justify-between mt-3">
        <div>
          <p class="text-[10px] uppercase text-slate-500">Est. ${p.horas_impresion || 0}h</p>
          <p id="tmr-${p.id}" class="font-mono text-lg font-bold ${t ? '' : 'text-slate-500'}">${t ? Timers.fmt(t.remaining()) : '--:--:--'}</p>
        </div>
        <div class="flex gap-2">
          ${t ? `<button class="tap bg-rose-600/80 text-xs px-3 py-2 rounded-xl" onclick="Timers.stop(${p.id})">Parar</button>`
              : `<button class="tap bg-brand text-xs px-3 py-2 rounded-xl" onclick="Timers.start(${p.id}, ${p.horas_impresion || 0}, '${esc(p.modelo)}')">▶ Iniciar timer</button>`}
        </div>
      </div>`;
    return div;
  }

  /* ---------------------------- Modal ---------------------------- */
  function openModal(title, bodyHTML, onOk, okLabel = 'Guardar') {
    el('modalTitle').textContent = title;
    el('modalBody').innerHTML = bodyHTML;
    const ok = el('modalOk'); ok.textContent = okLabel;
    ok.onclick = async () => { try { await onOk(); } catch (e) { toast(e.message, 'err'); } };
    const m = el('modal'); m.classList.remove('hidden'); m.classList.add('flex');
  }
  function closeModal() { const m = el('modal'); m.classList.add('hidden'); m.classList.remove('flex'); }

  const esc = s => String(s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  return { nav, loadFerias, loadMonitor, openNuevaFeria, openPOS, backToFerias,
           openNuevoProducto, confirmarCierre, ventaRapida, openModal, closeModal, toast, pedidoCard };
})();

/* ===================== Timers de impresión ===================== */
const Timers = (() => {
  const KEY = 'printTimers';
  const load = () => JSON.parse(localStorage.getItem(KEY) || '{}');
  const save = o => localStorage.setItem(KEY, JSON.stringify(o));
  let tick = null;

  function get(id) {
    const t = load()[id];
    if (!t) return null;
    return { ...t, remaining: () => Math.max(0, Math.round((t.end - Date.now()) / 1000)) };
  }
  function start(id, horas, nombre) {
    const o = load();
    o[id] = { end: Date.now() + (horas || 0) * 3600 * 1000, nombre, notified: false };
    save(o); ensureTick(); UI.loadMonitor();
    UI.toast('Timer iniciado ⏱️');
  }
  function stop(id) { const o = load(); delete o[id]; save(o); UI.loadMonitor(); }
  function fmt(sec) {
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return [h, m, s].map(n => String(n).padStart(2, '0')).join(':');
  }
  function ensureTick() { if (!tick) tick = setInterval(step, 1000); }
  function step() {
    const o = load(); let changed = false;
    Object.keys(o).forEach(id => {
      const rem = Math.max(0, Math.round((o[id].end - Date.now()) / 1000));
      const span = document.getElementById('tmr-' + id);
      if (span) span.textContent = fmt(rem);
      if (rem <= 0 && !o[id].notified) {
        o[id].notified = true; changed = true;
        Notif.fire('✅ Impresión terminada', `“${o[id].nombre}” llegó a 00:00:00`);
        if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
      }
    });
    if (changed) save(o);
    if (!Object.keys(o).length && tick) { clearInterval(tick); tick = null; }
  }
  function rehidratar() { if (Object.keys(load()).length) ensureTick(); }
  return { get, start, stop, fmt, rehidratar };
})();

/* ===================== Notificaciones (Notification API + SW) ===================== */
const Notif = (() => {
  let notifiedFilament = new Set();

  async function request() {
    if (!('Notification' in window)) return UI.toast('Sin soporte de notificaciones', 'warn');
    const p = await Notification.requestPermission();
    el('cfgNotif') && (el('cfgNotif').textContent = p);
    UI.toast(p === 'granted' ? 'Notificaciones activadas 🔔' : 'Permiso denegado', p === 'granted' ? 'ok' : 'warn');
  }
  async function fire(title, body) {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    const reg = await navigator.serviceWorker?.getRegistration();
    if (reg) reg.showNotification(title, { body, icon: 'icons/icon-192.png', badge: 'icons/icon-192.png', vibrate: [200, 100, 200] });
    else new Notification(title, { body });
  }
  function check(filamentos) {
    filamentos.forEach(f => {
      if (!notifiedFilament.has(f.id)) {
        notifiedFilament.add(f.id);
        fire('🧵 Filamento bajo', `${f.tipo} ${f.color || ''}: ${f.peso_restante}g restantes`);
      }
    });
  }
  return { request, fire, check };
})();

/* ============================ Bootstrap ============================ */
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.navbtn').forEach(b => b.addEventListener('click', () => UI.nav(b.dataset.nav)));
  el('btnBell').addEventListener('click', Notif.request);
  el('cfgNotif') && (el('cfgNotif').textContent = ('Notification' in window) ? Notification.permission : 'no soportado');

  UI.nav('ferias');

  // Service Worker
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  }
  // Poll de monitor en segundo plano para disparar alertas aunque no se mire
  setInterval(() => {
    if (!el('view-monitor').classList.contains('hidden')) UI.loadMonitor();
    else fetch(App.apiBase() + '/api/v1/monitor', { credentials: 'include' })
      .then(r => r.json()).then(d => { App.net(true); if (d.filamento_bajo?.length) Notif.check(d.filamento_bajo); })
      .catch(() => App.net(false));
  }, 60000);
});
