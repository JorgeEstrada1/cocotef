"""
Taller 3D — Sistema de gestión y control financiero para impresión 3D.
Ejecutar:  python app.py   ->  http://127.0.0.1:5000
"""
import os
import io
import csv
import re
import uuid
import shutil
import zipfile
import subprocess
import urllib.request
import urllib.error
from datetime import date, datetime

from flask import (Flask, render_template, request, redirect, url_for, flash,
                   Response, jsonify, send_from_directory)
from werkzeug.utils import secure_filename

EXTENSIONES_GCODE = (".gcode", ".gco", ".3mf")
EXTENSIONES_IMAGEN = (".jpg", ".jpeg", ".png", ".webp")
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from sqlalchemy import extract, inspect, text

from config import Config
from models import (db, User, Filamento, Proyecto, Venta, Gasto,
                    Liquidacion, Inversion, AbonoInversion,
                    Feria, FeriaInventario, FeriaVenta,
                    FotoPedido, Impresora,
                    FilamentoTienda, VentaFilamento,
                    DeudaFilamento, AbonoDeudaFilamento,
                    PosibleCliente, EncargoFilamento, ProductoCatalogo)


def fmt_bs(v):
    """Formatea Bolivianos conservando decimales solo cuando existen."""
    v = float(v or 0)
    if v == int(v):
        return "Bs. {:,.0f}".format(v)
    return "Bs. {:,.2f}".format(v)

MESES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
         "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

# Traducción de nombre de color (filamento) -> HEX para el indicador visual.
# Usado por el filtro de plantilla `color_hex` y por la API REST móvil.
COLORES_HEX = {
    "blanco": "#f8fafc", "negro": "#111827", "gris": "#9ca3af",
    "plata": "#cbd5e1", "plateado": "#cbd5e1", "rojo": "#ef4444",
    "naranja": "#f97316", "naranjo": "#f97316", "amarillo": "#eab308",
    "dorado": "#d4af37", "oro": "#d4af37", "verde": "#22c55e",
    "menta": "#34d399", "turquesa": "#2dd4bf", "cyan": "#06b6d4",
    "celeste": "#38bdf8", "azul": "#3b82f6", "morado": "#a855f7",
    "violeta": "#8b5cf6", "lila": "#c4b5fd", "rosa": "#ec4899",
    "rosado": "#ec4899", "fucsia": "#d946ef", "cafe": "#92400e",
    "café": "#92400e", "marron": "#92400e", "marrón": "#92400e",
    "beige": "#e7d8b1", "transparente": "#e5e7eb", "natural": "#e5e7eb",
}


def nombre_a_hex(nombre):
    """Devuelve un color HEX a partir del nombre libre del filamento."""
    if not nombre:
        return "#64748b"
    n = str(nombre).strip().lower()
    if n.startswith("#") and len(n) in (4, 7):
        return n
    for clave, hexv in COLORES_HEX.items():   # coincidencia por palabra contenida
        if clave in n:
            return hexv
    return "#64748b"


# Alias de estados aceptados por la API móvil -> estado canónico del modelo.
# Permite que el frontend use nombres amigables ("En impresión", "Listo").
ALIAS_ESTADO = {
    "en espera": "En espera", "espera": "En espera", "por diseñar": "En espera",
    "por disenar": "En espera", "cola diseño": "En espera",
    "diseñando": "Diseñando", "disenando": "Diseñando", "diseno": "Diseñando",
    "por imprimir": "Por imprimir", "en cola": "Por imprimir",
    "imprimiendo": "Imprimiendo", "en impresión": "Imprimiendo",
    "en impresion": "Imprimiendo", "imprimiendo…": "Imprimiendo",
    "terminado": "Terminado", "listo": "Terminado", "lista": "Terminado",
    "entregado": "Entregado", "entregada": "Entregado", "enviado": "Entregado",
    "cancelado": "Cancelado", "cancelada": "Cancelado", "anulado": "Cancelado",
}


def normalizar_estado(valor):
    """Normaliza un estado entrante (canónico o alias) al canónico o None."""
    if not valor:
        return None
    v = str(valor).strip()
    if v in Proyecto.ESTADOS:
        return v
    return ALIAS_ESTADO.get(v.lower())

# Cotizador automático: precio sugerido a partir del costo de filamento, las
# horas de máquina y un margen. Valores en Bs.; ajústalos a tu realidad.
COTIZADOR = {
    "tarifa_hora": 3.0,     # Bs. por hora de impresión (desgaste + luz + tiempo)
    "margen": 1.6,          # multiplicador sobre el costo (ganancia)
    "minimo": 15.0,         # precio mínimo por pedido (setup)
}


def cotizar_precio(costo_filamento, horas):
    """Precio sugerido (Bs.) redondeado a múltiplos de 5, con piso mínimo."""
    base = (float(costo_filamento or 0) + float(horas or 0) * COTIZADOR["tarifa_hora"])
    sugerido = base * COTIZADOR["margen"]
    sugerido = max(sugerido, COTIZADOR["minimo"])
    return round(sugerido / 5.0) * 5.0


# Credenciales sembradas por defecto en el primer arranque.
# IMPORTANTE: cambia estas contraseñas después de iniciar sesión.
SOCIOS_SEED = [
    {"username": "jorge", "nombre": "Jorge", "color": "#2dd4bf", "password": "jorge123"},
    {"username": "tefi",  "nombre": "Tefi",  "color": "#22d3ee", "password": "tefi123"},
]

# Sugerencias del "Agente" (Brújula de Tendencias). Locales, sin APIs externas.
TENDENCIAS_VIRALES = [
    {"icono": "🗂️", "titulo": "Organizadores de escritorio modulares para setups tech",
     "tip": "Idea de Reel: arma el organizador pieza por pieza en un timelapse y cierra con el setup ordenado."},
    {"icono": "🦴", "titulo": "Modelos anatómicos y maquetas mecánicas para estudiantes",
     "tip": "Idea de Reel: muestra el modelo girando 360° y explica una curiosidad en 15 segundos."},
    {"icono": "📷", "titulo": "Soportes de cámara y gadgets útiles (Pocket 3, GoPro, celular)",
     "tip": "Idea de Reel: graba un timelapse de la impresión con tu Pocket 3 y muestra el accesorio en uso."},
    {"icono": "🎮", "titulo": "Soportes de control y auriculares para gamers",
     "tip": "Idea de Reel: 'Antes y después' del escritorio gamer con el soporte instalado."},
    {"icono": "🪴", "titulo": "Materas geométricas y decoración minimalista",
     "tip": "Idea de Reel: satisfying del relleno de tierra + plantita, con música trend."},
]

bcrypt = Bcrypt()
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "Inicia sesión para continuar."


@login_manager.user_loader
def cargar_usuario(user_id):
    return db.session.get(User, int(user_id))


def crear_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    # Límite de subida para archivos de slicer (.gcode pueden ser grandes)
    app.config.setdefault("MAX_CONTENT_LENGTH", 128 * 1024 * 1024)  # 128 MB

    # Asegura que existan las carpetas de datos locales
    os.makedirs(os.path.join(app.root_path, "instance"), exist_ok=True)
    os.makedirs(os.path.join(app.root_path, "instance", "gcodes"), exist_ok=True)
    os.makedirs(os.path.join(app.root_path, "instance", "uploads", "imagenes"), exist_ok=True)

    # CORS solo para la API móvil (/api/*). Los orígenes permitidos (el dominio
    # de Vercel) se definen en la variable de entorno CORS_ORIGINS separada por
    # comas; por defecto "*" para facilitar el desarrollo.
    origenes = os.environ.get("CORS_ORIGINS", "*")
    if origenes != "*":
        origenes = [o.strip() for o in origenes.split(",") if o.strip()]
    CORS(app, resources={r"/api/*": {"origins": origenes}})

    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)

    with app.app_context():
        db.create_all()
        migrar_esquema()
        migrar_y_sembrar_usuarios()

    registrar_rutas(app)
    return app


def migrar_esquema():
    """Añade columnas nuevas a BDs existentes sin borrar datos (SQLite ALTER)."""
    with db.engine.begin() as conn:
        fil_cols = [c["name"] for c in inspect(db.engine).get_columns("filamentos")]
        if "stock_minimo" not in fil_cols:
            conn.execute(text(
                "ALTER TABLE filamentos ADD COLUMN stock_minimo FLOAT DEFAULT 200"))

        proy_cols = [c["name"] for c in inspect(db.engine).get_columns("proyectos")]
        if "fecha_entrega" not in proy_cols:
            conn.execute(text("ALTER TABLE proyectos ADD COLUMN fecha_entrega DATE"))
        if "gcode_filename" not in proy_cols:
            conn.execute(text("ALTER TABLE proyectos ADD COLUMN gcode_filename VARCHAR(120)"))
        if "precio_total" not in proy_cols:
            conn.execute(text("ALTER TABLE proyectos ADD COLUMN precio_total FLOAT DEFAULT 0"))
        if "adelanto" not in proy_cols:
            conn.execute(text("ALTER TABLE proyectos ADD COLUMN adelanto FLOAT DEFAULT 0"))
        if "imagen_filename" not in proy_cols:
            conn.execute(text("ALTER TABLE proyectos ADD COLUMN imagen_filename VARCHAR(120)"))
        if "horas_impresion" not in proy_cols:
            conn.execute(text("ALTER TABLE proyectos ADD COLUMN horas_impresion FLOAT DEFAULT 0"))
        if "inicio_impresion" not in proy_cols:
            conn.execute(text("ALTER TABLE proyectos ADD COLUMN inicio_impresion DATETIME"))
        # --- v2.2: cobro manual, deuda interna, WhatsApp, cola y link público ---
        if "telefono" not in proy_cols:
            conn.execute(text("ALTER TABLE proyectos ADD COLUMN telefono VARCHAR(40)"))
        if "orden" not in proy_cols:
            conn.execute(text("ALTER TABLE proyectos ADD COLUMN orden INTEGER DEFAULT 0"))
        if "public_token" not in proy_cols:
            conn.execute(text("ALTER TABLE proyectos ADD COLUMN public_token VARCHAR(24)"))
        if "cobrador_id" not in proy_cols:
            conn.execute(text("ALTER TABLE proyectos ADD COLUMN cobrador_id INTEGER"))
        if "saldado" not in proy_cols:
            conn.execute(text("ALTER TABLE proyectos ADD COLUMN saldado BOOLEAN DEFAULT 0"))
        if "fecha_saldado" not in proy_cols:
            conn.execute(text("ALTER TABLE proyectos ADD COLUMN fecha_saldado DATETIME"))
        if "fecha_entregado" not in proy_cols:
            conn.execute(text("ALTER TABLE proyectos ADD COLUMN fecha_entregado DATETIME"))

        # --- Módulo de Ferias (v2.0+): métricas de material y funciones de venta ---
        tablas = inspect(db.engine).get_table_names()
        if "ferias" in tablas:
            feria_cols = [c["name"] for c in inspect(db.engine).get_columns("ferias")]
            if "costo_material" not in feria_cols:
                conn.execute(text("ALTER TABLE ferias ADD COLUMN costo_material FLOAT DEFAULT 0"))
        if "ferias_inventario" in tablas:
            inv_cols = [c["name"] for c in inspect(db.engine).get_columns("ferias_inventario")]
            if "cantidad_merma" not in inv_cols:
                conn.execute(text("ALTER TABLE ferias_inventario ADD COLUMN cantidad_merma INTEGER DEFAULT 0"))
        if "ferias_ventas" in tablas:
            venta_cols = [c["name"] for c in inspect(db.engine).get_columns("ferias_ventas")]
            if "tipo" not in venta_cols:
                conn.execute(text("ALTER TABLE ferias_ventas ADD COLUMN tipo VARCHAR(20) DEFAULT 'venta'"))
            if "nota" not in venta_cols:
                conn.execute(text("ALTER TABLE ferias_ventas ADD COLUMN nota VARCHAR(200)"))

        # --- v2.5: alerta de reposición en tienda y seguimiento de leads ---
        if "filamentos_tienda" in tablas:
            ft_cols = [c["name"] for c in inspect(db.engine).get_columns("filamentos_tienda")]
            if "stock_minimo" not in ft_cols:
                conn.execute(text(
                    "ALTER TABLE filamentos_tienda ADD COLUMN stock_minimo INTEGER DEFAULT 2"))
        if "posibles_clientes" in tablas:
            pc_cols = [c["name"] for c in inspect(db.engine).get_columns("posibles_clientes")]
            if "fecha_estado" not in pc_cols:
                conn.execute(text(
                    "ALTER TABLE posibles_clientes ADD COLUMN fecha_estado DATETIME"))

    # Backfill: genera token de seguimiento a los pedidos que aún no tienen.
    import secrets as _secrets
    sin_token = Proyecto.query.filter(
        (Proyecto.public_token.is_(None)) | (Proyecto.public_token == "")).all()
    if sin_token:
        usados = {p.public_token for p in Proyecto.query.all() if p.public_token}
        for p in sin_token:
            tok = _secrets.token_urlsafe(8)
            while tok in usados:
                tok = _secrets.token_urlsafe(8)
            usados.add(tok)
            p.public_token = tok
        db.session.commit()


def migrar_y_sembrar_usuarios():
    """
    Evoluciona la tabla 'usuarios' para autenticación y siembra jorge/tefi.
    - Añade las columnas username/password_hash si no existen (sin borrar datos).
    - Convierte socios legacy (sin username) en jorge/tefi conservando su id
      (y por tanto las claves foráneas de ventas/gastos/proyectos).
    """
    cols = [c["name"] for c in inspect(db.engine).get_columns("usuarios")]
    with db.engine.begin() as conn:
        if "username" not in cols:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN username VARCHAR(80)"))
        if "password_hash" not in cols:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN password_hash VARCHAR(200)"))

    def _hash(pw):
        return bcrypt.generate_password_hash(pw).decode("utf-8")

    usuarios = User.query.order_by(User.id).all()
    if not usuarios:
        # BD nueva: crea jorge y tefi
        for s in SOCIOS_SEED:
            db.session.add(User(username=s["username"], nombre=s["nombre"],
                                color=s["color"], password_hash=_hash(s["password"])))
    else:
        # Normaliza filas legacy (sin username) a jorge/tefi por orden de id
        legacy = [u for u in usuarios if not u.username]
        for u, s in zip(legacy, SOCIOS_SEED):
            u.username, u.nombre, u.color = s["username"], s["nombre"], s["color"]
            u.password_hash = _hash(s["password"])
        # Crea los que falten (por si había menos de 2 socios)
        existentes = {u.username for u in User.query.all() if u.username}
        for s in SOCIOS_SEED:
            if s["username"] not in existentes:
                db.session.add(User(username=s["username"], nombre=s["nombre"],
                                    color=s["color"], password_hash=_hash(s["password"])))
    db.session.commit()


# --------------------------------------------------------------------------
#  Helpers de periodo (filtros por mes/año)
# --------------------------------------------------------------------------
def parse_periodo(valor):
    """Convierte 'YYYY-MM' (input type=month) a (año, mes). Default: mes actual."""
    if valor:
        try:
            y, m = valor.split("-")
            y, m = int(y), int(m)
            if 1 <= m <= 12:
                return y, m
        except (ValueError, AttributeError):
            pass
    hoy = date.today()
    return hoy.year, hoy.month


def periodo_str(anio, mes):
    return f"{anio:04d}-{mes:02d}"


def etiqueta_periodo(anio, mes):
    return f"{MESES[mes]} {anio}"


def mes_relativo(anio, mes, delta):
    """Devuelve (año, mes) desplazado 'delta' meses (puede ser negativo)."""
    total = (anio * 12 + (mes - 1)) + delta
    return total // 12, (total % 12) + 1


