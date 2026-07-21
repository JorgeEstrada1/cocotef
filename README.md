# 🖨️ Taller 3D — Gestión y control financiero · v1.9

Sistema local (Flask + SQLite) para controlar impresiones, costos, inventario y
"la plata" de un emprendimiento de impresión 3D manejado por 2 socios. Con
autenticación, diseño **Dark Premium**, un **Agente Asistente** de producción,
**carga inteligente de G-code / 3MF** y control financiero en **Bolivianos (Bs.)**.

---

## 🚀 Arranque en un clic (recomendado)

Haz **doble clic en `arrancar_sistema.bat`**. El script activa el entorno
virtual, abre el navegador en http://127.0.0.1:5000 y lanza el servidor.

> La primera vez debe existir el entorno virtual `venv/`. Si no lo tienes, créalo
> una sola vez con los pasos de abajo.

## Arranque manual (Windows / PowerShell)

```powershell
cd C:\Users\cocoyote\Desktop\inventario

# 1. Crear entorno virtual (una sola vez)
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Ejecutar
python app.py
```

Luego abre el navegador en: http://127.0.0.1:5000

---

## 🔐 Acceso (autenticación)

Protegido con inicio de sesión (Flask-Login + bcrypt). En el primer arranque se
siembran automáticamente dos usuarios:

| Usuario | Contraseña inicial |
|---------|--------------------|
| `jorge` | `jorge123`         |
| `tefi`  | `tefi123`          |

> ⚠️ **Cambia estas contraseñas** editando `SOCIOS_SEED` en `app.py` (y borrando
> luego `instance/taller3d.db` para re-sembrar), o generando un nuevo hash con
> `bcrypt.generate_password_hash("nueva").decode()`.

Todas las rutas requieren sesión iniciada. Cada proyecto, gasto o inversión se
asocia automáticamente al usuario autenticado que lo registra. La barra superior
saluda al usuario ("Hola, Jorge") e incluye botón de cerrar sesión.

La BD SQLite se crea sola en `instance/taller3d.db`. Si ya existía una BD de una
versión anterior, **al arrancar se migra automáticamente** (añade columnas nuevas
con `ALTER TABLE` y crea tablas nuevas sin borrar datos ni relaciones).

---

## ☁️ Novedades de la v1.9 — Arquitectura híbrida (Backend PythonAnywhere + PWA en Vercel)

El **backend/API Flask** vive en PythonAnywhere y el **frontend/PWA** de la App de
Producción se despliega como sitio estático en **Vercel**, consumiendo la API por HTTP.

### API REST v1 (Flask + CORS)
- **CORS** habilitado (`flask-cors`) solo para `/api/*`. Orígenes permitidos vía
  la variable de entorno `CORS_ORIGINS` (coma-separada; el dominio de Vercel).
- Endpoints (JSON):
  | Método | Ruta | Descripción |
  |--------|------|-------------|
  | `GET`  | `/api/v1/pedidos-activos` | Pedidos vigentes: `id, nombre, cliente, estado, foto_url, fecha_entrega_iso`. |
  | `PATCH`| `/api/v1/pedidos/<id>/estado` | Cambia el estado (JSON `{"estado": "..."}`; acepta alias como *En impresión*, *Listo*). |
  | `GET`  | `/api/v1/filamentos-stock` | Filamentos: `id, marca, material, color_hex, stock_gramos, alerta_bajo_stock`. |
  | `GET`  | `/api/v1/imagenes/<archivo>` | Sirve las fotos **públicamente** (para que Vercel las renderice). |
- Las `foto_url` son **absolutas** (dominio del backend), tomadas de `BACKEND_BASE_URL`.
- **API key opcional**: si defines `MOBILE_API_KEY`, la API exige el header `X-API-Key`.

### Frontend en Vercel (`/public` + `vercel.json`)
- PWA pura **HTML/JS/Tailwind** (sin build): tarjetas verticales Dark Premium,
  **timer countdown** con badges (🟢 >12h · 🟠 <12h · 🔴 animado <3h/vencido),
  **acciones rápidas con Fetch** (PATCH sin recargar) y **stock de filamentos**
  con muestra de color HEX y gramos restantes.
- `public/config.js` define `API_BASE_URL` (por defecto
  `https://cocoteff.pythonanywhere.com`) y `API_KEY` opcional.
