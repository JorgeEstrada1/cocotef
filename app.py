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
                    Liquidacion, Inversion, AbonoInversion)

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
    "diseñando": "Diseñando", "disenando": "Diseñando", "diseno": "Diseñando",
    "por imprimir": "Por imprimir", "en cola": "Por imprimir",
    "imprimiendo": "Imprimiendo", "en impresión": "Imprimiendo",
    "en impresion": "Imprimiendo", "imprimiendo…": "Imprimiendo",
    "terminado": "Terminado", "listo": "Terminado", "lista": "Terminado",
    "entregado": "Entregado", "entregada": "Entregado", "enviado": "Entregado",
}


def normalizar_estado(valor):
    """Normaliza un estado entrante (canónico o alias) al canónico o None."""
    if not valor:
        return None
    v = str(valor).strip()
    if v in Proyecto.ESTADOS:
        return v
    return ALIAS_ESTADO.get(v.lower())

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
        """Cuenta filamentos bajo stock mínimo para el badge de la nav."""
        if not current_user.is_authenticated:
            return {"conteo_alertas": 0}
        conteo = sum(1 for f in Filamento.query.all() if f.bajo_stock)
        return {"conteo_alertas": conteo}

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

    def _proyecto_a_json(p):
        return {
            "id": p.id,
            "nombre": p.nombre,
            "cliente": p.cliente or "",
            "estado": p.estado,
            "foto_url": _url_imagen(p.imagen_filename),
            "fecha_entrega_iso": p.fecha_entrega.isoformat() if p.fecha_entrega else None,
            "saldo_pendiente": p.saldo_pendiente,
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
        activos = Proyecto.query.filter(Proyecto.estado != "Entregado").all()
        activos.sort(key=lambda p: (p.fecha_entrega is None,
                                    p.fecha_entrega or date.max,
                                    -(p.id or 0)))
        return jsonify({
            "ok": True,
            "count": len(activos),
            "pedidos": [_proyecto_a_json(p) for p in activos],
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
        p.estado = estado
        db.session.commit()
        return jsonify({"ok": True, "pedido": _proyecto_a_json(p),
                        "activo": p.estado != "Entregado"})

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
        lista = Proyecto.query.order_by(Proyecto.creado.desc()).all()
        return render_template("proyectos.html", proyectos=lista,
                               filamentos=Filamento.query.all(),
                               usuarios=User.query.all(),
                               estados=Proyecto.ESTADOS)

    @app.route("/proyectos/nuevo", methods=["POST"])
    @login_required
    def nuevo_proyecto():
        f = request.form
        p = Proyecto(
            nombre=f.get("nombre", "").strip(),
            cliente=f.get("cliente", "").strip(),
            estado=f.get("estado") or "Diseñando",
            peso_g=float(f.get("peso_g") or 0),
            tiempo_estimado_h=float(f.get("tiempo_estimado_h") or 0),
            filamento_id=int(f["filamento_id"]) if f.get("filamento_id") else None,
            fecha_entrega=_parse_fecha_opt(f.get("fecha_entrega")),
            precio_total=float(f.get("precio_total") or 0),
            adelanto=float(f.get("adelanto") or 0),
            usuario_id=current_user.id,  # registra automáticamente al usuario autenticado
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
            p.estado = nuevo
            db.session.commit()
        return redirect(url_for("proyectos"))

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
            p.filamento_id = int(f["filamento_id"]) if f.get("filamento_id") else None
            p.fecha_entrega = _parse_fecha_opt(f.get("fecha_entrega"))
            p.precio_total = float(f.get("precio_total") or 0)
            p.adelanto = float(f.get("adelanto") or 0)
            p.usuario_id = int(f["usuario_id"]) if f.get("usuario_id") else None

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
    @app.route("/balance")
    @login_required
    def balance():
        per = _contexto_periodo()
        historial = Liquidacion.query.order_by(
            Liquidacion.fecha.desc(), Liquidacion.id.desc()).all()
        return render_template("balance.html",
                               bal=calcular_balance(per["anio"], per["mes"]),
                               per=per, historial=historial, meses=MESES)

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
            flash(f"{sug['pagador'].nombre} le pagó Bs. {monto:,.0f} a "
                  f"{sug['receptor'].nombre}. Cuentas saldadas ✔", "ok")
        else:
            flash(f"Pago parcial de Bs. {monto:,.0f} registrado "
                  f"({sug['pagador'].nombre} → {sug['receptor'].nombre}). "
                  f"Saldo remanente del mes: Bs. {remanente:,.0f}.", "ok")
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
            flash(f"Abono de Bs. {monto:,.0f} registrado. "
                  f"Deuda de «{inv.descripcion}» saldada por completo ✔", "ok")
        else:
            flash(f"Abono de Bs. {monto:,.0f} registrado. "
                  f"Saldo restante: Bs. {inv.deuda_pendiente:,.0f}.", "ok")
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
            "sistema.html", db_info=db_info,
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

    # Filtro para formatear plata en las plantillas (moneda: Bolivianos)
    @app.template_filter("money")
    def money(v):
        try:
            return "Bs. {:,.0f}".format(float(v or 0))
        except (ValueError, TypeError):
            return "Bs. 0"

    # Traduce el nombre del color del filamento a un hex para el indicador visual.
    @app.template_filter("color_hex")
    def color_hex(nombre):
        return nombre_a_hex(nombre)


app = crear_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
