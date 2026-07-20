# 🖨️ Taller 3D — Gestión y control financiero · v1.3

Sistema local (Flask + SQLite) para controlar impresiones, costos, inventario y
"la plata" de un emprendimiento de impresión 3D manejado por 2 socios. Con
autenticación, diseño **Dark Premium**, un **Agente Asistente** de producción y
**carga inteligente de G-code / 3MF**.

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

Todas las rutas requieren sesión iniciada. Cada venta, gasto o proyecto se asocia
automáticamente al usuario autenticado que lo registra. La barra superior saluda
al usuario ("Hola, Jorge") e incluye botón de cerrar sesión.

La BD SQLite se crea sola en `instance/taller3d.db`. Si ya existía una BD de una
versión anterior, **al arrancar se migra automáticamente** (añade columnas nuevas
con `ALTER TABLE` sin borrar datos ni relaciones).

---

## 🧩 Funcionalidades

### 1. Control de impresiones y costos
- Piezas con cliente y estado (Diseñando → Imprimiendo → Terminado → Entregado).
- Datos técnicos: peso (g), tiempo estimado (h), filamento (tipo/color).
- Costo de filamento por pieza automático = `peso × (precio_rollo / peso_rollo)`.
- **Fecha de entrega** por proyecto, con columna y badges de urgencia en la tabla
  (⏰ retrasado · 🔥 vence hoy · ⚡ en N días · ✓ entregado · "Sin fecha").

### 2. Control financiero
- Ventas (monto, método de pago, fecha, proyecto opcional).
- Gastos por categoría (filamento, cajas, envíos, luz, etc.).
- Ganancia neta = Ingresos − Gastos.
- **Filtro por mes/año** en Dashboard, Balance, Ventas y Gastos (por defecto el
  mes actual, para no mezclar cuentas).
- **Exportación CSV** (compatible con Excel, BOM UTF-8) de ventas y gastos,
  respetando el mes seleccionado.
- **Gráfico** Ingresos vs. Gastos (Chart.js) en el Dashboard.

### 3. Multiusuario (2 socios)
- Panel de balance: cuánto cobró y aportó cada uno, cuánto le corresponde (50%)
  y el ajuste necesario para quedar parejos.

### 4. 📉 Alertas de stock crítico (inventario)
- Campo `stock_minimo` por filamento (default 200 g), editable inline.
- Cálculo de gramos restantes = peso del rollo − consumo de proyectos impresos
  (Imprimiendo / Terminado / Entregado).
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
├── app.py                 # App Flask: rutas, auth, balance, alertas, agente
├── models.py              # Modelos SQLite (User, Filamento, Proyecto, Venta, Gasto)
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
    ├── proyectos.html     # Piezas, estados, costo, fecha de entrega + badges
    ├── editar_proyecto.html
    ├── filamentos.html    # Rollos, precio/gramo, stock mínimo y estado
    ├── ventas.html
    ├── editar_venta.html
    ├── gastos.html
    ├── editar_gasto.html
    ├── balance.html       # Reparto 50/50 y ajuste entre socios
    └── _selector_mes.html # Selector de mes reutilizable
```

---

## 🛠️ Notas técnicas

- **Migraciones**: `migrar_esquema()` y `migrar_y_sembrar_usuarios()` corren en
  cada arranque; añaden columnas nuevas (`stock_minimo`, `fecha_entrega`,
  `gcode_filename`, auth) de forma idempotente y sin perder datos.
- **Estilo**: Tailwind CSS por CDN con paleta dark propia (`#090d16` fondo,
  `#151c2c` tarjetas, acentos teal/cyan). Sin build de Node/npm.
- **`instance/`, `venv/`, `*.db` y `.claude/`** están en `.gitignore`.