- `manifest.json` (`start_url: /`) + `sw.js` → **instalable** en Android (Chrome)
  e iOS (Safari), con caché del *app shell*.
- `vercel.json` publica la carpeta `public/` como sitio estático y fija el header
  `Service-Worker-Allowed: /` para el Service Worker.

### Variables de entorno del backend
| Variable | Uso |
|----------|-----|
| `CORS_ORIGINS` | Dominios permitidos para la API (ej. `https://taller3d.vercel.app`). |
| `BACKEND_BASE_URL` | URL absoluta del backend para las `foto_url` (ej. `https://cocoteff.pythonanywhere.com`). |
| `MOBILE_API_KEY` | (Opcional) Clave que la PWA debe enviar en `X-API-Key`. |

## 📱 Novedades de la v1.8 — App de Taller (móvil / PWA)

### Vista móvil de producción (`/mobile`)
- Plantilla `mobile.html` independiente, **Dark Premium**, pensada para usar con
  **una mano**: tarjetas verticales y **barra de pestañas inferior** (Pedidos / Filamentos).
- **Tarjetas de pedidos en vivo**: foto principal de la pieza, nombre, cliente y
  **badge de estado**. Cada pedido con fecha de entrega muestra un **timer countdown**
  en JavaScript con colores de alerta:
  🟢 **verde** (tiempo de sobra) · 🟠 **naranja** (< 12 h) · 🔴 **rojo animado**
  (vencido o < 3 h).
- **Cambio rápido de estado** con un toque (**✅ Listo**, **📦 Entregado**, o el
  selector *Más…*) vía **AJAX** (`fetch`): actualiza la tarjeta sin recargar la
  pantalla; al marcar *Entregado* la tarjeta sale del tablero con animación.
- **🧵 Stock de Filamentos** rápido: cada rollo como barra compacta con **indicador
  de color**, material, gramos restantes, equivalente en **rollos**, barra de
  progreso y **alerta de bajo stock**.

### PWA (instalable)
- `/` **redirige automáticamente** a `/mobile` desde teléfonos (detección por
  User-Agent); `?desktop=1` fuerza el panel completo.
- `manifest.json` (con `start_url: /mobile`, íconos e identidad) y `sw.js`
  (Service Worker servido desde la raíz, alcance `/`) → la app se puede **instalar**
  y abre por defecto en la vista móvil, con caché básica offline.

## 🆕 Novedades de la v1.7

### A. 📷 Fotos en Proyectos / Ventas
- Cada proyecto puede tener una **foto de la pieza** (JPG, PNG, WEBP o JPEG).
- Se sube desde los formularios de **crear** y **editar** proyecto (con vista previa
  instantánea). El archivo se guarda en `instance/uploads/imagenes/` con un
  nombre **UUID único** (vía `secure_filename` + `uuid`) para evitar colisiones.
- En la tabla de proyectos se muestra una **miniatura**; al hacer click se abre en
  **tamaño completo** (lightbox). Al eliminar el proyecto —o reemplazar/quitar la
  foto— el archivo físico también se borra del disco.

### B. 🔧 Sistema / Configuración (mantenimiento y despliegue)
Nueva pestaña **🔧 Sistema** en la barra de navegación con:
- **📥 Exportar base de datos (.db):** descarga directa del SQLite como respaldo.
- **📤 Importar / Restaurar:** sube un `.db` para reemplazar los datos (ideal para
  migrar local ↔ PythonAnywhere). Valida la cabecera SQLite, exige **confirmación**
  de seguridad y crea un **respaldo `.bak` automático** antes de sobrescribir.
- **🔄 Sincronizar código (git pull):** ejecuta `git pull` en el servidor.
- **🚀 Recargar web (PythonAnywhere):** reinicia la app vía la API de PythonAnywhere
  usando las variables de entorno `PA_USERNAME`, `PA_DOMAIN` y `PA_API_TOKEN`.

## 💱 Novedades de la v1.5

### A. Moneda global en Bolivianos (Bs.)
Toda la aplicación muestra los montos en **Bs.** en lugar del signo `$`:
Dashboard, Proyectos / Ventas, Gastos, Balance, Deudas e Inversiones, la
**gráfica** de Chart.js (tooltips y eje Y) y las **exportaciones CSV**.