# --------------------------------------------------------------------------
#  Lógica financiera (el corazón del "conteo de la plata")
# --------------------------------------------------------------------------
def calcular_balance(anio=None, mes=None):
    """
    Devuelve el resumen financiero global y el balance por socio.

    Regla contable (unificación Proyectos/Ventas):
      - El ingreso de un pedido SOLO se reconoce cuando está 'Entregado' o su
        saldo pendiente es 0 (pagado en su totalidad). Los adelantos/pagos
        parciales no se suman hasta entonces (ver Proyecto.ingreso_reconocido).

    Regla de reparto:
      - Ganancia neta total = Ingresos reconocidos - Gastos
      - Cada socio tiene derecho al 50% de la ganancia neta.
      - 'Aporte' de un socio = gastos que pagó de su bolsillo.
      - 'Cobrado' de un socio = ingresos reconocidos de los pedidos que registró.
      - 'En mano' = cobrado - aporte  (efectivo real que tiene ahora)
      - 'Ajuste'  = lo que debería tener (50% ganancia) - lo que tiene en mano.
                    Positivo = le deben plata / Negativo = debe plata.
    """
    usuarios = User.query.all()

    # Filtra proyectos/gastos por mes (proyectos por su fecha de creación) si aplica
    pq, gq = Proyecto.query, Gasto.query
    if anio and mes:
        pq = pq.filter(extract("year", Proyecto.creado) == anio,
                       extract("month", Proyecto.creado) == mes)
        gq = gq.filter(extract("year", Gasto.fecha) == anio,
                       extract("month", Gasto.fecha) == mes)
    proyectos, gastos = pq.all(), gq.all()

    # Liquidaciones (transferencias entre socios) del mismo periodo. NO son
    # ingresos ni gastos: solo reacomodan el efectivo en mano de cada socio.
    lq = Liquidacion.query
    if anio and mes:
        lq = lq.filter(Liquidacion.anio == anio, Liquidacion.mes == mes)
    liquidaciones = lq.all()

    # Solo cuentan los pedidos entregados o cancelados en su totalidad
    total_ingresos = sum(p.ingreso_reconocido for p in proyectos)
    total_gastos = sum(g.monto for g in gastos)
    ganancia_neta = total_ingresos - total_gastos

    n = len(usuarios) or 1
    parte_justa = ganancia_neta / n  # 50% si son 2 socios

    balance_socios = []
    for u in usuarios:
        cobrado = sum(p.ingreso_reconocido for p in proyectos if p.usuario_id == u.id)
        aporte = sum(g.monto for g in gastos if g.usuario_id == u.id)
        # Efecto de las liquidaciones ya registradas: recibió suma, pagó resta
        recibido = sum(l.monto for l in liquidaciones if l.receptor_id == u.id)
        pagado = sum(l.monto for l in liquidaciones if l.pagador_id == u.id)
        en_mano = cobrado - aporte + recibido - pagado
        ajuste = parte_justa - en_mano
        balance_socios.append({
            "usuario": u,
            "cobrado": cobrado,
            "aporte": aporte,
            "liquidado": recibido - pagado,
            "en_mano": en_mano,
            "parte_justa": parte_justa,
            "ajuste": ajuste,
        })

    # Sugerencia para 'quedar a mano': quien tiene de más le paga a quien tiene
    # de menos, por el monto exacto del ajuste. None si ya están parejos.
    liquidacion_sugerida = None
    if balance_socios:
        receptor = max(balance_socios, key=lambda s: s["ajuste"])   # ajuste > 0 → le deben
        pagador = min(balance_socios, key=lambda s: s["ajuste"])    # ajuste < 0 → debe
        monto = round(min(receptor["ajuste"], -pagador["ajuste"]), 2)
        if receptor["usuario"].id != pagador["usuario"].id and monto > 0.5:
            liquidacion_sugerida = {
                "pagador": pagador["usuario"],
                "receptor": receptor["usuario"],
                "monto": monto,
            }

    return {
        "total_ingresos": total_ingresos,
        "total_gastos": total_gastos,
        "ganancia_neta": ganancia_neta,
        "parte_justa": parte_justa,
        "socios": balance_socios,
        "liquidacion_sugerida": liquidacion_sugerida,
    }


def _texto_de_archivo_slicer(data, filename=""):
    """Extrae texto de un .gcode (texto plano) o .3mf (ZIP con configs/XML)."""
    if zipfile.is_zipfile(io.BytesIO(data)):
        partes = []
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in z.namelist():
                if name.lower().endswith((".config", ".xml", ".gcode", ".txt", ".json")):
                    try:
                        partes.append(z.read(name).decode("utf-8", "ignore"))
                    except Exception:
                        pass
        return "\n".join(partes)
    return data.decode("utf-8", "ignore")


def _fragmento_a_horas(frag):
    """Convierte '1d 2h 30m 15s' -> horas (float)."""
    d = re.search(r"(\d+)\s*d", frag)
    h = re.search(r"(\d+)\s*h", frag)
    mi = re.search(r"(\d+)\s*m", frag)
    s = re.search(r"(\d+)\s*s", frag)
    total = 0.0
    if d:  total += int(d.group(1)) * 24
    if h:  total += int(h.group(1))
    if mi: total += int(mi.group(1)) / 60
    if s:  total += int(s.group(1)) / 3600
    return round(total, 2) if total else None


def parsear_metadatos_slicer(data, filename=""):
    """
    Lee los metadatos de peso (g) y tiempo de impresión desde un archivo de
    slicer (PrusaSlicer/Orca/Bambu/SuperSlicer/Cura, .gcode o .3mf) con regex.
    Devuelve dict {peso_g, tiempo_h}. Valores None si no se encuentran.
    """
    texto = _texto_de_archivo_slicer(data, filename)

    # ---- Peso en gramos ----
    peso = None
    patrones_peso = [
        r"total\s+filament\s+(?:used|weight)\s*\[?g\]?\s*[:=]\s*([\d.]+)",  # total explícito
        r'used_g="([\d.]+)"',                         # .3mf slice_info (por filamento)
        r'key="weight"\s+value="([\d.]+)"',           # .3mf metadata
        r"filament\s+used\s*\[g\]\s*[:=]\s*([\d.]+)",  # PrusaSlicer/Orca por herramienta
        r"filament\s+weight[^\d]*([\d.]+)\s*g",       # genérico "filament weight: X g"
    ]
    for pat in patrones_peso:
        encontrados = re.findall(pat, texto, re.I)
        if encontrados:
            # Suma (varios filamentos) salvo que el patrón ya sea un total
            peso = round(sum(float(x) for x in encontrados), 2)
            break

    # ---- Tiempo en horas ----
    tiempo = None
    m = re.search(r";TIME:(\d+)", texto)                         # Cura (segundos)
    if not m:
        m = re.search(r'key="prediction"\s+value="(\d+)"', texto, re.I)  # .3mf (segundos)
    if m:
        tiempo = round(int(m.group(1)) / 3600, 2)
    else:
        etq = re.search(
            r"(?:estimated printing time[^\n=:]*|total estimated time|model printing time)"
            r"\s*[:=]\s*([0-9hdms \t]+)", texto, re.I)
        if etq:
            tiempo = _fragmento_a_horas(etq.group(1))

    return {"peso_g": peso, "tiempo_h": tiempo}


def obtener_proyectos_urgentes():
    """
    Proyectos NO entregados que vencen en <= 2 días o ya están retrasados,
    ordenados por urgencia (más retrasado / próximo primero).
    """
    candidatos = Proyecto.query.filter(Proyecto.estado != "Entregado").all()
    urgentes = [p for p in candidatos if p.es_urgente]
    urgentes.sort(key=lambda p: p.dias_restantes)
    return urgentes


