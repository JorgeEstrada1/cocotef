# 🖨️ Taller 3D — Gestión y control financiero

Sistema local para controlar impresiones, costos y "la plata" de un emprendimiento
de impresión 3D manejado por 2 socios.

## Cómo ejecutar (Windows / PowerShell)

```powershell
cd C:\Users\cocoyote\Desktop\inventario

# 1. Crear entorno virtual (recomendado)
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Ejecutar
python app.py
```

Luego abre el navegador en: http://127.0.0.1:5000

## 🔐 Acceso (autenticación)

El sistema está protegido con inicio de sesión (Flask-Login + bcrypt). En el
primer arranque se siembran automáticamente dos usuarios:

| Usuario | Contraseña inicial |
|---------|--------------------|
| `jorge` | `jorge123`         |
| `tefi`  | `tefi123`          |

> ⚠️ **Cambia estas contraseñas** editando `SOCIOS_SEED` en `app.py` (y borrando
> luego `instance/taller3d.db` para re-sembrar), o generando un nuevo hash con
> `bcrypt.generate_password_hash("nueva").decode()`.

Todas las rutas (Panel, Proyectos, Ventas, Gastos, Balance) requieren sesión
iniciada. Cada venta, gasto o proyecto se asocia automáticamente al usuario
autenticado que lo registra.

La base de datos SQLite se crea sola en `instance/taller3d.db` la primera vez.
Si ya existía una BD de la v1.0, al arrancar se migra automáticamente (se añaden
las columnas de autenticación y los 2 socios se convierten en jorge/tefi
conservando todos los datos y relaciones).

## Estructura

```
inventario/
├── app.py              # App Flask + rutas + lógica de balance
├── models.py           # Modelos SQLite (Usuario, Filamento, Proyecto, Venta, Gasto)
├── config.py           # Configuración (ruta BD, clave secreta)
├── requirements.txt
├── README.md
├── instance/
│   └── taller3d.db     # BD SQLite (se genera automáticamente)
└── templates/
    ├── base.html
    ├── dashboard.html  # Panel general
    ├── proyectos.html  # Piezas + estados + costo de filamento
    ├── filamentos.html # Rollos y precio por gramo
    ├── ventas.html
    ├── gastos.html
    └── balance.html    # Reparto 50/50 y ajuste entre socios
```

## Funcionalidades

**1. Control de impresiones y costos**
- Registro de piezas con cliente y estado (Diseñando → Imprimiendo → Terminado → Entregado).
- Datos técnicos: peso (g), tiempo estimado (h), filamento (tipo/color).
- Cálculo automático del costo de filamento por pieza = `peso × (precio_rollo / peso_rollo)`.

**2. Control financiero**
- Ventas (monto, método de pago, fecha, socio, proyecto opcional).
- Gastos por categoría (filamento, cajas, envíos, luz, etc.).
- Ganancia neta = Ingresos − Gastos.

**3. Multiusuario (2 socios)**
- Cada venta/gasto se asigna a un socio.
- Panel de balance: cuánto cobró y aportó cada uno, cuánto le corresponde (50%)
  y el ajuste necesario para quedar parejos.
```