### B. Balance: Liquidación / Saldar Cuentas entre socios
- En el Balance mensual, un botón **"🤝 Saldar Cuentas / Registrar Pago a Socio"**
  abre un **modal** que confirma quién le paga a quién y el **monto exacto** del
  ajuste calculado por la app.
- Al confirmar se registra un movimiento de **transferencia entre socios**
  (modelo `Liquidacion`) que deja el ajuste del mes en **Bs. 0** (a mano).
- El monto se **recalcula en el servidor** (no se confía en el cliente).
- **Regla clave:** la liquidación solo reacomoda el "en mano" de cada socio;
  **no** afecta ingresos, gastos ni la ganancia neta / gráfica financiera.

### C. Módulo independiente de Deudas e Inversiones de Capital
- Nueva pestaña **"Deudas e Inversiones"** en la barra de navegación.
- Registra compras de **activo fijo / maquinaria** (ej. "Compra Bambu Lab A2")
  con `monto_total`, `aporte_jorge`, `aporte_tefi`, `deuda_pendiente`, `estado`
  (Pendiente / Saldada) y `fecha` (modelo `Inversion`).
- Calcula la **deuda para quedar 50/50** en el activo (mitad de la diferencia de
  aportes), muestra **deudor → acreedor** y el progreso de abonos.
- Botón **"Abonar"** por fila para reducir el saldo hasta liquidarlo; al llegar a
  Bs. 0 la inversión pasa a **"Saldada"** automáticamente.
- **Regla clave:** es **100% independiente** de los ingresos, gastos operativos y
  ganancias. No se mezcla con la caja chica ni con la gráfica financiera mensual.

---

## 🧩 Funcionalidades

### 1. Proyectos / Ventas (módulo unificado)
- Piezas con cliente y **estado**:
  `Diseñando → Por imprimir → Imprimiendo → Terminado → Entregado`.
- Datos técnicos: peso (g), tiempo estimado (h), filamento (tipo/color).
- Costo de filamento por pieza automático = `peso × (precio_rollo / peso_rollo)`.
- **Cobranza integrada** en el proyecto: `precio_total`, `adelanto` y
  `saldo_pendiente` (= precio − adelanto), con badge **✓ Pagado** cuando el saldo
  llega a Bs. 0.
- **Fecha de entrega** por proyecto, con badges de urgencia (⏰ retrasado ·
  🔥 vence hoy · ⚡ en N días · ✓ entregado).
- Tabla "de un vistazo": Nombre, Cliente, Estado (dropdown), Precio total,
  Adelanto, Saldo pendiente, quién registró y acciones (Editar · G-Code · Eliminar).

### 2. Control financiero
- Gastos por categoría (filamento, cajas, envíos, luz, etc.).
- **Regla contable de ingresos:** el precio de un pedido **solo se reconoce** como
  ingreso cuando el estado es **Entregado** o su **saldo pendiente es Bs. 0**. Los
  adelantos / pagos parciales **no** suman a Ingresos Totales ni a la gráfica hasta
  que el pedido esté cancelado por completo.
- Ganancia neta = Ingresos reconocidos − Gastos.
- **Filtro por mes/año** en Dashboard, Balance y Gastos (por defecto el mes actual).
- **Exportación CSV** (compatible con Excel, BOM UTF-8) con montos en Bs.
- **Gráfico** Ingresos vs. Gastos (Chart.js) en el Dashboard.

### 3. Multiusuario (2 socios) y reparto
- Panel de balance: cuánto cobró (pedidos entregados/saldados) y aportó cada uno,
  cuánto le corresponde (50%) y el ajuste para quedar parejos.
- **Liquidación** entre socios para dejar el ajuste del mes en Bs. 0 (ver
  Novedades v1.5 · B).

### 4. 📉 Alertas de stock crítico (inventario)
- Campo `stock_minimo` por filamento (default 200 g), editable inline.
- Cálculo de gramos restantes = peso del rollo − consumo de proyectos impresos
  (Imprimiendo / Terminado / Entregado). El estado **"Por imprimir" no consume**
  (la pieza está en cola pero aún no se imprimió).
- Tarjeta de alerta llamativa (ámbar/naranja) en el Dashboard y **badge de
  notificación global** junto a "Filamentos" en la barra de navegación.