# --------------------------------------------------------------------------
#  Rutas
# --------------------------------------------------------------------------
def registrar_rutas(app):

    # ---------- Contexto global (disponible en TODAS las plantillas) ----------
    @app.context_processor
    def inyectar_alertas_stock():
        """Badges de la nav: stock bajo (taller y tienda) y leads pendientes."""
        if not current_user.is_authenticated:
            return {"conteo_alertas": 0, "conteo_por_contestar": 0,
                    "conteo_tienda": 0}
        conteo = sum(1 for f in Filamento.query.all() if f.bajo_stock)
        # Leads: por contestar + contestados que ya piden seguimiento.
        leads = PosibleCliente.query.filter(
            PosibleCliente.estado.in_(["Por contestar", "Contestado"])).all()
        por_contestar = sum(1 for c in leads
                            if c.estado == "Por contestar" or c.necesita_seguimiento)
        # Tienda: colores por reponer + encargos sin atender.
        tienda = sum(1 for i in FilamentoTienda.query.all() if i.bajo_stock)
        tienda += EncargoFilamento.query.filter_by(estado="Pendiente").count()
        return {"conteo_alertas": conteo, "conteo_por_contestar": por_contestar,
                "conteo_tienda": tienda}

    # ---------- Autenticación ----------
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            username = request.form.get("username", "").strip().lower()
            password = request.form.get("password", "")
            user = User.query.filter_by(username=username).first()
            if user and user.password_hash and \
                    bcrypt.check_password_hash(user.password_hash, password):
                login_user(user)
                destino = request.args.get("next") or url_for("dashboard")
                return redirect(destino)
            flash("Usuario o contraseña incorrectos.", "error")
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        flash("Sesión cerrada correctamente.", "ok")
        return redirect(url_for("login"))

    def _parse_fecha(valor):
        if not valor:
            return date.today()
        return datetime.strptime(valor, "%Y-%m-%d").date()

    def _parse_fecha_opt(valor):
        """Fecha opcional: None si el campo viene vacío."""
        if not valor:
            return None
        return datetime.strptime(valor, "%Y-%m-%d").date()

    def _gcodes_dir():
        return os.path.join(app.root_path, "instance", "gcodes")

    def _guardar_gcode(archivo):
        """Guarda el archivo con nombre UUID (evita colisiones). Devuelve el nombre en disco o None."""
        if not archivo or not archivo.filename:
            return None
        base = secure_filename(archivo.filename)
        ext = os.path.splitext(base)[1].lower()
        if ext not in EXTENSIONES_GCODE:
            return None
        nombre_disco = f"{uuid.uuid4().hex}{ext}"
        archivo.save(os.path.join(_gcodes_dir(), nombre_disco))
        return nombre_disco

    def _guardar_bytes_gcode(data, ext):
        """Escribe bytes en disco con nombre UUID. Devuelve el nombre en disco."""
        nombre_disco = f"{uuid.uuid4().hex}{ext}"
        with open(os.path.join(_gcodes_dir(), nombre_disco), "wb") as fh:
            fh.write(data)
        return nombre_disco

    def _borrar_gcode(nombre):
        """Borra el archivo físico si existe (evita basura en disco)."""
        if not nombre:
            return
        ruta = os.path.join(_gcodes_dir(), nombre)
        try:
            if os.path.isfile(ruta):
                os.remove(ruta)
        except OSError:
            pass

    # ---- Imágenes de proyecto (JPG/PNG/WEBP) ----
    def _imagenes_dir():
        return os.path.join(app.root_path, "instance", "uploads", "imagenes")

    def _guardar_imagen(archivo):
        """
        Valida y guarda una foto de proyecto con nombre UUID (secure_filename +
        uuid evitan colisiones y rutas maliciosas). Devuelve el nombre en disco
        o None si no hay archivo o el formato no está permitido.
        """
        if not archivo or not archivo.filename:
            return None
        base = secure_filename(archivo.filename)
        ext = os.path.splitext(base)[1].lower()
        if ext not in EXTENSIONES_IMAGEN:
            return None
        nombre_disco = f"{uuid.uuid4().hex}{ext}"
        archivo.save(os.path.join(_imagenes_dir(), nombre_disco))
        return nombre_disco

    def _borrar_imagen(nombre):
        """Borra la foto física si existe (evita basura en disco)."""
        if not nombre:
            return
        ruta = os.path.join(_imagenes_dir(), nombre)
        try:
            if os.path.isfile(ruta):
                os.remove(ruta)
        except OSError:
            pass

    def _filtrar_mes(query, columna_fecha, per):
        return query.filter(extract("year", columna_fecha) == per["anio"],
                            extract("month", columna_fecha) == per["mes"])

    def _csv_response(nombre, cabecera, filas):
        buf = io.StringIO()
        buf.write("﻿")  # BOM: Excel abre los acentos correctamente
        w = csv.writer(buf)
        w.writerow(cabecera)
        w.writerows(filas)
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={nombre}"},
        )

    def _contexto_periodo():
        """Datos comunes del selector de mes para las plantillas."""
        anio, mes = parse_periodo(request.args.get("periodo"))
        pa, ma = mes_relativo(anio, mes, -1)
        ps, ms = mes_relativo(anio, mes, +1)
        return {
            "anio": anio, "mes": mes,
            "periodo": periodo_str(anio, mes),
            "periodo_label": etiqueta_periodo(anio, mes),
            "periodo_prev": periodo_str(pa, ma),
            "periodo_next": periodo_str(ps, ms),
        }

    def _es_movil():
        """Heurística simple de dispositivo móvil a partir del User-Agent."""
        ua = (request.user_agent.string or "").lower()
        claves = ("android", "iphone", "ipod", "ipad", "mobile",
                  "windows phone", "blackberry", "opera mini")
        return any(k in ua for k in claves)

    # ---------- Dashboard ----------
    @app.route("/")
    @login_required
    def dashboard():
        # Desde el celular (o la PWA instalada) mostramos la App de Taller móvil.
        # ?desktop=1 fuerza el panel completo aunque sea un teléfono.
        if _es_movil() and not request.args.get("desktop"):
            return redirect(url_for("app_mobile"))
        per = _contexto_periodo()
        bal = calcular_balance(per["anio"], per["mes"])
        proyectos = Proyecto.query.order_by(Proyecto.creado.desc()).limit(6).all()
        conteo_estados = {
            e: Proyecto.query.filter_by(estado=e).count()
            for e in Proyecto.ESTADOS
        }
        # Alertas de stock crítico de filamento
        alertas_stock = [f for f in Filamento.query.all() if f.bajo_stock]
        # Agente Asistente: pedidos urgentes + tendencias
        urgentes = obtener_proyectos_urgentes()
        return render_template("dashboard.html", bal=bal, per=per,
                               proyectos=proyectos, conteo_estados=conteo_estados,
                               alertas_stock=alertas_stock,
                               urgentes=urgentes, tendencias=TENDENCIAS_VIRALES)

    # ---------- App de Taller (vista móvil de producción) ----------
    @app.route("/mobile")
    @login_required
    def app_mobile():
        """Vista simplificada para el teléfono: pedidos en vivo + stock rápido."""
        activos = Proyecto.query.filter(Proyecto.estado != "Entregado").all()
        # Los que tienen fecha van primero (más próximos arriba); el resto por reciente.
        activos.sort(key=lambda p: (p.fecha_entrega is None,
                                    p.fecha_entrega or date.max,
                                    -(p.id or 0)))
        filamentos = Filamento.query.order_by(Filamento.tipo, Filamento.color).all()
        return render_template("mobile.html", proyectos=activos,
                               filamentos=filamentos, estados=Proyecto.ESTADOS)

    @app.route("/mobile/proyecto/<int:pid>/estado", methods=["POST"])
    @login_required
    def mobile_cambiar_estado(pid):
        """Cambio rápido de estado por AJAX (sin recargar). Devuelve JSON."""
        p = Proyecto.query.get_or_404(pid)
        nuevo = request.form.get("estado") or (request.get_json(silent=True) or {}).get("estado")
        if nuevo not in Proyecto.ESTADOS:
            return jsonify({"ok": False, "error": "Estado inválido."}), 400
        if nuevo == "Imprimiendo" and p.estado != "Imprimiendo":
            p.inicio_impresion = datetime.utcnow()
        p.estado = nuevo
        db.session.commit()
        return jsonify({
            "ok": True,
            "id": p.id,
            "estado": p.estado,
            "activo": p.estado != "Entregado",   # si sale del tablero de producción
            "mensaje": f"«{p.nombre}» → {p.estado}",
        })

    # ---------- PWA (manifest + service worker) ----------
    @app.route("/sw.js")
    def service_worker():
        """Sirve el Service Worker desde la raíz para que su alcance cubra /mobile."""
        return app.send_static_file("sw.js"), 200, {
            "Content-Type": "application/javascript",
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache",
        }

    @app.route("/manifest.json")
    def manifest():
        return app.send_static_file("manifest.json"), 200, {
            "Content-Type": "application/manifest+json",
        }

    # ==========================================================================
    #  API REST v1 (consumida por la PWA móvil desplegada en Vercel)
    #  Sin sesión de Flask-Login (cross-origin); opcionalmente protegida con una
    #  API key por header X-API-Key si se define MOBILE_API_KEY en el entorno.
    # ==========================================================================
    def _base_backend():
        """URL absoluta del backend (para construir URLs de imágenes)."""
        base = os.environ.get("BACKEND_BASE_URL") or request.url_root
        return base.rstrip("/")

    def _url_imagen(filename):
        if not filename:
            return None
        return f"{_base_backend()}/api/v1/imagenes/{filename}"

    def _api_key_ok():
        """True si no hay API key configurada o si el header coincide."""
        requerida = os.environ.get("MOBILE_API_KEY")
        if not requerida:
            return True
        enviada = request.headers.get("X-API-Key") or request.args.get("api_key")
        return enviada == requerida

    def _socio_a_json(u):
        if not u:
            return None
        return {"id": u.id, "nombre": u.nombre, "color": u.color}

    def _proyecto_a_json(p):
        fin = p.fin_impresion_estimado
        return {
            "id": p.id,
            "nombre": p.nombre,
            "cliente": p.cliente or "",
            "telefono": p.telefono or "",
            "estado": p.estado,
            "foto_url": _url_imagen(p.imagen_filename),
            "fotos": [_url_imagen(f.filename) for f in p.fotos],
            "fecha_entrega_iso": p.fecha_entrega.isoformat() if p.fecha_entrega else None,
            "orden": p.orden or 0,
            "public_token": p.public_token,
            # Cobranza / deuda interna
            "precio_total": p.precio_total or 0.0,
            "adelanto": p.adelanto or 0.0,
            "saldo_pendiente": p.saldo_pendiente,
            "pagado_completo": p.pagado_completo,
            "ganancia": p.ganancia,
            "costo_filamento": p.costo_filamento,
            "cobrador": _socio_a_json(p.cobrador),
            "saldado": bool(p.saldado),
            "parte_socio": p.parte_socio,
            "deuda_pendiente": p.deuda_interna_pendiente,
            "cerrado": p.cerrado,
            # Monitor de impresión
            "tiempo_estimado_h": p.tiempo_estimado_h or 0.0,
            "horas_impresion": p.horas_impresion or 0.0,
            "horas_totales_impresion": p.horas_totales_impresion,
            "inicio_impresion_iso": p.inicio_impresion.isoformat() if p.inicio_impresion else None,
            "fin_impresion_iso": fin.isoformat() if fin else None,
            "imprimiendo": p.estado == "Imprimiendo",
        }

    def _filamento_a_json(f):
        return {
            "id": f.id,
            "marca": "",                       # el modelo no guarda marca (reservado)
            "material": f.tipo,
            "color": f.color,
            "color_hex": nombre_a_hex(f.color),
            "stock_gramos": round(max(f.gramos_restantes, 0.0), 1),
            "peso_rollo_g": f.peso_rollo_g,
            "rollos_restantes": round((f.gramos_restantes / f.peso_rollo_g), 2) if f.peso_rollo_g else 0,
            "alerta_bajo_stock": bool(f.bajo_stock),
        }

    @app.route("/api/v1/imagenes/<path:filename>")
    def api_imagen(filename):
        """Sirve las fotos de proyecto de forma pública (para la PWA en Vercel)."""
        return send_from_directory(_imagenes_dir(), filename)

    @app.route("/api/v1/pedidos-activos")
    def api_pedidos_activos():
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        from datetime import timedelta
        limite = datetime.utcnow() - timedelta(days=7)
        todos = Proyecto.query.filter(Proyecto.estado != "Cancelado").all()

        def visible(p):
            # En producción siempre; entregados solo los de los últimos 7 días.
            if p.estado != "Entregado":
                return True
            return (p.fecha_entregado or p.creado or datetime.min) >= limite

        lista = [p for p in todos if visible(p)]
        # Pendientes arriba (por fecha de entrega / cola), entregados al fondo.
        lista.sort(key=lambda p: (
            p.estado == "Entregado",                       # entregados últimos
            p.fecha_entrega is None,                        # sin fecha, después
            p.fecha_entrega or date.max,                    # entrega más próxima arriba
            p.orden or 0,
            -(p.id or 0),
        ))
        pendientes = sum(1 for p in lista if p.estado != "Entregado")
        return jsonify({
            "ok": True,
            "count": pendientes,
            "total": len(lista),
            "pedidos": [_proyecto_a_json(p) for p in lista],
        })

    @app.route("/api/v1/pedidos/<int:pid>/estado", methods=["PATCH", "POST"])
    def api_actualizar_estado(pid):
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        datos = request.get_json(silent=True) or request.form
        estado = normalizar_estado(datos.get("estado"))
        if not estado:
            return jsonify({"ok": False,
                            "error": "Estado inválido.",
                            "estados_validos": Proyecto.ESTADOS}), 400
        p = Proyecto.query.get_or_404(pid)
        # Al arrancar la impresión guardamos la hora de inicio para el monitor/timer.
        if estado == "Imprimiendo" and p.estado != "Imprimiendo":
            p.inicio_impresion = datetime.utcnow()
        # Marca la fecha de entrega real la primera vez que pasa a "Entregado".
        if estado == "Entregado" and p.estado != "Entregado":
            p.fecha_entregado = datetime.utcnow()
        p.estado = estado
        db.session.commit()
        return jsonify({"ok": True, "pedido": _proyecto_a_json(p),
                        "activo": not p.cerrado})

    @app.route("/api/v1/filamentos-stock")
    def api_filamentos_stock():
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        filamentos = Filamento.query.order_by(Filamento.tipo, Filamento.color).all()
        return jsonify({
            "ok": True,
            "count": len(filamentos),
            "filamentos": [_filamento_a_json(f) for f in filamentos],
        })

    @app.route("/api/v1/pedidos/<int:pid>/foto", methods=["POST"])
    def api_subir_foto_pedido(pid):
        """
        Sube la foto del resultado final de un pedido desde la cámara del celular.
        La PWA envía un multipart/form-data con el campo 'foto'. Reemplaza la
        anterior si existía y devuelve la URL pública de la nueva imagen.
        """
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        p = Proyecto.query.get_or_404(pid)
        archivo = request.files.get("foto") or request.files.get("imagen")
        if not archivo or not archivo.filename:
            return jsonify({"ok": False, "error": "No se recibió ninguna foto."}), 400
        guardada = _guardar_imagen(archivo)
        if not guardada:
            return jsonify({"ok": False,
                            "error": "Formato no soportado (usa JPG, PNG o WEBP)."}), 400
        _borrar_imagen(p.imagen_filename)   # elimina la foto vieja para no dejar basura
        p.imagen_filename = guardada
        db.session.commit()
        return jsonify({"ok": True, "pedido": _proyecto_a_json(p),
                        "foto_url": _url_imagen(p.imagen_filename)})

    # ======================================================================
    #  API REST v1 — extensiones (v2.2): cobro, deuda, calendario, clientes,
    #  fotos, cola, impresoras, dashboard y cotizador.
    # ======================================================================
    @app.route("/api/v1/usuarios")
    def api_usuarios():
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        socios = User.query.order_by(User.id).all()
        return jsonify({"ok": True, "usuarios": [_socio_a_json(u) for u in socios]})

    @app.route("/api/v1/pedidos/<int:pid>/cobrador", methods=["PATCH", "POST"])
    def api_set_cobrador(pid):
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        p = Proyecto.query.get_or_404(pid)
        datos = request.get_json(silent=True) or request.form
        cid = datos.get("cobrador_id")
        p.cobrador_id = int(cid) if cid not in (None, "", "0") else None
        if not p.cobrador_id:            # sin cobrador no hay deuda que saldar
            p.saldado = False
            p.fecha_saldado = None
        db.session.commit()
        return jsonify({"ok": True, "pedido": _proyecto_a_json(p)})

    @app.route("/api/v1/pedidos/<int:pid>/saldar", methods=["PATCH", "POST"])
    def api_saldar(pid):
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        p = Proyecto.query.get_or_404(pid)
        datos = request.get_json(silent=True) or request.form
        valor = datos.get("saldado", True)
        p.saldado = str(valor).lower() not in ("false", "0", "no", "")
        p.fecha_saldado = datetime.utcnow() if p.saldado else None
        db.session.commit()
        return jsonify({"ok": True, "pedido": _proyecto_a_json(p)})

    @app.route("/api/v1/pedidos/<int:pid>", methods=["PATCH", "POST"])
    def api_editar_pedido(pid):
        """Edición ligera de datos del pedido desde el celular."""
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        p = Proyecto.query.get_or_404(pid)
        d = request.get_json(silent=True) or request.form
        if "nombre" in d and d.get("nombre"):
            p.nombre = str(d.get("nombre")).strip()
        if "cliente" in d:
            p.cliente = (d.get("cliente") or "").strip()
        if "telefono" in d:
            p.telefono = (d.get("telefono") or "").strip()
        if "precio_total" in d:
            p.precio_total = float(d.get("precio_total") or 0)
        if "adelanto" in d:
            p.adelanto = float(d.get("adelanto") or 0)
        if "peso_g" in d:
            p.peso_g = float(d.get("peso_g") or 0)
        if "tiempo_estimado_h" in d:
            p.tiempo_estimado_h = float(d.get("tiempo_estimado_h") or 0)
        if "filamento_id" in d:
            fid = d.get("filamento_id")
            p.filamento_id = int(fid) if fid not in (None, "", "0") else None
        if "fecha_entrega" in d:
            p.fecha_entrega = _parse_fecha_opt(d.get("fecha_entrega"))
        db.session.commit()
        return jsonify({"ok": True, "pedido": _proyecto_a_json(p)})

    @app.route("/api/v1/pedidos", methods=["POST"])
    def api_crear_pedido():
        """Crea un pedido desde la PWA (el cobrador se ELIGE, no se asume)."""
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        d = request.get_json(silent=True) or request.form
        nombre = (d.get("nombre") or "").strip()
        if not nombre:
            return jsonify({"ok": False, "error": "El nombre es obligatorio."}), 400
        cid = d.get("cobrador_id")
        fid = d.get("filamento_id")
        p = Proyecto(
            nombre=nombre,
            cliente=(d.get("cliente") or "").strip(),
            telefono=(d.get("telefono") or "").strip(),
            estado=normalizar_estado(d.get("estado")) or "En espera",
            peso_g=float(d.get("peso_g") or 0),
            tiempo_estimado_h=float(d.get("tiempo_estimado_h") or 0),
            filamento_id=int(fid) if fid not in (None, "", "0") else None,
            fecha_entrega=_parse_fecha_opt(d.get("fecha_entrega")),
            precio_total=float(d.get("precio_total") or 0),
            adelanto=float(d.get("adelanto") or 0),
            cobrador_id=int(cid) if cid not in (None, "", "0") else None,
        )
        db.session.add(p)
        db.session.commit()
        return jsonify({"ok": True, "pedido": _proyecto_a_json(p)})

    @app.route("/api/v1/pedidos-calendario")
    def api_pedidos_calendario():
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        hoy = date.today()
        try:
            anio = int(request.args.get("anio") or hoy.year)
            mes = int(request.args.get("mes") or hoy.month)
        except ValueError:
            anio, mes = hoy.year, hoy.month
        q = Proyecto.query.filter(
            Proyecto.fecha_entrega.isnot(None),
            Proyecto.estado != "Cancelado",
            extract("year", Proyecto.fecha_entrega) == anio,
            extract("month", Proyecto.fecha_entrega) == mes,
        ).all()
        dias = {}
        for p in q:
            k = p.fecha_entrega.isoformat()
            dias.setdefault(k, []).append({
                "id": p.id, "nombre": p.nombre, "cliente": p.cliente or "",
                "estado": p.estado, "urgente": p.es_urgente,
                "entregado": p.estado == "Entregado",
            })
        return jsonify({"ok": True, "anio": anio, "mes": mes, "dias": dias})

    @app.route("/api/v1/resumen-deuda")
    def api_resumen_deuda():
        """Deuda interna entre socios por pedidos cobrados y aún no saldados."""
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        pendientes = Proyecto.query.filter(
            Proyecto.cobrador_id.isnot(None),
            Proyecto.saldado == False,                      # noqa: E712
            Proyecto.precio_total > 0,
            Proyecto.estado != "Cancelado",
        ).all()
        # Cada cobrador le debe al OTRO socio la parte del otro (50%).
        por_cobrador = {}
        for p in pendientes:
            e = por_cobrador.setdefault(p.cobrador_id, {"monto": 0.0, "count": 0,
                                                         "nombre": p.cobrador.nombre})
            e["monto"] += p.parte_socio
            e["count"] += 1
        detalle = [{"cobrador_id": k, "cobrador": v["nombre"],
                    "debe": round(v["monto"], 2), "pedidos": v["count"]}
                   for k, v in por_cobrador.items()]
        return jsonify({"ok": True, "detalle": detalle,
                        "total_pendiente": round(sum(d["debe"] for d in detalle), 2)})

    @app.route("/api/v1/clientes")
    def api_clientes():
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        clientes = {}
        for p in Proyecto.query.filter(Proyecto.cliente.isnot(None),
                                       Proyecto.cliente != "").all():
            c = clientes.setdefault(p.cliente.strip(), {
                "cliente": p.cliente.strip(), "telefono": "", "pedidos": 0,
                "total_gastado": 0.0, "activos": 0})
            c["pedidos"] += 1
            c["total_gastado"] += p.ingreso_reconocido
            if not p.cerrado:
                c["activos"] += 1
            if p.telefono and not c["telefono"]:
                c["telefono"] = p.telefono
        lista = sorted(clientes.values(), key=lambda c: -c["total_gastado"])
        for c in lista:
            c["total_gastado"] = round(c["total_gastado"], 2)
        return jsonify({"ok": True, "clientes": lista})

    @app.route("/api/v1/pedidos/<int:pid>/fotos", methods=["POST"])
    def api_agregar_foto(pid):
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        p = Proyecto.query.get_or_404(pid)
        archivo = request.files.get("foto") or request.files.get("imagen")
        if not archivo or not archivo.filename:
            return jsonify({"ok": False, "error": "No se recibió ninguna foto."}), 400
        guardada = _guardar_imagen(archivo)
        if not guardada:
            return jsonify({"ok": False, "error": "Formato no soportado."}), 400
        if not p.imagen_filename:        # la primera foto también es la principal
            p.imagen_filename = guardada
        db.session.add(FotoPedido(proyecto_id=p.id, filename=guardada,
                                  nota=(request.form.get("nota") or "").strip()))
        db.session.commit()
        return jsonify({"ok": True, "pedido": _proyecto_a_json(p),
                        "foto_url": _url_imagen(guardada)})

    @app.route("/api/v1/fotos/<int:fid>", methods=["DELETE", "POST"])
    def api_borrar_foto(fid):
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        f = FotoPedido.query.get_or_404(fid)
        _borrar_imagen(f.filename)
        db.session.delete(f)
        db.session.commit()
        return jsonify({"ok": True})

    @app.route("/api/v1/pedidos/reordenar", methods=["POST", "PATCH"])
    def api_reordenar():
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        d = request.get_json(silent=True) or {}
        ids = d.get("orden") or []
        for i, pid in enumerate(ids):
            p = Proyecto.query.get(int(pid))
            if p:
                p.orden = i
        db.session.commit()
        return jsonify({"ok": True})

    @app.route("/api/v1/gastos", methods=["POST"])
    def api_crear_gasto():
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        d = request.get_json(silent=True) or request.form
        monto = float(d.get("monto") or 0)
        if monto <= 0:
            return jsonify({"ok": False, "error": "El monto debe ser mayor a 0."}), 400
        uid = d.get("usuario_id")
        g = Gasto(
            categoria=d.get("categoria") or "Otro",
            descripcion=(d.get("descripcion") or "").strip(),
            monto=monto,
            usuario_id=int(uid) if uid not in (None, "", "0") else None,
        )
        db.session.add(g)
        db.session.commit()
        return jsonify({"ok": True, "gasto": {"id": g.id, "monto": g.monto,
                        "categoria": g.categoria, "descripcion": g.descripcion}})

    @app.route("/api/v1/cotizar")
    def api_cotizar():
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        peso = float(request.args.get("peso") or 0)
        horas = float(request.args.get("horas") or 0)
        fid = request.args.get("filamento_id")
        costo = 0.0
        if fid:
            fil = Filamento.query.get(int(fid))
            if fil:
                costo = round(peso * fil.precio_por_gramo, 2)
        return jsonify({"ok": True, "costo_filamento": costo,
                        "precio_sugerido": cotizar_precio(costo, horas),
                        "tarifa_hora": COTIZADOR["tarifa_hora"],
                        "margen": COTIZADOR["margen"]})

    @app.route("/api/v1/dashboard")
    def api_dashboard():
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        hoy = date.today()
        proyectos = Proyecto.query.all()
        activos = [p for p in proyectos if not p.cerrado]
        entregados_mes = [p for p in proyectos if p.estado == "Entregado"
                          and p.fecha_entregado and p.fecha_entregado.year == hoy.year
                          and p.fecha_entregado.month == hoy.month]
        ingreso_mes = sum(p.ingreso_reconocido for p in entregados_mes)
        por_estado = {}
        for p in activos:
            por_estado[p.estado] = por_estado.get(p.estado, 0) + 1
        return jsonify({"ok": True,
                        "activos": len(activos),
                        "en_espera": sum(1 for p in activos if p.estado == "En espera"),
                        "urgentes": sum(1 for p in activos if p.es_urgente),
                        "entregados_mes": len(entregados_mes),
                        "ingreso_mes": round(ingreso_mes, 2),
                        "por_estado": por_estado})

    def _impresora_a_json(m):
        return {"id": m.id, "nombre": m.nombre,
                "horas_totales": round(m.horas_totales or 0, 1),
                "horas_desde_mant": m.horas_desde_mant,
                "intervalo_mant_h": m.intervalo_mant_h or 0,
                "necesita_mant": m.necesita_mant, "nota": m.nota or ""}

    @app.route("/api/v1/impresoras")
    def api_impresoras():
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        ms = Impresora.query.filter_by(activa=True).order_by(Impresora.nombre).all()
        return jsonify({"ok": True, "impresoras": [_impresora_a_json(m) for m in ms]})

    @app.route("/api/v1/impresoras", methods=["POST"])
    def api_crear_impresora():
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        d = request.get_json(silent=True) or request.form
        nombre = (d.get("nombre") or "").strip()
        if not nombre:
            return jsonify({"ok": False, "error": "El nombre es obligatorio."}), 400
        m = Impresora(nombre=nombre,
                      horas_totales=float(d.get("horas_totales") or 0),
                      intervalo_mant_h=float(d.get("intervalo_mant_h") or 250))
        db.session.add(m)
        db.session.commit()
        return jsonify({"ok": True, "impresora": _impresora_a_json(m)})

    @app.route("/api/v1/impresoras/<int:mid>/horas", methods=["POST", "PATCH"])
    def api_sumar_horas(mid):
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        m = Impresora.query.get_or_404(mid)
        d = request.get_json(silent=True) or request.form
        m.horas_totales = (m.horas_totales or 0) + float(d.get("horas") or 0)
        db.session.commit()
        return jsonify({"ok": True, "impresora": _impresora_a_json(m)})

    @app.route("/api/v1/impresoras/<int:mid>/mantenimiento", methods=["POST"])
    def api_mantenimiento(mid):
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        m = Impresora.query.get_or_404(mid)
        m.horas_ultimo_mant = m.horas_totales or 0
        db.session.commit()
        return jsonify({"ok": True, "impresora": _impresora_a_json(m)})

    # ======================================================================
    #  Ferias y Eventos (POS móvil) — API REST v1
    # ======================================================================
    def _feria_inv_a_json(i):
        return {
            "id": i.id,
            "producto_id": i.producto_id,
            "producto_nombre": i.producto_nombre,
            "cantidad_llevada": i.cantidad_llevada or 0,
            "cantidad_vendida": i.cantidad_vendida or 0,
            "cantidad_merma": i.cantidad_merma or 0,
            "cantidad_restante": i.cantidad_restante,
            "precio_unitario": i.precio_unitario or 0.0,
            "recaudado": i.recaudado,
            "valor_proyectado": i.valor_proyectado,
            "valor_restante": i.valor_restante,
        }

    def _feria_a_json(f, detalle=False):
        base = {
            "id": f.id,
            "nombre": f.nombre,
            "fecha_iso": f.fecha.isoformat() if f.fecha else None,
            "costo_stand": f.costo_stand or 0.0,
            "costo_material": f.costo_material or 0.0,
            "estado": f.estado,
            "total_recaudado": round(f.total_recaudado or 0.0, 2),
            "total_proyectado": f.total_proyectado,
            "valor_restante_mesa": f.valor_restante_mesa,
            "ganancia_neta": f.ganancia_neta,
            "unidades_vendidas": f.unidades_vendidas,
            "unidades_llevadas": f.unidades_llevadas,
            "unidades_merma": f.unidades_merma,
        }
        if detalle:
            base["inventario"] = [_feria_inv_a_json(i) for i in f.inventario]
            base["ventas"] = [
                {
                    "id": v.id, "producto_nombre": v.producto_nombre,
                    "cantidad": v.cantidad, "precio_total": v.precio_total,
                    "tipo": v.tipo or "venta", "nota": v.nota or "",
                    "fecha_hora_iso": v.fecha_hora.isoformat() if v.fecha_hora else None,
                }
                for v in f.ventas
            ]
        return base

    @app.route("/api/v1/ferias", methods=["GET", "POST"])
    def api_ferias():
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401

        if request.method == "POST":
            datos = request.get_json(silent=True) or request.form
            nombre = (datos.get("nombre") or "").strip()
            if not nombre:
                return jsonify({"ok": False, "error": "El nombre es obligatorio."}), 400
            try:
                costo_stand = float(datos.get("costo_stand") or 0)
            except (ValueError, TypeError):
                costo_stand = 0.0
            try:
                costo_material = float(datos.get("costo_material") or 0)
            except (ValueError, TypeError):
                costo_material = 0.0
            fecha = _parse_fecha_opt(datos.get("fecha")) or date.today()
            feria = Feria(nombre=nombre, costo_stand=costo_stand,
                          costo_material=costo_material, fecha=fecha,
                          estado="Activa", total_recaudado=0.0)
            db.session.add(feria)
            db.session.commit()
            return jsonify({"ok": True, "feria": _feria_a_json(feria, detalle=True)}), 201

        # GET: listar (activas primero, luego por fecha desc)
        ferias = Feria.query.order_by(Feria.creado.desc()).all()
        ferias.sort(key=lambda f: (f.estado != "Activa",))
        return jsonify({"ok": True, "count": len(ferias),
                        "ferias": [_feria_a_json(f) for f in ferias]})

    @app.route("/api/v1/ferias/<int:fid>", methods=["GET"])
    def api_feria_detalle(fid):
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        f = Feria.query.get_or_404(fid)
        return jsonify({"ok": True, "feria": _feria_a_json(f, detalle=True)})

    @app.route("/api/v1/ferias/<int:fid>/inventario", methods=["GET", "POST"])
    def api_feria_inventario(fid):
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        f = Feria.query.get_or_404(fid)

        if request.method == "POST":
            if f.estado != "Activa":
                return jsonify({"ok": False,
                                "error": "La feria está finalizada; no se puede cargar stock."}), 400
            datos = request.get_json(silent=True) or request.form
            nombre = (datos.get("producto_nombre") or datos.get("nombre") or "").strip()
            if not nombre:
                return jsonify({"ok": False, "error": "El nombre del producto es obligatorio."}), 400
            try:
                cantidad = int(float(datos.get("cantidad_llevada") or datos.get("cantidad") or 0))
                precio = float(datos.get("precio_unitario") or datos.get("precio") or 0)
            except (ValueError, TypeError):
                return jsonify({"ok": False, "error": "Cantidad o precio inválidos."}), 400
            producto_id = datos.get("producto_id")
            item = FeriaInventario(
                feria_id=f.id,
                producto_id=int(producto_id) if producto_id else None,
                producto_nombre=nombre,
                cantidad_llevada=max(cantidad, 0),
                cantidad_vendida=0,
                precio_unitario=max(precio, 0.0),
            )
            db.session.add(item)
            db.session.commit()
            return jsonify({"ok": True, "item": _feria_inv_a_json(item)}), 201

        return jsonify({"ok": True,
                        "inventario": [_feria_inv_a_json(i) for i in f.inventario]})

    @app.route("/api/v1/ferias/<int:fid>/inventario/<int:item_id>",
               methods=["PUT", "PATCH", "DELETE"])
    def api_feria_inventario_item(fid, item_id):
        """
        Edita (PUT/PATCH) o elimina (DELETE) un producto del inventario de la feria.
        Al editar se pueden ajustar 'precio_unitario' y 'cantidad_llevada'; la
        cantidad no puede quedar por debajo de lo ya vendido + mermado.
        """
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        f = Feria.query.get_or_404(fid)
        item = FeriaInventario.query.filter_by(id=item_id, feria_id=f.id).first()
        if item is None:
            return jsonify({"ok": False, "error": "Producto no encontrado en la feria."}), 404
        if f.estado != "Activa":
            return jsonify({"ok": False,
                            "error": "La feria está finalizada; no se puede modificar el stock."}), 400

        if request.method == "DELETE":
            db.session.delete(item)
            db.session.commit()
            return jsonify({"ok": True, "eliminado": item_id})

        # PUT/PATCH — edición de precio y/o cantidad
        datos = request.get_json(silent=True) or request.form
        comprometido = (item.cantidad_vendida or 0) + (item.cantidad_merma or 0)

        if "precio_unitario" in datos or "precio" in datos:
            try:
                item.precio_unitario = max(float(datos.get("precio_unitario")
                                                 if "precio_unitario" in datos
                                                 else datos.get("precio")), 0.0)
            except (ValueError, TypeError):
                return jsonify({"ok": False, "error": "Precio inválido."}), 400

        if "cantidad_llevada" in datos or "cantidad" in datos:
            try:
                nueva = int(float(datos.get("cantidad_llevada")
                                  if "cantidad_llevada" in datos
                                  else datos.get("cantidad")))
            except (ValueError, TypeError):
                return jsonify({"ok": False, "error": "Cantidad inválida."}), 400
            if nueva < comprometido:
                return jsonify({"ok": False,
                                "error": f"La cantidad no puede ser menor a lo ya movido ({comprometido})."}), 409
            item.cantidad_llevada = nueva

        if "producto_nombre" in datos or "nombre" in datos:
            nombre = (datos.get("producto_nombre") or datos.get("nombre") or "").strip()
            if nombre:
                item.producto_nombre = nombre

        db.session.commit()
        return jsonify({"ok": True, "item": _feria_inv_a_json(item),
                        "feria": _feria_a_json(f)})

    @app.route("/api/v1/ferias/<int:fid>/venta-rapida", methods=["POST"])
    def api_feria_venta_rapida(fid):
        """
        Venta instantánea en 1 toque: +1 a la cantidad vendida del producto,
        calcula el precio_total, registra la FeriaVenta y actualiza el total
        recaudado de la feria. Devuelve el estado actualizado para refrescar la caja.
        """
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        f = Feria.query.get_or_404(fid)
        if f.estado != "Activa":
            return jsonify({"ok": False, "error": "La feria ya está finalizada."}), 400

        datos = request.get_json(silent=True) or request.form
        inv_id = datos.get("inventario_id") or datos.get("item_id")
        item = None
        if inv_id:
            item = FeriaInventario.query.filter_by(id=int(inv_id), feria_id=f.id).first()
        if item is None:
            return jsonify({"ok": False, "error": "Producto no encontrado en la feria."}), 404

        try:
            cantidad = int(float(datos.get("cantidad") or 1))
        except (ValueError, TypeError):
            cantidad = 1
        cantidad = max(cantidad, 1)

        if item.cantidad_restante < cantidad:
            return jsonify({"ok": False,
                            "error": "Sin stock suficiente de ese producto.",
                            "item": _feria_inv_a_json(item)}), 409

        nota = (datos.get("nota") or "").strip()[:200]
        precio_total = round(cantidad * (item.precio_unitario or 0.0), 2)
        item.cantidad_vendida = (item.cantidad_vendida or 0) + cantidad
        f.total_recaudado = round((f.total_recaudado or 0.0) + precio_total, 2)
        venta = FeriaVenta(feria_id=f.id, inventario_id=item.id,
                           producto_nombre=item.producto_nombre,
                           cantidad=cantidad, precio_total=precio_total,
                           tipo="venta", nota=nota or None,
                           fecha_hora=datetime.utcnow())
        db.session.add(venta)
        db.session.commit()
        return jsonify({
            "ok": True,
            "venta": {"id": venta.id, "producto_nombre": venta.producto_nombre,
                      "cantidad": venta.cantidad, "precio_total": venta.precio_total,
                      "nota": venta.nota or ""},
            "item": _feria_inv_a_json(item),
            "total_recaudado": f.total_recaudado,
            "total_proyectado": f.total_proyectado,
            "valor_restante_mesa": f.valor_restante_mesa,
            "ganancia_neta": f.ganancia_neta,
            "unidades_vendidas": f.unidades_vendidas,
        })

    @app.route("/api/v1/ferias/<int:fid>/venta-combo", methods=["POST"])
    def api_feria_venta_combo(fid):
        """
        Venta tipo combo / descuento rápido (ej. "3 Llaveros por 20 Bs" o
        "Combo PopMe + Llavero"). Recibe una lista de ítems con su cantidad y un
        precio total pactado; descuenta las unidades de cada producto y cobra el
        precio del combo a la caja (que puede diferir de la suma unitaria).
        """
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        f = Feria.query.get_or_404(fid)
        if f.estado != "Activa":
            return jsonify({"ok": False, "error": "La feria ya está finalizada."}), 400

        datos = request.get_json(silent=True) or request.form
        lineas = datos.get("items") or []
        if isinstance(lineas, str):
            lineas = []
        if not lineas:
            return jsonify({"ok": False, "error": "El combo necesita al menos un producto."}), 400

        try:
            precio_total = round(float(datos.get("precio_total") or datos.get("precio") or 0), 2)
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "Precio del combo inválido."}), 400
        if precio_total < 0:
            precio_total = 0.0

        # Resuelve y valida stock de cada línea antes de tocar nada.
        resueltas = []
        for ln in lineas:
            inv_id = (ln or {}).get("inventario_id") or (ln or {}).get("item_id")
            try:
                cant = max(int(float((ln or {}).get("cantidad") or 1)), 1)
            except (ValueError, TypeError):
                cant = 1
            it = FeriaInventario.query.filter_by(id=int(inv_id), feria_id=f.id).first() if inv_id else None
            if it is None:
                return jsonify({"ok": False, "error": "Un producto del combo no existe en la feria."}), 404
            if it.cantidad_restante < cant:
                return jsonify({"ok": False,
                                "error": f"Sin stock suficiente de «{it.producto_nombre}».",
                                "item": _feria_inv_a_json(it)}), 409
            resueltas.append((it, cant))

        # Aplica el descuento de stock y arma un nombre legible del combo.
        total_unid = 0
        partes = []
        for it, cant in resueltas:
            it.cantidad_vendida = (it.cantidad_vendida or 0) + cant
            total_unid += cant
            partes.append(f"{cant}× {it.producto_nombre}")

        descripcion = (datos.get("descripcion") or datos.get("nombre") or "").strip()
        if not descripcion:
            descripcion = "Combo: " + " + ".join(partes)
        nota = (datos.get("nota") or "").strip()[:200]

        f.total_recaudado = round((f.total_recaudado or 0.0) + precio_total, 2)
        venta = FeriaVenta(feria_id=f.id,
                           inventario_id=resueltas[0][0].id,
                           producto_nombre=descripcion[:120],
                           cantidad=total_unid, precio_total=precio_total,
                           tipo="combo", nota=nota or None,
                           fecha_hora=datetime.utcnow())
        db.session.add(venta)
        db.session.commit()
        return jsonify({
            "ok": True,
            "venta": {"id": venta.id, "producto_nombre": venta.producto_nombre,
                      "cantidad": venta.cantidad, "precio_total": venta.precio_total,
                      "tipo": "combo", "nota": venta.nota or ""},
            "items": [_feria_inv_a_json(it) for it, _ in resueltas],
            "total_recaudado": f.total_recaudado,
            "total_proyectado": f.total_proyectado,
            "valor_restante_mesa": f.valor_restante_mesa,
            "ganancia_neta": f.ganancia_neta,
            "unidades_vendidas": f.unidades_vendidas,
        })

    @app.route("/api/v1/ferias/<int:fid>/merma", methods=["POST"])
    def api_feria_merma(fid):
        """
        Registra mermas / muestras gratis / canjes: descuenta unidades del stock
        restante SIN sumar dinero a la caja. Útil para piezas dañadas o regaladas.
        """
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        f = Feria.query.get_or_404(fid)
        if f.estado != "Activa":
            return jsonify({"ok": False, "error": "La feria ya está finalizada."}), 400

        datos = request.get_json(silent=True) or request.form
        inv_id = datos.get("inventario_id") or datos.get("item_id")
        item = FeriaInventario.query.filter_by(id=int(inv_id), feria_id=f.id).first() if inv_id else None
        if item is None:
            return jsonify({"ok": False, "error": "Producto no encontrado en la feria."}), 404

        try:
            cantidad = max(int(float(datos.get("cantidad") or 1)), 1)
        except (ValueError, TypeError):
            cantidad = 1
        if item.cantidad_restante < cantidad:
            return jsonify({"ok": False,
                            "error": "Sin stock suficiente para registrar la merma.",
                            "item": _feria_inv_a_json(item)}), 409

        nota = (datos.get("nota") or datos.get("motivo") or "").strip()[:200]
        item.cantidad_merma = (item.cantidad_merma or 0) + cantidad
        venta = FeriaVenta(feria_id=f.id, inventario_id=item.id,
                           producto_nombre=item.producto_nombre,
                           cantidad=cantidad, precio_total=0.0,
                           tipo="merma", nota=nota or None,
                           fecha_hora=datetime.utcnow())
        db.session.add(venta)
        db.session.commit()
        return jsonify({
            "ok": True,
            "merma": {"id": venta.id, "producto_nombre": venta.producto_nombre,
                      "cantidad": venta.cantidad, "nota": venta.nota or ""},
            "item": _feria_inv_a_json(item),
            "total_proyectado": f.total_proyectado,
            "valor_restante_mesa": f.valor_restante_mesa,
            "unidades_merma": f.unidades_merma,
        })

    @app.route("/api/v1/ferias/<int:fid>/cerrar", methods=["POST"])
    def api_feria_cerrar(fid):
        """
        Cierra la feria: calcula el balance total y la ganancia neta, marca la
        feria como 'Finalizada' y reporta el stock no vendido que vuelve al
        inventario general. Registra el costo del stand como Gasto de la operación.
        """
        if not _api_key_ok():
            return jsonify({"ok": False, "error": "API key inválida."}), 401
        f = Feria.query.get_or_404(fid)
        if f.estado == "Finalizada":
            return jsonify({"ok": False, "error": "La feria ya estaba cerrada.",
                            "feria": _feria_a_json(f, detalle=True)}), 400

        # Permite ajustar el costo de material justo al cierre (a menudo se sabe al final).
        datos = request.get_json(silent=True) or request.form or {}
        if "costo_material" in datos:
            try:
                f.costo_material = max(float(datos.get("costo_material") or 0), 0.0)
            except (ValueError, TypeError):
                pass

        # Stock no vendido que retorna al inventario general (reporte).
        devuelto = [
            {"producto_id": i.producto_id, "producto_nombre": i.producto_nombre,
             "cantidad_devuelta": i.cantidad_restante}
            for i in f.inventario if i.cantidad_restante > 0
        ]

        # Reporte de rendimiento del evento.
        estrella = f.producto_estrella
        pct_vendido = f.porcentaje_vendido
        reporte = {
            "producto_estrella": estrella,
            "porcentaje_vendido": pct_vendido,
            "porcentaje_sobrante": round(100.0 - pct_vendido, 1),
            "unidades_vendidas": f.unidades_vendidas,
            "unidades_llevadas": f.unidades_llevadas,
            "unidades_restantes": f.unidades_restantes,
            "unidades_merma": f.unidades_merma,
            "total_recaudado": round(f.total_recaudado or 0.0, 2),
            "costo_stand": f.costo_stand or 0.0,
            "costo_material": f.costo_material or 0.0,
            "ganancia_neta": f.ganancia_neta,
        }

        f.estado = "Finalizada"

        # El alquiler del stand es un gasto real de la operación (categoría Otro).
        if (f.costo_stand or 0) > 0:
            db.session.add(Gasto(
                categoria="Otro",
                descripcion=f"Stand feria: {f.nombre}",
                monto=f.costo_stand,
                fecha=f.fecha or date.today(),
            ))
        # El material/mercadería consumida también es un gasto real de la operación.
        if (f.costo_material or 0) > 0:
            db.session.add(Gasto(
                categoria="Filamento",
                descripcion=f"Material feria: {f.nombre}",
                monto=f.costo_material,
                fecha=f.fecha or date.today(),
            ))
        db.session.commit()

        return jsonify({
            "ok": True,
            "feria": _feria_a_json(f, detalle=True),
            "balance": {
                "total_recaudado": round(f.total_recaudado or 0.0, 2),
                "costo_stand": f.costo_stand or 0.0,
                "costo_material": f.costo_material or 0.0,
                "ganancia_neta": f.ganancia_neta,
                "unidades_vendidas": f.unidades_vendidas,
                "unidades_llevadas": f.unidades_llevadas,
            },
            "reporte": reporte,
            "stock_devuelto": devuelto,
        })

    # ---------- Proyectos / Impresiones ----------
    @app.route("/proyectos/parse-gcode", methods=["POST"])
    @login_required
    def parse_gcode():
        """Recibe un .gcode/.3mf por AJAX y devuelve peso (g) y tiempo (h)."""
        archivo = request.files.get("archivo")
        if not archivo or not archivo.filename:
            return jsonify({"ok": False, "error": "No se recibió ningún archivo."}), 400
        if not archivo.filename.lower().endswith((".gcode", ".gco", ".3mf")):
            return jsonify({"ok": False, "error": "Formato no soportado (usa .gcode o .3mf)."}), 400
        try:
            data = archivo.read()
            meta = parsear_metadatos_slicer(data, archivo.filename)
        except Exception as e:
            return jsonify({"ok": False, "error": f"No se pudo leer el archivo: {e}"}), 500
        if meta["peso_g"] is None and meta["tiempo_h"] is None:
            return jsonify({"ok": False,
                            "error": "No se encontraron metadatos de peso/tiempo en el archivo."}), 200
        return jsonify({"ok": True, "peso_g": meta["peso_g"],
                        "tiempo_h": meta["tiempo_h"], "archivo": archivo.filename})

    @app.route("/proyectos")
    @login_required
    def proyectos():
        lista = Proyecto.query.all()
        # Pendientes primero (cola de diseño arriba), cerrados al fondo.
        orden_estado = {e: i for i, e in enumerate(Proyecto.ESTADOS)}
        lista.sort(key=lambda p: (p.cerrado, orden_estado.get(p.estado, 99),
                                  p.fecha_entrega or date.max, -(p.id or 0)))
        # Cola de "En espera" (esperando respuesta de diseño) destacada aparte.
        en_espera = [p for p in lista if p.estado == "En espera"]
        # Deuda interna entre socios (cobrados y no saldados).
        deuda = {}
        for p in lista:
            if p.deuda_interna_pendiente:
                e = deuda.setdefault(p.cobrador_id, {"nombre": p.cobrador.nombre,
                                                     "monto": 0.0, "count": 0})
                e["monto"] += p.parte_socio
                e["count"] += 1
        return render_template("proyectos.html", proyectos=lista,
                               en_espera=en_espera, deuda=list(deuda.values()),
                               filamentos=Filamento.query.all(),
                               usuarios=User.query.all(),
                               estados=Proyecto.ESTADOS)

    @app.route("/proyectos/nuevo", methods=["POST"])
    @login_required
    def nuevo_proyecto():
        f = request.form
        cid = f.get("cobrador_id")
        p = Proyecto(
            nombre=f.get("nombre", "").strip(),
            cliente=f.get("cliente", "").strip(),
            telefono=f.get("telefono", "").strip(),
            estado=f.get("estado") or "En espera",
            peso_g=float(f.get("peso_g") or 0),
            tiempo_estimado_h=float(f.get("tiempo_estimado_h") or 0),
            horas_impresion=float(f.get("horas_impresion") or 0),
            filamento_id=int(f["filamento_id"]) if f.get("filamento_id") else None,
            fecha_entrega=_parse_fecha_opt(f.get("fecha_entrega")),
            precio_total=float(f.get("precio_total") or 0),
            adelanto=float(f.get("adelanto") or 0),
            # quién COBRA se elige (opcional); quién REGISTRA es el usuario logueado
            cobrador_id=int(cid) if cid not in (None, "", "0") else None,
            usuario_id=current_user.id,
        )
        if not p.nombre:
            flash("El nombre del proyecto es obligatorio.", "error")
        else:
            # Guarda físicamente el G-code/3MF subido con el formulario
            p.gcode_filename = _guardar_gcode(request.files.get("gcode_file"))
            p.imagen_filename = _guardar_imagen(request.files.get("imagen_file"))
            db.session.add(p)
            db.session.commit()
            flash("Proyecto creado.", "ok")
        return redirect(url_for("proyectos"))

    @app.route("/proyectos/<int:pid>/estado", methods=["POST"])
    @login_required
    def cambiar_estado(pid):
        p = Proyecto.query.get_or_404(pid)
        nuevo = request.form.get("estado")
        if nuevo in Proyecto.ESTADOS:
            if nuevo == "Imprimiendo" and p.estado != "Imprimiendo":
                p.inicio_impresion = datetime.utcnow()
                # El stock de gramos se descuenta solo si el pedido tiene
                # filamento y peso asignados; si faltan, avisar para que el
                # inventario del taller no quede desactualizado.
                if not p.filamento_id or not (p.peso_g or 0):
                    flash(f"«{p.nombre}» empezó a imprimir sin "
                          f"{'filamento asignado' if not p.filamento_id else 'peso (gramos)'} — "
                          f"el stock del taller NO se descontará. Edita el pedido para corregirlo.",
                          "error")
                elif p.filamento and p.filamento.gramos_restantes - p.peso_g < 0:
                    flash(f"Ojo: a {p.filamento.etiqueta} no le alcanzan los gramos "
                          f"(quedarían {p.filamento.gramos_restantes - p.peso_g:.0f} g). "
                          f"Revisa el stock real del rollo.", "error")
            if nuevo == "Entregado" and p.estado != "Entregado":
                p.fecha_entregado = datetime.utcnow()
            p.estado = nuevo
            db.session.commit()
        return redirect(url_for("proyectos"))

    @app.route("/proyectos/<int:pid>/saldar", methods=["POST"])
    @login_required
    def saldar_proyecto(pid):
        """Marca/desmarca que el cobrador ya pasó su parte al otro socio."""
        p = Proyecto.query.get_or_404(pid)
        p.saldado = not p.saldado
        p.fecha_saldado = datetime.utcnow() if p.saldado else None
        db.session.commit()
        return redirect(request.referrer or url_for("proyectos"))

    @app.route("/proyectos/<int:pid>/editar", methods=["GET", "POST"])
    @login_required
    def editar_proyecto(pid):
        p = Proyecto.query.get_or_404(pid)
        if request.method == "POST":
            f = request.form
            p.nombre = f.get("nombre", "").strip() or p.nombre
            p.cliente = f.get("cliente", "").strip()
            p.estado = f.get("estado") if f.get("estado") in Proyecto.ESTADOS else p.estado
            p.peso_g = float(f.get("peso_g") or 0)
            p.tiempo_estimado_h = float(f.get("tiempo_estimado_h") or 0)
            if f.get("horas_impresion") is not None and f.get("horas_impresion") != "":
                p.horas_impresion = float(f.get("horas_impresion") or 0)
            p.filamento_id = int(f["filamento_id"]) if f.get("filamento_id") else None
            p.fecha_entrega = _parse_fecha_opt(f.get("fecha_entrega"))
            p.precio_total = float(f.get("precio_total") or 0)
            p.adelanto = float(f.get("adelanto") or 0)
            p.telefono = f.get("telefono", "").strip()
            p.usuario_id = int(f["usuario_id"]) if f.get("usuario_id") else None
            p.cobrador_id = int(f["cobrador_id"]) if f.get("cobrador_id") else None

            # ¿Subió un archivo nuevo? -> reparsear, borrar el viejo y guardar el nuevo
            nuevo = request.files.get("gcode_file")
            if nuevo and nuevo.filename:
                ext = os.path.splitext(secure_filename(nuevo.filename))[1].lower()
                if ext in EXTENSIONES_GCODE:
                    data = nuevo.read()
                    meta = parsear_metadatos_slicer(data, nuevo.filename)
                    if meta["peso_g"] is not None:
                        p.peso_g = meta["peso_g"]
                    if meta["tiempo_h"] is not None:
                        p.tiempo_estimado_h = meta["tiempo_h"]
                    _borrar_gcode(p.gcode_filename)            # elimina el archivo viejo
                    p.gcode_filename = _guardar_bytes_gcode(data, ext)  # guarda el nuevo (UUID)
                    flash("Archivo G-code reemplazado y metadatos actualizados.", "ok")
                else:
                    flash("Formato de archivo no soportado; se conservó el anterior.", "error")
            # Si NO subió archivo, gcode_filename queda intacto.

            # ¿Subió una foto nueva? -> borrar la anterior y guardar la nueva
            nueva_img = request.files.get("imagen_file")
            if nueva_img and nueva_img.filename:
                guardada = _guardar_imagen(nueva_img)
                if guardada:
                    _borrar_imagen(p.imagen_filename)   # elimina la foto vieja
                    p.imagen_filename = guardada
                    flash("Foto del proyecto actualizada.", "ok")
                else:
                    flash("Formato de imagen no soportado (usa JPG, PNG o WEBP); "
                          "se conservó la anterior.", "error")
            # Quitar la foto sin subir otra (checkbox de la plantilla)
            elif request.form.get("quitar_imagen") and p.imagen_filename:
                _borrar_imagen(p.imagen_filename)
                p.imagen_filename = None

            db.session.commit()  # el costo se recalcula solo (propiedad derivada)
            flash("Proyecto actualizado.", "ok")
            return redirect(url_for("proyectos"))
        return render_template("editar_proyecto.html", p=p,
                               filamentos=Filamento.query.all(),
                               usuarios=User.query.all(),
                               estados=Proyecto.ESTADOS)

    @app.route("/proyectos/<int:pid>/gcode")
    @login_required
    def descargar_gcode(pid):
        p = Proyecto.query.get_or_404(pid)
        if not p.gcode_filename:
            return redirect(url_for("proyectos"))
        return send_from_directory(_gcodes_dir(), p.gcode_filename, as_attachment=True)

    @app.route("/uploads/imagenes/<path:filename>")
    @login_required
    def imagen_proyecto(filename):
        """Sirve la foto de un proyecto (miniatura y vista completa)."""
        return send_from_directory(_imagenes_dir(), filename)

    @app.route("/proyectos/<int:pid>/eliminar", methods=["POST"])
    @login_required
    def eliminar_proyecto(pid):
        p = Proyecto.query.get_or_404(pid)
        _borrar_gcode(p.gcode_filename)   # borra el archivo físico para no dejar basura
        _borrar_imagen(p.imagen_filename)  # borra también la foto de la pieza
        db.session.delete(p)
        db.session.commit()
        return redirect(url_for("proyectos"))

    # ---------- Calendario de entregas ----------
    @app.route("/calendario")
    @login_required
    def calendario():
        import calendar as _cal
        hoy = date.today()
        try:
            anio = int(request.args.get("anio") or hoy.year)
            mes = int(request.args.get("mes") or hoy.month)
        except ValueError:
            anio, mes = hoy.year, hoy.month
        pedidos = Proyecto.query.filter(
            Proyecto.fecha_entrega.isnot(None),
            Proyecto.estado != "Cancelado",
            extract("year", Proyecto.fecha_entrega) == anio,
            extract("month", Proyecto.fecha_entrega) == mes,
        ).all()
        por_dia = {}
        for p in pedidos:
            por_dia.setdefault(p.fecha_entrega.day, []).append(p)
        _cal.setfirstweekday(0)   # lunes
        semanas = _cal.monthcalendar(anio, mes)
        # Navegación de mes anterior/siguiente
        prev = (anio - 1, 12) if mes == 1 else (anio, mes - 1)
        sig = (anio + 1, 1) if mes == 12 else (anio, mes + 1)
        return render_template("calendario.html", anio=anio, mes=mes,
                               mes_nombre=MESES[mes], semanas=semanas,
                               por_dia=por_dia, hoy=hoy,
                               prev=prev, sig=sig, meses=MESES)

    # ---------- Ranking de clientes ----------
    @app.route("/clientes")
    @login_required
    def clientes():
        """Ranking: quién compra más y quién no vuelve hace tiempo."""
        agregados = {}
        for p in Proyecto.query.filter(Proyecto.cliente.isnot(None)).all():
            nombre = (p.cliente or "").strip()
            if not nombre:
                continue
            clave = nombre.lower()
            c = agregados.setdefault(clave, {
                "nombre": nombre, "pedidos": 0, "total": 0.0,
                "ultimo": None, "telefono": None, "activos": 0})
            c["pedidos"] += 1
            c["total"] += p.ingreso_reconocido
            if p.telefono and not c["telefono"]:
                c["telefono"] = p.telefono
            if not p.cerrado:
                c["activos"] += 1
            fecha = p.creado.date() if p.creado else None
            if fecha and (not c["ultimo"] or fecha > c["ultimo"]):
                c["ultimo"] = fecha
        ranking = sorted(agregados.values(),
                         key=lambda c: (c["total"], c["pedidos"]), reverse=True)
        hoy = date.today()
        for c in ranking:
            c["total"] = round(c["total"], 2)
            c["dias_sin_comprar"] = (hoy - c["ultimo"]).days if c["ultimo"] else None
        return render_template("clientes.html", ranking=ranking)

    # ---------- Ficha de cliente ----------
    @app.route("/cliente/<path:nombre>")
    @login_required
    def ficha_cliente(nombre):
        pedidos = Proyecto.query.filter(
            db.func.lower(Proyecto.cliente) == nombre.strip().lower()
        ).order_by(Proyecto.creado.desc()).all()
        total = sum(p.ingreso_reconocido for p in pedidos)
        telefono = next((p.telefono for p in pedidos if p.telefono), "")
        return render_template("cliente.html", nombre=nombre, pedidos=pedidos,
                               total=total, telefono=telefono)

    # ---------- Comprobante / recibo del pedido ----------
    @app.route("/pedido/<int:pid>/recibo")
    @login_required
    def recibo_pedido(pid):
        p = Proyecto.query.get_or_404(pid)
        return render_template("recibo.html", p=p, hoy=date.today())

    # ---------- Seguimiento público (sin login) ----------
    @app.route("/seguir/<token>")
    def seguir_pedido(token):
        p = Proyecto.query.filter_by(public_token=token).first_or_404()
        # Pasos del flujo para la barra de progreso (sin estados terminales raros).
        pasos = ["En espera", "Diseñando", "Por imprimir", "Imprimiendo",
                 "Terminado", "Entregado"]
        try:
            idx = pasos.index(p.estado)
        except ValueError:
            idx = -1
        return render_template("seguimiento.html", p=p, pasos=pasos, idx=idx)

    # ---------- Impresoras (mantenimiento) ----------
    @app.route("/impresoras")
    @login_required
    def impresoras():
        ms = Impresora.query.order_by(Impresora.nombre).all()
        return render_template("impresoras.html", impresoras=ms)

    @app.route("/impresoras/nueva", methods=["POST"])
    @login_required
    def nueva_impresora():
        f = request.form
        nombre = (f.get("nombre") or "").strip()
        if nombre:
            db.session.add(Impresora(
                nombre=nombre,
                horas_totales=float(f.get("horas_totales") or 0),
                intervalo_mant_h=float(f.get("intervalo_mant_h") or 250),
                nota=(f.get("nota") or "").strip()))
            db.session.commit()
            flash("Impresora agregada.", "ok")
        return redirect(url_for("impresoras"))

    @app.route("/impresoras/<int:mid>/horas", methods=["POST"])
    @login_required
    def sumar_horas_impresora(mid):
        m = Impresora.query.get_or_404(mid)
        m.horas_totales = (m.horas_totales or 0) + float(request.form.get("horas") or 0)
        db.session.commit()
        return redirect(url_for("impresoras"))

    @app.route("/impresoras/<int:mid>/mantenimiento", methods=["POST"])
    @login_required
    def mantenimiento_impresora(mid):
        m = Impresora.query.get_or_404(mid)
        m.horas_ultimo_mant = m.horas_totales or 0
        db.session.commit()
        flash(f"Mantenimiento de «{m.nombre}» registrado.", "ok")
        return redirect(url_for("impresoras"))

    @app.route("/impresoras/<int:mid>/eliminar", methods=["POST"])
    @login_required
    def eliminar_impresora(mid):
        db.session.delete(Impresora.query.get_or_404(mid))
        db.session.commit()
        return redirect(url_for("impresoras"))

    # ---------- Catálogo público (link compartible sin login) ----------
    def _whatsapp_taller():
        """Número de WhatsApp del taller para el botón del catálogo (opcional)."""
        return (os.environ.get("TALLER_WHATSAPP") or "").replace(" ", "").replace("+", "")

    @app.route("/catalogo")
    def catalogo_publico():
        productos = (ProductoCatalogo.query.filter_by(disponible=True)
                     .order_by(ProductoCatalogo.orden, ProductoCatalogo.id).all())
        return render_template("catalogo.html", productos=productos,
                               whatsapp=_whatsapp_taller())

    @app.route("/catalogo/imagen/<path:filename>")
    def imagen_catalogo(filename):
        """Sirve las fotos del catálogo sin exigir login (página pública)."""
        return send_from_directory(_imagenes_dir(), filename)

    @app.route("/catalogo-admin")
    @login_required
    def catalogo_admin():
        productos = (ProductoCatalogo.query
                     .order_by(ProductoCatalogo.orden, ProductoCatalogo.id).all())
        return render_template("catalogo_admin.html", productos=productos,
                               whatsapp=_whatsapp_taller())

    @app.route("/catalogo-admin/nuevo", methods=["POST"])
    @login_required
    def nuevo_producto_catalogo():
        f = request.form
        nombre = (f.get("nombre") or "").strip()
        if not nombre:
            flash("El nombre del producto es obligatorio.", "error")
            return redirect(url_for("catalogo_admin"))
        db.session.add(ProductoCatalogo(
            nombre=nombre,
            descripcion=(f.get("descripcion") or "").strip() or None,
            precio=float(f.get("precio") or 0),
            orden=int(float(f.get("orden") or 0)),
            imagen_filename=_guardar_imagen(request.files.get("imagen"))))
        db.session.commit()
        flash(f"«{nombre}» agregado al catálogo.", "ok")
        return redirect(url_for("catalogo_admin"))

    @app.route("/catalogo-admin/<int:prid>/editar", methods=["POST"])
    @login_required
    def editar_producto_catalogo(prid):
        pr = ProductoCatalogo.query.get_or_404(prid)
        f = request.form
        pr.nombre = (f.get("nombre") or pr.nombre).strip()
        pr.descripcion = (f.get("descripcion") or "").strip() or None
        if f.get("precio"):
            pr.precio = float(f.get("precio") or 0)
        if f.get("orden") is not None and f.get("orden") != "":
            pr.orden = int(float(f.get("orden") or 0))
        nueva = _guardar_imagen(request.files.get("imagen"))
        if nueva:
            _borrar_imagen(pr.imagen_filename)
            pr.imagen_filename = nueva
        db.session.commit()
        flash(f"«{pr.nombre}» actualizado.", "ok")
        return redirect(url_for("catalogo_admin"))

    @app.route("/catalogo-admin/<int:prid>/disponible", methods=["POST"])
    @login_required
    def alternar_producto_catalogo(prid):
        pr = ProductoCatalogo.query.get_or_404(prid)
        pr.disponible = not pr.disponible
        db.session.commit()
        flash(f"«{pr.nombre}» {'visible en' if pr.disponible else 'oculto d'}el catálogo.", "ok")
        return redirect(url_for("catalogo_admin"))

    @app.route("/catalogo-admin/<int:prid>/eliminar", methods=["POST"])
    @login_required
    def eliminar_producto_catalogo(prid):
        pr = ProductoCatalogo.query.get_or_404(prid)
        _borrar_imagen(pr.imagen_filename)
        db.session.delete(pr)
        db.session.commit()
        return redirect(url_for("catalogo_admin"))

    # ---------- Filamentos ----------
    @app.route("/filamentos")
    @login_required
    def filamentos():
        return render_template("filamentos.html", filamentos=Filamento.query.all())

    @app.route("/filamentos/nuevo", methods=["POST"])
    @login_required
    def nuevo_filamento():
        f = request.form
        fil = Filamento(
            tipo=f.get("tipo", "PLA").strip(),
            color=f.get("color", "").strip(),
            precio_rollo=float(f.get("precio_rollo") or 0),
            peso_rollo_g=float(f.get("peso_rollo_g") or 1000),
            stock_minimo=float(f.get("stock_minimo") or 200),
        )
        db.session.add(fil)
        db.session.commit()
        flash("Filamento agregado.", "ok")
        return redirect(url_for("filamentos"))

    @app.route("/filamentos/<int:fid>/stock", methods=["POST"])
    @login_required
    def actualizar_stock_minimo(fid):
        fil = Filamento.query.get_or_404(fid)
        fil.stock_minimo = float(request.form.get("stock_minimo") or 0)
        db.session.commit()
        flash(f"Stock mínimo de {fil.etiqueta} actualizado.", "ok")
        return redirect(url_for("filamentos"))

    @app.route("/filamentos/<int:fid>/eliminar", methods=["POST"])
    @login_required
    def eliminar_filamento(fid):
        db.session.delete(Filamento.query.get_or_404(fid))
        db.session.commit()
        return redirect(url_for("filamentos"))

    # ---------- Posibles clientes (leads / mensajes por contestar) ----------
    @app.route("/posibles-clientes")
    @login_required
    def posibles_clientes():
        todos = (PosibleCliente.query
                 .order_by(PosibleCliente.fecha_mensaje.asc(),
                           PosibleCliente.id.asc()).all())
        pendientes = [c for c in todos if c.estado == "Por contestar"]
        seguimiento = [c for c in todos if c.necesita_seguimiento]
        contestados = [c for c in todos
                       if c.estado == "Contestado" and not c.necesita_seguimiento]
        cerrados = [c for c in todos if c.estado in ("Convertido", "Perdido")]
        return render_template("posibles_clientes.html",
                               pendientes=pendientes,
                               seguimiento=seguimiento,
                               contestados=contestados,
                               cerrados=cerrados,
                               estados=PosibleCliente.ESTADOS)

    @app.route("/posibles-clientes/nuevo", methods=["POST"])
    @login_required
    def nuevo_posible_cliente():
        f = request.form
        nombre = (f.get("nombre") or "").strip()
        if not nombre:
            flash("El nombre del posible cliente es obligatorio.", "error")
            return redirect(url_for("posibles_clientes"))
        db.session.add(PosibleCliente(
            nombre=nombre,
            telefono=(f.get("telefono") or "").strip() or None,
            fuente=(f.get("fuente") or "").strip() or None,
            interes=(f.get("interes") or "").strip() or None,
            fecha_mensaje=_parse_fecha_opt(f.get("fecha_mensaje")) or date.today()))
        db.session.commit()
        flash(f"«{nombre}» agregado a posibles clientes.", "ok")
        return redirect(url_for("posibles_clientes"))

    @app.route("/posibles-clientes/<int:cid>/estado", methods=["POST"])
    @login_required
    def estado_posible_cliente(cid):
        c = PosibleCliente.query.get_or_404(cid)
        nuevo = (request.form.get("estado") or "").strip()
        if nuevo in PosibleCliente.ESTADOS:
            c.estado = nuevo
            c.fecha_estado = datetime.utcnow()   # reinicia el reloj de seguimiento
            db.session.commit()
            flash(f"«{c.nombre}» → {nuevo}.", "ok")
        return redirect(url_for("posibles_clientes"))

    @app.route("/posibles-clientes/<int:cid>/editar", methods=["POST"])
    @login_required
    def editar_posible_cliente(cid):
        c = PosibleCliente.query.get_or_404(cid)
        f = request.form
        c.nombre = (f.get("nombre") or c.nombre).strip()
        c.telefono = (f.get("telefono") or "").strip() or None
        c.fuente = (f.get("fuente") or "").strip() or None
        c.interes = (f.get("interes") or "").strip() or None
        c.nota = (f.get("nota") or "").strip() or None
        db.session.commit()
        flash(f"«{c.nombre}» actualizado.", "ok")
        return redirect(url_for("posibles_clientes"))

    @app.route("/posibles-clientes/<int:cid>/eliminar", methods=["POST"])
    @login_required
    def eliminar_posible_cliente(cid):
        db.session.delete(PosibleCliente.query.get_or_404(cid))
        db.session.commit()
        return redirect(url_for("posibles_clientes"))

    # ---------- Venta de Filamentos (reventa de rollos + deuda Sirley) ----------
    def _deuda_filamentos():
        """Devuelve la deuda configurada (una sola) o None."""
        return DeudaFilamento.query.order_by(DeudaFilamento.id).first()

    @app.route("/venta-filamentos")
    @login_required
    def venta_filamentos():
        items = FilamentoTienda.query.order_by(FilamentoTienda.nombre).all()
        ventas_fil = (VentaFilamento.query
                      .order_by(VentaFilamento.fecha.desc(), VentaFilamento.id.desc())
                      .limit(30).all())
        total_vendido = round(sum(
            v.precio_total or 0 for v in VentaFilamento.query.all()), 2)
        encargos = (EncargoFilamento.query
                    .filter(EncargoFilamento.estado != "Cerrado")
                    .order_by(EncargoFilamento.fecha.asc()).all())
        return render_template(
            "venta_filamentos.html",
            items=items,
            ventas=ventas_fil,
            deuda=_deuda_filamentos(),
            valor_stock=round(sum(i.valor_stock for i in items), 2),
            rollos_stock=sum(i.cantidad or 0 for i in items),
            por_reponer=[i for i in items if i.bajo_stock],
            encargos=encargos,
            total_vendido=total_vendido)

    @app.route("/venta-filamentos/nuevo", methods=["POST"])
    @login_required
    def nuevo_filamento_tienda():
        f = request.form
        nombre = (f.get("nombre") or "").strip()
        if not nombre:
            flash("El nombre del filamento es obligatorio.", "error")
            return redirect(url_for("venta_filamentos"))
        db.session.add(FilamentoTienda(
            nombre=nombre,
            material=(f.get("material") or "PLA").strip(),
            color=(f.get("color") or "").strip(),
            cantidad=int(float(f.get("cantidad") or 0)),
            costo_unitario=float(f.get("costo_unitario") or 0),
            precio_venta=float(f.get("precio_venta") or 0),
            stock_minimo=int(float(f.get("stock_minimo") or 2))))
        db.session.commit()
        # Si alguien encargó algo parecido, recuérdalo al reponer.
        pendientes = EncargoFilamento.query.filter_by(estado="Pendiente").count()
        if pendientes:
            flash(f"Filamento agregado. Ojo: hay {pendientes} encargo(s) pendiente(s) — "
                  f"revisa si alguien buscaba este color.", "ok")
        else:
            flash("Filamento agregado a la tienda.", "ok")
        return redirect(url_for("venta_filamentos"))

    @app.route("/venta-filamentos/<int:iid>/editar", methods=["POST"])
    @login_required
    def editar_filamento_tienda(iid):
        item = FilamentoTienda.query.get_or_404(iid)
        f = request.form
        agregar = int(float(f.get("agregar") or 0))            # reposición de rollos
        if agregar:
            item.cantidad = max((item.cantidad or 0) + agregar, 0)
        if f.get("precio_venta"):
            item.precio_venta = float(f.get("precio_venta") or 0)
        if f.get("costo_unitario"):
            item.costo_unitario = float(f.get("costo_unitario") or 0)
        if f.get("stock_minimo"):
            item.stock_minimo = int(float(f.get("stock_minimo") or 2))
        db.session.commit()
        flash(f"«{item.nombre}» actualizado.", "ok")
        return redirect(url_for("venta_filamentos"))

    # --- Encargos: clientes que buscan un filamento que no hay en stock ---
    @app.route("/venta-filamentos/encargos/nuevo", methods=["POST"])
    @login_required
    def nuevo_encargo_filamento():
        f = request.form
        cliente = (f.get("cliente") or "").strip()
        descripcion = (f.get("descripcion") or "").strip()
        if not cliente or not descripcion:
            flash("El encargo necesita cliente y qué filamento busca.", "error")
            return redirect(url_for("venta_filamentos"))
        db.session.add(EncargoFilamento(
            cliente=cliente, descripcion=descripcion,
            telefono=(f.get("telefono") or "").strip() or None,
            nota=(f.get("nota") or "").strip() or None))
        db.session.commit()
        flash(f"Encargo de «{cliente}» anotado.", "ok")
        return redirect(url_for("venta_filamentos"))

    @app.route("/venta-filamentos/encargos/<int:eid>/estado", methods=["POST"])
    @login_required
    def estado_encargo_filamento(eid):
        e = EncargoFilamento.query.get_or_404(eid)
        nuevo = (request.form.get("estado") or "").strip()
        if nuevo in EncargoFilamento.ESTADOS:
            e.estado = nuevo
            db.session.commit()
            flash(f"Encargo de «{e.cliente}» → {nuevo}.", "ok")
        return redirect(url_for("venta_filamentos"))

    @app.route("/venta-filamentos/encargos/<int:eid>/eliminar", methods=["POST"])
    @login_required
    def eliminar_encargo_filamento(eid):
        db.session.delete(EncargoFilamento.query.get_or_404(eid))
        db.session.commit()
        return redirect(url_for("venta_filamentos"))

    @app.route("/venta-filamentos/<int:iid>/eliminar", methods=["POST"])
    @login_required
    def eliminar_filamento_tienda(iid):
        db.session.delete(FilamentoTienda.query.get_or_404(iid))
        db.session.commit()
        return redirect(url_for("venta_filamentos"))

    @app.route("/venta-filamentos/<int:iid>/vender", methods=["POST"])
    @login_required
    def vender_filamento(iid):
        item = FilamentoTienda.query.get_or_404(iid)
        f = request.form
        cantidad = max(int(float(f.get("cantidad") or 1)), 1)
        if cantidad > (item.cantidad or 0):
            flash(f"Stock insuficiente de «{item.nombre}» "
                  f"(quedan {item.cantidad or 0}).", "error")
            return redirect(url_for("venta_filamentos"))
        # Total editable (para descuentos); si viene vacío usa precio de lista.
        try:
            precio_total = float(f.get("precio_total") or "")
        except ValueError:
            precio_total = cantidad * (item.precio_venta or 0.0)
        precio_total = round(max(precio_total, 0.0), 2)

        item.cantidad = (item.cantidad or 0) - cantidad
        venta = VentaFilamento(
            item_id=item.id, item_nombre=item.nombre,
            cantidad=cantidad, precio_total=precio_total,
            nota=(f.get("nota") or "").strip() or None,
            usuario_id=current_user.id)
        db.session.add(venta)

        # Abono automático a la deuda: % configurable de cada venta,
        # sin pasarse de lo pendiente.
        deuda = _deuda_filamentos()
        if deuda and deuda.activa and deuda.pendiente > 0 and precio_total > 0:
            abono = round(min(precio_total * (deuda.porcentaje or 0) / 100.0,
                              deuda.pendiente), 2)
            if abono > 0:
                venta.abono_deuda = abono
                db.session.flush()          # asegura venta.id para el vínculo
                db.session.add(AbonoDeudaFilamento(
                    deuda_id=deuda.id, venta_id=venta.id, monto=abono,
                    nota=f"Venta: {item.nombre} x{cantidad}"))
        db.session.commit()

        msg = f"Vendido {item.nombre} x{cantidad} por {fmt_bs(precio_total)}."
        if venta.abono_deuda:
            msg += f" Se abonaron {fmt_bs(venta.abono_deuda)} a la deuda."
        flash(msg, "ok")
        return redirect(url_for("venta_filamentos"))

    @app.route("/venta-filamentos/ventas/<int:vid>/eliminar", methods=["POST"])
    @login_required
    def eliminar_venta_filamento(vid):
        v = VentaFilamento.query.get_or_404(vid)
        # Devuelve el stock si el ítem sigue existiendo y revierte su abono.
        if v.item_id:
            item = FilamentoTienda.query.get(v.item_id)
            if item:
                item.cantidad = (item.cantidad or 0) + (v.cantidad or 0)
        AbonoDeudaFilamento.query.filter_by(venta_id=v.id).delete()
        db.session.delete(v)
        db.session.commit()
        flash("Venta eliminada: stock y deuda revertidos.", "ok")
        return redirect(url_for("venta_filamentos"))

    @app.route("/venta-filamentos/deuda", methods=["POST"])
    @login_required
    def configurar_deuda_filamentos():
        f = request.form
        deuda = _deuda_filamentos()
        if not deuda:
            deuda = DeudaFilamento()
            db.session.add(deuda)
        deuda.acreedor = (f.get("acreedor") or "Sirley").strip() or "Sirley"
        deuda.monto_total = max(float(f.get("monto_total") or 0), 0.0)
        deuda.porcentaje = min(max(float(f.get("porcentaje") or 0), 0.0), 100.0)
        deuda.activa = bool(f.get("activa"))
        db.session.commit()
        flash(f"Deuda de {deuda.acreedor} actualizada.", "ok")
        return redirect(url_for("venta_filamentos"))

    @app.route("/venta-filamentos/deuda/abono", methods=["POST"])
    @login_required
    def abono_manual_deuda_filamentos():
        deuda = _deuda_filamentos()
        if not deuda:
            flash("Primero configura la deuda.", "error")
            return redirect(url_for("venta_filamentos"))
        monto = round(float(request.form.get("monto") or 0), 2)
        if monto <= 0:
            flash("El monto del abono debe ser mayor a 0.", "error")
            return redirect(url_for("venta_filamentos"))
        monto = min(monto, deuda.pendiente)
        db.session.add(AbonoDeudaFilamento(
            deuda_id=deuda.id, monto=monto,
            nota=(request.form.get("nota") or "").strip() or "Abono manual"))
        db.session.commit()
        flash(f"Abono de {fmt_bs(monto)} registrado.", "ok")
        return redirect(url_for("venta_filamentos"))

    @app.route("/venta-filamentos/deuda/abonos/<int:aid>/eliminar", methods=["POST"])
    @login_required
    def eliminar_abono_deuda_filamentos(aid):
        a = AbonoDeudaFilamento.query.get_or_404(aid)
        # Si el abono vino de una venta, desliga el monto de esa venta.
        if a.venta_id:
            v = VentaFilamento.query.get(a.venta_id)
            if v:
                v.abono_deuda = 0.0
        db.session.delete(a)
        db.session.commit()
        flash("Abono eliminado.", "ok")
        return redirect(url_for("venta_filamentos"))

    # ---------- Ventas ----------
    @app.route("/ventas")
    @login_required
    def ventas():
        per = _contexto_periodo()
        q = _filtrar_mes(Venta.query, Venta.fecha, per)
        lista = q.order_by(Venta.fecha.desc(), Venta.id.desc()).all()
        return render_template("ventas.html", ventas=lista, per=per,
                               usuarios=User.query.all(),
                               proyectos=Proyecto.query.all(),
                               metodos=Venta.METODOS,
                               total=sum(v.monto for v in lista))

    @app.route("/ventas/nueva", methods=["POST"])
    @login_required
    def nueva_venta():
        f = request.form
        v = Venta(
            descripcion=f.get("descripcion", "").strip(),
            monto=float(f.get("monto") or 0),
            metodo_pago=f.get("metodo_pago") or "Efectivo",
            fecha=_parse_fecha(f.get("fecha")),
            usuario_id=current_user.id,  # registra automáticamente al usuario autenticado
            proyecto_id=int(f["proyecto_id"]) if f.get("proyecto_id") else None,
        )
        if v.monto <= 0:
            flash("El monto debe ser mayor a 0.", "error")
        else:
            db.session.add(v)
            db.session.commit()
            flash("Venta registrada.", "ok")
        return redirect(url_for("ventas"))

    @app.route("/ventas/<int:vid>/editar", methods=["GET", "POST"])
    @login_required
    def editar_venta(vid):
        v = Venta.query.get_or_404(vid)
        if request.method == "POST":
            f = request.form
            monto = float(f.get("monto") or 0)
            if monto <= 0:
                flash("El monto debe ser mayor a 0.", "error")
                return redirect(url_for("editar_venta", vid=vid))
            v.descripcion = f.get("descripcion", "").strip()
            v.monto = monto
            v.metodo_pago = f.get("metodo_pago") or v.metodo_pago
            v.fecha = _parse_fecha(f.get("fecha"))
            v.usuario_id = int(f["usuario_id"]) if f.get("usuario_id") else None
            v.proyecto_id = int(f["proyecto_id"]) if f.get("proyecto_id") else None
            db.session.commit()
            flash("Venta actualizada.", "ok")
            return redirect(url_for("ventas"))
        return render_template("editar_venta.html", v=v,
                               usuarios=User.query.all(),
                               proyectos=Proyecto.query.all(),
                               metodos=Venta.METODOS)

    @app.route("/ventas/<int:vid>/eliminar", methods=["POST"])
    @login_required
    def eliminar_venta(vid):
        db.session.delete(Venta.query.get_or_404(vid))
        db.session.commit()
        return redirect(url_for("ventas"))

    @app.route("/ventas/export.csv")
    @login_required
    def exportar_ventas():
        per = _contexto_periodo()
        filas = _filtrar_mes(Venta.query, Venta.fecha, per) \
            .order_by(Venta.fecha.asc(), Venta.id.asc()).all()
        rows = [[
            v.fecha, v.descripcion or "", v.metodo_pago,
            v.usuario.nombre if v.usuario else "",
            v.proyecto.nombre if v.proyecto else "", f"Bs. {v.monto:,.2f}"
        ] for v in filas]
        return _csv_response(f"ventas_{per['periodo']}.csv",
                             ["Fecha", "Descripción", "Método", "Cobró", "Proyecto", "Monto (Bs.)"],
                             rows)

    # ---------- Gastos ----------
    @app.route("/gastos")
    @login_required
    def gastos():
        per = _contexto_periodo()
        q = _filtrar_mes(Gasto.query, Gasto.fecha, per)
        lista = q.order_by(Gasto.fecha.desc(), Gasto.id.desc()).all()
        return render_template("gastos.html", gastos=lista, per=per,
                               usuarios=User.query.all(),
                               categorias=Gasto.CATEGORIAS,
                               total=sum(g.monto for g in lista))

    @app.route("/gastos/nuevo", methods=["POST"])
    @login_required
    def nuevo_gasto():
        f = request.form
        g = Gasto(
            categoria=f.get("categoria") or "Otro",
            descripcion=f.get("descripcion", "").strip(),
            monto=float(f.get("monto") or 0),
            fecha=_parse_fecha(f.get("fecha")),
            usuario_id=current_user.id,  # registra automáticamente al usuario autenticado
        )
        if g.monto <= 0:
            flash("El monto debe ser mayor a 0.", "error")
        else:
            db.session.add(g)
            db.session.commit()
            flash("Gasto registrado.", "ok")
        return redirect(url_for("gastos"))

    @app.route("/gastos/<int:gid>/editar", methods=["GET", "POST"])
    @login_required
    def editar_gasto(gid):
        g = Gasto.query.get_or_404(gid)
        if request.method == "POST":
            f = request.form
            monto = float(f.get("monto") or 0)
            if monto <= 0:
                flash("El monto debe ser mayor a 0.", "error")
                return redirect(url_for("editar_gasto", gid=gid))
            g.categoria = f.get("categoria") or g.categoria
            g.descripcion = f.get("descripcion", "").strip()
            g.monto = monto
            g.fecha = _parse_fecha(f.get("fecha"))
            g.usuario_id = int(f["usuario_id"]) if f.get("usuario_id") else None
            db.session.commit()
            flash("Gasto actualizado.", "ok")
            return redirect(url_for("gastos"))
        return render_template("editar_gasto.html", g=g,
                               usuarios=User.query.all(),
                               categorias=Gasto.CATEGORIAS)

    @app.route("/gastos/<int:gid>/eliminar", methods=["POST"])
    @login_required
    def eliminar_gasto(gid):
        db.session.delete(Gasto.query.get_or_404(gid))
        db.session.commit()
        return redirect(url_for("gastos"))

    @app.route("/gastos/export.csv")
    @login_required
    def exportar_gastos():
        per = _contexto_periodo()
        filas = _filtrar_mes(Gasto.query, Gasto.fecha, per) \
            .order_by(Gasto.fecha.asc(), Gasto.id.asc()).all()
        rows = [[
            g.fecha, g.categoria, g.descripcion or "",
            g.usuario.nombre if g.usuario else "", f"Bs. {g.monto:,.2f}"
        ] for g in filas]
        return _csv_response(f"gastos_{per['periodo']}.csv",
                             ["Fecha", "Categoría", "Descripción", "Pagó", "Monto (Bs.)"],
                             rows)

    # ---------- Balance / Reparto ----------
    def _ingresos_por_linea(anio, mes):
        """Ingresos del mes por línea de negocio: pedidos, ferias y filamentos."""
        pedidos = sum(p.ingreso_reconocido for p in Proyecto.query.filter(
            extract("year", Proyecto.creado) == anio,
            extract("month", Proyecto.creado) == mes).all())
        ferias = sum((v.precio_total or 0) for v in FeriaVenta.query.filter(
            extract("year", FeriaVenta.fecha_hora) == anio,
            extract("month", FeriaVenta.fecha_hora) == mes,
            FeriaVenta.tipo != "merma").all())
        filamentos = sum((v.precio_total or 0) for v in VentaFilamento.query.filter(
            extract("year", VentaFilamento.fecha) == anio,
            extract("month", VentaFilamento.fecha) == mes).all())
        return {"pedidos": round(pedidos, 2), "ferias": round(ferias, 2),
                "filamentos": round(filamentos, 2),
                "total": round(pedidos + ferias + filamentos, 2)}

    @app.route("/balance")
    @login_required
    def balance():
        per = _contexto_periodo()
        historial = Liquidacion.query.order_by(
            Liquidacion.fecha.desc(), Liquidacion.id.desc()).all()

        # Últimos 6 meses (terminando en el periodo elegido) por línea de negocio.
        lineas = []
        a, m = per["anio"], per["mes"]
        for _ in range(6):
            datos = _ingresos_por_linea(a, m)
            datos.update({"anio": a, "mes": m, "etiqueta": f"{MESES[m][:3]} {a}"})
            lineas.append(datos)
            a, m = mes_relativo(a, m, -1)
        lineas.reverse()
        max_linea = max((l["total"] for l in lineas), default=0) or 1

        return render_template("balance.html",
                               bal=calcular_balance(per["anio"], per["mes"]),
                               per=per, historial=historial, meses=MESES,
                               lineas=lineas, max_linea=max_linea)

    @app.route("/balance/liquidar", methods=["POST"])
    @login_required
    def liquidar_balance():
        """
        Registra una transferencia entre socios (total o PARCIAL). La dirección
        (quién paga a quién) la determina el servidor a partir del ajuste; el
        monto es editable por el usuario para permitir pagos parciales. No toca
        ingresos ni gastos.
        """
        anio, mes = parse_periodo(request.form.get("periodo"))
        bal = calcular_balance(anio, mes)
        sug = bal.get("liquidacion_sugerida")
        if not sug:
            flash("Las cuentas de este mes ya están a mano.", "ok")
            return redirect(url_for("balance", periodo=periodo_str(anio, mes)))

        # Monto editable: por defecto la sugerencia, tope = ajuste pendiente
        try:
            monto = float(request.form.get("monto") or sug["monto"])
        except ValueError:
            monto = sug["monto"]
        if monto <= 0:
            flash("El monto a transferir debe ser mayor a 0.", "error")
            return redirect(url_for("balance", periodo=periodo_str(anio, mes)))
        # No permitir pagar de más y voltear el desbalance
        monto = round(min(monto, sug["monto"]), 2)

        db.session.add(Liquidacion(
            anio=anio, mes=mes, fecha=date.today(), monto=monto,
            pagador_id=sug["pagador"].id, receptor_id=sug["receptor"].id,
        ))
        db.session.commit()

        remanente = round(sug["monto"] - monto, 2)
        if remanente <= 0:
            flash(f"{sug['pagador'].nombre} le pagó {fmt_bs(monto)} a "
                  f"{sug['receptor'].nombre}. Cuentas saldadas ✔", "ok")
        else:
            flash(f"Pago parcial de {fmt_bs(monto)} registrado "
                  f"({sug['pagador'].nombre} → {sug['receptor'].nombre}). "
                  f"Saldo remanente del mes: {fmt_bs(remanente)}.", "ok")
        return redirect(url_for("balance", periodo=periodo_str(anio, mes)))

    @app.route("/balance/liquidar/<int:lid>/eliminar", methods=["POST"])
    @login_required
    def eliminar_liquidacion(lid):
        """Revierte (elimina) una transferencia; el balance se recalcula solo."""
        liq = Liquidacion.query.get_or_404(lid)
        destino = periodo_str(liq.anio, liq.mes)
        db.session.delete(liq)
        db.session.commit()
        flash("Liquidación revertida. El ajuste del mes se recalculó.", "ok")
        return redirect(url_for("balance", periodo=destino))

    # ---------- Deudas e Inversiones de Capital (módulo independiente) ----------
    @app.route("/inversiones")
    @login_required
    def inversiones():
        lista = Inversion.query.order_by(Inversion.fecha.desc(), Inversion.id.desc()).all()
        total_activos = sum(i.monto_total or 0 for i in lista)
        deuda_abierta = sum(i.deuda_pendiente or 0 for i in lista if i.estado == "Pendiente")
        historial_abonos = AbonoInversion.query.order_by(
            AbonoInversion.fecha.desc(), AbonoInversion.id.desc()).all()
        return render_template("inversiones.html", inversiones=lista,
                               total_activos=total_activos, deuda_abierta=deuda_abierta,
                               estados=Inversion.ESTADOS, historial_abonos=historial_abonos)

    @app.route("/inversiones/nueva", methods=["POST"])
    @login_required
    def nueva_inversion():
        f = request.form
        aporte_j = float(f.get("aporte_jorge") or 0)
        aporte_t = float(f.get("aporte_tefi") or 0)
        deuda = Inversion.deuda_inicial(aporte_j, aporte_t)
        inv = Inversion(
            descripcion=f.get("descripcion", "").strip(),
            monto_total=float(f.get("monto_total") or 0),
            aporte_jorge=aporte_j,
            aporte_tefi=aporte_t,
            deuda_pendiente=deuda,
            estado="Saldada" if deuda <= 0 else "Pendiente",
            fecha=_parse_fecha(f.get("fecha")),
        )
        if not inv.descripcion:
            flash("La descripción de la inversión es obligatoria.", "error")
        else:
            db.session.add(inv)
            db.session.commit()
            flash("Inversión registrada.", "ok")
        return redirect(url_for("inversiones"))

    @app.route("/inversiones/<int:iid>/abono", methods=["POST"])
    @login_required
    def abonar_inversion(iid):
        inv = Inversion.query.get_or_404(iid)

        # Control de permisos: solo el socio DEUDOR puede abonar su deuda.
        # El acreedor no debe poder descontar la deuda del otro por error.
        if inv.estado == "Saldada" or not inv.deudor_username:
            flash("Esta inversión no tiene deuda pendiente que abonar.", "error")
            return redirect(url_for("inversiones"))
        if current_user.username != inv.deudor_username:
            flash(f"Solo {inv.deudor} (el socio deudor) puede registrar abonos "
                  f"de «{inv.descripcion}».", "error")
            return redirect(url_for("inversiones"))

        monto = float(request.form.get("monto") or 0)
        if monto <= 0:
            flash("El abono debe ser mayor a 0.", "error")
            return redirect(url_for("inversiones"))
        # No abonar más de lo que se debe
        monto = round(min(monto, inv.deuda_pendiente or 0.0), 2)

        inv.deuda_pendiente = round(max((inv.deuda_pendiente or 0) - monto, 0.0), 2)
        if inv.deuda_pendiente <= 0:
            inv.deuda_pendiente = 0.0
            inv.estado = "Saldada"

        # Trazabilidad: registra el abono con el saldo resultante y nota opcional
        db.session.add(AbonoInversion(
            inversion_id=inv.id, usuario_id=current_user.id, monto=monto,
            saldo_restante=inv.deuda_pendiente,
            nota=(request.form.get("nota") or "").strip() or None,
            fecha=date.today(),
        ))
        db.session.commit()

        if inv.estado == "Saldada":
            flash(f"Abono de {fmt_bs(monto)} registrado. "
                  f"Deuda de «{inv.descripcion}» saldada por completo ✔", "ok")
        else:
            flash(f"Abono de {fmt_bs(monto)} registrado. "
                  f"Saldo restante: {fmt_bs(inv.deuda_pendiente)}.", "ok")
        return redirect(url_for("inversiones"))

    @app.route("/inversiones/<int:iid>/eliminar", methods=["POST"])
    @login_required
    def eliminar_inversion(iid):
        db.session.delete(Inversion.query.get_or_404(iid))
        db.session.commit()
        flash("Inversión eliminada.", "ok")
        return redirect(url_for("inversiones"))

    # ---------- Sistema / Configuración (respaldos, sync, recarga) ----------
    def _db_path():
        """Ruta absoluta del archivo SQLite en uso (según la config actual)."""
        uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        if uri.startswith("sqlite:///"):
            return uri[len("sqlite:///"):]
        return None

    def _backups_dir():
        ruta = _db_path()
        if not ruta:
            return None
        carpeta = os.path.join(os.path.dirname(ruta), "backups")
        os.makedirs(carpeta, exist_ok=True)
        return carpeta

    def _listar_backups():
        carpeta = _backups_dir()
        if not carpeta:
            return []
        copias = []
        for nombre in sorted(os.listdir(carpeta), reverse=True):
            if nombre.endswith(".db"):
                completo = os.path.join(carpeta, nombre)
                copias.append({"nombre": nombre,
                               "size": os.path.getsize(completo)})
        return copias

    # Estado en memoria para hacer el respaldo UNA vez al día (primer request).
    _backup_estado = {"dia": None}
    MAX_BACKUPS = 14

    @app.before_request
    def backup_diario():
        """Copia diaria automática de la BD a backups/ (conserva las últimas 14)."""
        hoy = date.today()
        if _backup_estado["dia"] == hoy:
            return
        _backup_estado["dia"] = hoy
        try:
            ruta = _db_path()
            carpeta = _backups_dir()
            if not ruta or not carpeta or not os.path.isfile(ruta):
                return
            destino = os.path.join(carpeta, f"respaldo_{hoy.isoformat()}.db")
            if not os.path.isfile(destino):
                shutil.copy2(ruta, destino)
            copias = sorted(f for f in os.listdir(carpeta)
                            if f.startswith("respaldo_") and f.endswith(".db"))
            for viejo in copias[:-MAX_BACKUPS]:
                os.remove(os.path.join(carpeta, viejo))
        except OSError:
            pass   # un backup fallido nunca debe tumbar la app

    @app.route("/sistema/backups/<path:nombre>")
    @login_required
    def descargar_backup(nombre):
        carpeta = _backups_dir()
        if not carpeta:
            flash("No hay carpeta de respaldos.", "error")
            return redirect(url_for("sistema"))
        return send_from_directory(carpeta, nombre, as_attachment=True)

    def _pa_config():
        """Credenciales de PythonAnywhere leídas de variables de entorno."""
        return {
            "username": os.environ.get("PA_USERNAME"),
            "domain": os.environ.get("PA_DOMAIN"),
            "token": os.environ.get("PA_API_TOKEN"),
            "host": os.environ.get("PA_API_HOST", "www.pythonanywhere.com"),
        }

    @app.route("/sistema")
    @login_required
    def sistema():
        ruta = _db_path()
        db_info = {"path": ruta, "existe": bool(ruta and os.path.isfile(ruta)),
                   "size": 0, "nombre": os.path.basename(ruta) if ruta else "—"}
        if db_info["existe"]:
            db_info["size"] = os.path.getsize(ruta)
        pa = _pa_config()
        return render_template(
            "sistema.html", db_info=db_info, backups=_listar_backups(),
            pa_configurado=bool(pa["username"] and pa["domain"] and pa["token"]),
            pa_username=pa["username"], pa_domain=pa["domain"])

    @app.route("/sistema/exportar-db")
    @login_required
    def exportar_db():
        """Descarga directa del archivo SQLite como respaldo local."""
        ruta = _db_path()
        if not ruta or not os.path.isfile(ruta):
            flash("No se encontró el archivo de base de datos para exportar.", "error")
            return redirect(url_for("sistema"))
        carpeta, nombre = os.path.split(ruta)
        sello = date.today().isoformat()
        descarga = f"respaldo_{os.path.splitext(nombre)[0]}_{sello}.db"
        return send_from_directory(carpeta, nombre, as_attachment=True,
                                   download_name=descarga)

    @app.route("/sistema/importar-db", methods=["POST"])
    @login_required
    def importar_db():
        """
        Reemplaza la base de datos actual con un archivo .db subido. Antes de
        sobrescribir hace una copia de seguridad automática y valida que el
        archivo sea realmente una base SQLite (cabecera mágica).
        """
        if not request.form.get("confirmar"):
            flash("Debes confirmar la casilla de seguridad para restaurar la BD.", "error")
            return redirect(url_for("sistema"))

        archivo = request.files.get("db_file")
        if not archivo or not archivo.filename:
            flash("No se seleccionó ningún archivo .db para importar.", "error")
            return redirect(url_for("sistema"))
        if not archivo.filename.lower().endswith(".db"):
            flash("El archivo debe tener extensión .db (base SQLite).", "error")
            return redirect(url_for("sistema"))

        datos = archivo.read()
        if not datos.startswith(b"SQLite format 3\x00"):
            flash("El archivo no es una base de datos SQLite válida.", "error")
            return redirect(url_for("sistema"))

        ruta = _db_path()
        if not ruta:
            flash("La configuración actual no usa SQLite; no se puede restaurar.", "error")
            return redirect(url_for("sistema"))

        try:
            # Cierra conexiones abiertas para poder reemplazar el archivo (Windows)
            db.session.remove()
            db.engine.dispose()
            # Copia de seguridad de la BD actual antes de sobrescribir
            if os.path.isfile(ruta):
                respaldo = f"{ruta}.bak-{date.today().isoformat()}"
                shutil.copyfile(ruta, respaldo)
            with open(ruta, "wb") as fh:
                fh.write(datos)
            # Alinea el esquema por si la BD importada es de una versión anterior
            db.create_all()
            migrar_esquema()
            db.session.commit()
        except Exception as e:  # noqa: BLE001
            flash(f"No se pudo restaurar la base de datos: {e}", "error")
            return redirect(url_for("sistema"))

        flash("Base de datos restaurada correctamente. Se guardó un respaldo de la anterior.", "ok")
        return redirect(url_for("sistema"))

    @app.route("/sistema/git-pull", methods=["POST"])
    @login_required
    def git_pull():
        """Ejecuta 'git pull' en la carpeta del proyecto para sincronizar el código."""
        try:
            resultado = subprocess.run(
                ["git", "pull"], cwd=app.root_path,
                capture_output=True, text=True, timeout=120)
            salida = (resultado.stdout or "") + (resultado.stderr or "")
            salida = salida.strip() or "(sin salida)"
            if resultado.returncode == 0:
                flash(f"✅ Git pull ejecutado:\n{salida}", "ok")
            else:
                flash(f"⚠️ Git pull terminó con código {resultado.returncode}:\n{salida}", "error")
        except FileNotFoundError:
            flash("No se encontró 'git' en el sistema. Instálalo o usa la API de PythonAnywhere.", "error")
        except subprocess.TimeoutExpired:
            flash("El 'git pull' tardó demasiado y se canceló.", "error")
        except Exception as e:  # noqa: BLE001
            flash(f"Error al ejecutar git pull: {e}", "error")
        return redirect(url_for("sistema"))

    @app.route("/sistema/recargar-web", methods=["POST"])
    @login_required
    def recargar_web():
        """
        Recarga la aplicación web en PythonAnywhere vía su API, usando las
        credenciales de las variables de entorno (PA_USERNAME/PA_DOMAIN/PA_API_TOKEN).
        """
        pa = _pa_config()
        if not (pa["username"] and pa["domain"] and pa["token"]):
            flash("Faltan variables de entorno de PythonAnywhere "
                  "(PA_USERNAME, PA_DOMAIN, PA_API_TOKEN).", "error")
            return redirect(url_for("sistema"))

        url = (f"https://{pa['host']}/api/v0/user/{pa['username']}"
               f"/webapps/{pa['domain']}/reload/")
        req = urllib.request.Request(url, method="POST",
                                     headers={"Authorization": f"Token {pa['token']}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                codigo = resp.getcode()
            if codigo in (200, 201):
                flash(f"🔄 Aplicación web «{pa['domain']}» recargada en PythonAnywhere.", "ok")
            else:
                flash(f"PythonAnywhere respondió con código {codigo}.", "error")
        except urllib.error.HTTPError as e:
            flash(f"Error de la API de PythonAnywhere ({e.code}): {e.reason}.", "error")
        except urllib.error.URLError as e:
            flash(f"No se pudo contactar con PythonAnywhere: {e.reason}.", "error")
        except Exception as e:  # noqa: BLE001
            flash(f"Error al recargar la web: {e}", "error")
        return redirect(url_for("sistema"))

    # Filtro para formatear plata en las plantillas (moneda: Bolivianos).
    # Conserva los decimales cuando existen (ej. Bs. 120.50) y los omite
    # cuando el monto es entero (ej. Bs. 120).
    @app.template_filter("money")
    def money(v):
        try:
            return fmt_bs(v)
        except (ValueError, TypeError):
            return "Bs. 0"

    # Traduce el nombre del color del filamento a un hex para el indicador visual.
    @app.template_filter("color_hex")
    def color_hex(nombre):
        return nombre_a_hex(nombre)


app = crear_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