### 5. 🧠 Agente Asistente de Producción (local, sin APIs externas)
- **Alertas de vencimiento**: detecta proyectos no entregados que vencen en ≤2
  días o ya retrasados y los anuncia ("🤖 Jorge / Tefi: Tienen X pedidos
  urgentes…" / "Producción al día").
- **🧭 Brújula de Tendencias**: ideas virales de impresión 3D para creadores de
  contenido, cada una con un tip de Reel. Se edita en `TENDENCIAS_VIRALES`
  (`app.py`).
- Tarjeta premium con glow cyan/indigo e íconos animados.

### 6. 📄 Carga inteligente de G-code / 3MF
- **Autocompletado**: al subir el `.gcode`/`.3mf` del slicer en el formulario de
  proyecto, se leen los metadatos con **regex** (peso en gramos y tiempo de
  impresión) y se rellenan Peso y Tiempo automáticamente vía AJAX, sin recargar.
- **Multi-slicer**: soporta PrusaSlicer / OrcaSlicer / Bambu Studio /
  SuperSlicer (`.gcode`) y `.3mf` (ZIP con configs/XML internos), incluyendo
  suma de varios filamentos y formatos de tiempo `Xh Ym Zs`, `TIME:` (Cura) y
  `prediction` (segundos).
- **Almacenamiento local**: el archivo se guarda en `instance/gcodes/` con un
  nombre **UUID** (evita colisiones) y se registra en `Proyecto.gcode_filename`.
- **Descarga integrada**: botón ⬇ cyan junto al nombre en la tabla y en la vista
  de edición (solo si el proyecto tiene archivo).
- **Reemplazo en edición**: subir un archivo nuevo reparsea peso/tiempo, borra el
  anterior del disco y guarda el nuevo; si no se sube nada, el archivo actual se
  conserva intacto.
- **Sin huérfanos**: al eliminar un proyecto se borra también su archivo físico.
- Límite de subida: 128 MB (`MAX_CONTENT_LENGTH`).

---

## 📁 Estructura

```
inventario/
├── arrancar_sistema.bat   # Lanzador de un clic (venv + navegador + Flask)
├── app.py                 # App Flask: rutas, auth, balance, liquidación, inversiones
├── models.py              # Modelos SQLite (User, Filamento, Proyecto, Venta, Gasto, Liquidacion, Inversion)
├── config.py              # Configuración (ruta BD, clave secreta)
├── requirements.txt       # Flask, Flask-SQLAlchemy, Flask-Login, Flask-Bcrypt
├── README.md
├── instance/
│   ├── taller3d.db        # BD SQLite (se genera automáticamente)
│   └── gcodes/            # Archivos G-code/3MF subidos (nombre UUID)
└── templates/
    ├── base.html          # Layout, nav con saludo/logout y badge de alertas
    ├── login.html         # Pantalla de inicio de sesión (Dark Premium)
    ├── dashboard.html     # Panel: agente, alertas, gráfico, balance, KPIs
    ├── proyectos.html     # Proyectos / Ventas unificado (cobranza + estados + G-code)
    ├── editar_proyecto.html
    ├── filamentos.html    # Rollos, precio/gramo, stock mínimo y estado
    ├── ventas.html        # Legacy de ventas (fuera de la nav; datos preservados)
    ├── editar_venta.html
    ├── gastos.html
    ├── editar_gasto.html
    ├── inversiones.html   # Deudas e Inversiones de Capital (módulo independiente)
    ├── balance.html       # Reparto 50/50, ajuste y liquidación entre socios
    └── _selector_mes.html # Selector de mes reutilizable
```

---

## 🛠️ Notas técnicas

- **Migraciones**: `migrar_esquema()` y `migrar_y_sembrar_usuarios()` corren en
  cada arranque; añaden columnas nuevas (`stock_minimo`, `fecha_entrega`,
  `gcode_filename`, `precio_total`, `adelanto`, auth) de forma idempotente y sin
  perder datos. Las tablas nuevas (`liquidaciones`, `inversiones`) las crea
  `db.create_all()` sin afectar las existentes.
- **Independencia contable**: el módulo de Deudas e Inversiones y las
  liquidaciones entre socios se calculan aparte de los ingresos/gastos operativos;
  no alteran la ganancia neta ni la gráfica financiera mensual.
- **Estilo**: Tailwind CSS por CDN con paleta dark propia (`#090d16` fondo,
  `#151c2c` tarjetas, acentos teal/cyan). Sin build de Node/npm.
- **`instance/`, `venv/`, `*.db` y `.claude/`** están en `.gitignore`.
