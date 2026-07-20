"""
Taller 3D — Sistema de gestión y control financiero para impresión 3D.
Ejecutar:  python app.py   ->  http://127.0.0.1:5000
"""
import os
import io
import csv
from datetime import date, datetime

from flask import Flask, render_template, request, redirect, url_for, flash, Response
from sqlalchemy import extract

from config import Config
from models import db, Usuario, Filamento, Proyecto, Venta, Gasto

MESES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
         "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def crear_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Asegura que exista la carpeta 'instance/' para la BD SQLite
    os.makedirs(os.path.join(app.root_path, "instance"), exist_ok=True)

    db.init_app(app)

    with app.app_context():
        db.create_all()
        sembrar_datos_iniciales()

    registrar_rutas(app)
    return app


def sembrar_datos_iniciales():
    """Crea los 2 socios si la tabla está vacía."""
    if Usuario.query.count() == 0:
        db.session.add_all([
            Usuario(nombre="Tú", color="#6366f1"),
            Usuario(nombre="Mi novia", color="#ec4899"),
        ])
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

    Regla de reparto:
      - Ganancia neta total = Ingresos - Gastos
      - Cada socio tiene derecho al 50% de la ganancia neta.
      - 'Aporte' de un socio = gastos que pagó de su bolsillo.
      - 'Cobrado' de un socio = ventas que recibió.
      - 'En mano' = cobrado - aporte  (efectivo real que tiene ahora)
      - 'Ajuste'  = lo que debería tener (50% ganancia) - lo que tiene en mano.
                    Positivo = le deben plata / Negativo = debe plata.
    """
    usuarios = Usuario.query.all()

    # Filtra ventas/gastos por mes si se indica un periodo
    vq, gq = Venta.query, Gasto.query
    if anio and mes:
        vq = vq.filter(extract("year", Venta.fecha) == anio,
                       extract("month", Venta.fecha) == mes)
        gq = gq.filter(extract("year", Gasto.fecha) == anio,
                       extract("month", Gasto.fecha) == mes)
    ventas, gastos = vq.all(), gq.all()

    total_ingresos = sum(v.monto for v in ventas)
    total_gastos = sum(g.monto for g in gastos)
    ganancia_neta = total_ingresos - total_gastos

    n = len(usuarios) or 1
    parte_justa = ganancia_neta / n  # 50% si son 2 socios

    balance_socios = []
    for u in usuarios:
        cobrado = sum(v.monto for v in ventas if v.usuario_id == u.id)
        aporte = sum(g.monto for g in gastos if g.usuario_id == u.id)
        en_mano = cobrado - aporte
        ajuste = parte_justa - en_mano
        balance_socios.append({
            "usuario": u,
            "cobrado": cobrado,
            "aporte": aporte,
            "en_mano": en_mano,
            "parte_justa": parte_justa,
            "ajuste": ajuste,
        })

    return {
        "total_ingresos": total_ingresos,
        "total_gastos": total_gastos,
        "ganancia_neta": ganancia_neta,
        "parte_justa": parte_justa,
        "socios": balance_socios,
    }


# --------------------------------------------------------------------------
#  Rutas
# --------------------------------------------------------------------------
def registrar_rutas(app):

    def _parse_fecha(valor):
        if not valor:
            return date.today()
        return datetime.strptime(valor, "%Y-%m-%d").date()

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

    # ---------- Dashboard ----------
    @app.route("/")
    def dashboard():
        per = _contexto_periodo()
        bal = calcular_balance(per["anio"], per["mes"])
        proyectos = Proyecto.query.order_by(Proyecto.creado.desc()).limit(6).all()
        conteo_estados = {
            e: Proyecto.query.filter_by(estado=e).count()
            for e in Proyecto.ESTADOS
        }
        return render_template("dashboard.html", bal=bal, per=per,
                               proyectos=proyectos, conteo_estados=conteo_estados)

    # ---------- Proyectos / Impresiones ----------
    @app.route("/proyectos")
    def proyectos():
        lista = Proyecto.query.order_by(Proyecto.creado.desc()).all()
        return render_template("proyectos.html", proyectos=lista,
                               filamentos=Filamento.query.all(),
                               usuarios=Usuario.query.all(),
                               estados=Proyecto.ESTADOS)

    @app.route("/proyectos/nuevo", methods=["POST"])
    def nuevo_proyecto():
        f = request.form
        p = Proyecto(
            nombre=f.get("nombre", "").strip(),
            cliente=f.get("cliente", "").strip(),
            estado=f.get("estado") or "Diseñando",
            peso_g=float(f.get("peso_g") or 0),
            tiempo_estimado_h=float(f.get("tiempo_estimado_h") or 0),
            filamento_id=int(f["filamento_id"]) if f.get("filamento_id") else None,
            usuario_id=int(f["usuario_id"]) if f.get("usuario_id") else None,
        )
        if not p.nombre:
            flash("El nombre del proyecto es obligatorio.", "error")
        else:
            db.session.add(p)
            db.session.commit()
            flash("Proyecto creado.", "ok")
        return redirect(url_for("proyectos"))

    @app.route("/proyectos/<int:pid>/estado", methods=["POST"])
    def cambiar_estado(pid):
        p = Proyecto.query.get_or_404(pid)
        nuevo = request.form.get("estado")
        if nuevo in Proyecto.ESTADOS:
            p.estado = nuevo
            db.session.commit()
        return redirect(url_for("proyectos"))

    @app.route("/proyectos/<int:pid>/editar", methods=["GET", "POST"])
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
            p.usuario_id = int(f["usuario_id"]) if f.get("usuario_id") else None
            db.session.commit()  # el costo se recalcula solo (propiedad derivada)
            flash("Proyecto actualizado.", "ok")
            return redirect(url_for("proyectos"))
        return render_template("editar_proyecto.html", p=p,
                               filamentos=Filamento.query.all(),
                               usuarios=Usuario.query.all(),
                               estados=Proyecto.ESTADOS)

    @app.route("/proyectos/<int:pid>/eliminar", methods=["POST"])
    def eliminar_proyecto(pid):
        db.session.delete(Proyecto.query.get_or_404(pid))
        db.session.commit()
        return redirect(url_for("proyectos"))

    # ---------- Filamentos ----------
    @app.route("/filamentos")
    def filamentos():
        return render_template("filamentos.html", filamentos=Filamento.query.all())

    @app.route("/filamentos/nuevo", methods=["POST"])
    def nuevo_filamento():
        f = request.form
        fil = Filamento(
            tipo=f.get("tipo", "PLA").strip(),
            color=f.get("color", "").strip(),
            precio_rollo=float(f.get("precio_rollo") or 0),
            peso_rollo_g=float(f.get("peso_rollo_g") or 1000),
        )
        db.session.add(fil)
        db.session.commit()
        flash("Filamento agregado.", "ok")
        return redirect(url_for("filamentos"))

    @app.route("/filamentos/<int:fid>/eliminar", methods=["POST"])
    def eliminar_filamento(fid):
        db.session.delete(Filamento.query.get_or_404(fid))
        db.session.commit()
        return redirect(url_for("filamentos"))

    # ---------- Ventas ----------
    @app.route("/ventas")
    def ventas():
        per = _contexto_periodo()
        q = _filtrar_mes(Venta.query, Venta.fecha, per)
        lista = q.order_by(Venta.fecha.desc(), Venta.id.desc()).all()
        return render_template("ventas.html", ventas=lista, per=per,
                               usuarios=Usuario.query.all(),
                               proyectos=Proyecto.query.all(),
                               metodos=Venta.METODOS,
                               total=sum(v.monto for v in lista))

    @app.route("/ventas/nueva", methods=["POST"])
    def nueva_venta():
        f = request.form
        v = Venta(
            descripcion=f.get("descripcion", "").strip(),
            monto=float(f.get("monto") or 0),
            metodo_pago=f.get("metodo_pago") or "Efectivo",
            fecha=_parse_fecha(f.get("fecha")),
            usuario_id=int(f["usuario_id"]) if f.get("usuario_id") else None,
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
                               usuarios=Usuario.query.all(),
                               proyectos=Proyecto.query.all(),
                               metodos=Venta.METODOS)

    @app.route("/ventas/<int:vid>/eliminar", methods=["POST"])
    def eliminar_venta(vid):
        db.session.delete(Venta.query.get_or_404(vid))
        db.session.commit()
        return redirect(url_for("ventas"))

    @app.route("/ventas/export.csv")
    def exportar_ventas():
        per = _contexto_periodo()
        filas = _filtrar_mes(Venta.query, Venta.fecha, per) \
            .order_by(Venta.fecha.asc(), Venta.id.asc()).all()
        rows = [[
            v.fecha, v.descripcion or "", v.metodo_pago,
            v.usuario.nombre if v.usuario else "",
            v.proyecto.nombre if v.proyecto else "", v.monto
        ] for v in filas]
        return _csv_response(f"ventas_{per['periodo']}.csv",
                             ["Fecha", "Descripción", "Método", "Cobró", "Proyecto", "Monto"],
                             rows)

    # ---------- Gastos ----------
    @app.route("/gastos")
    def gastos():
        per = _contexto_periodo()
        q = _filtrar_mes(Gasto.query, Gasto.fecha, per)
        lista = q.order_by(Gasto.fecha.desc(), Gasto.id.desc()).all()
        return render_template("gastos.html", gastos=lista, per=per,
                               usuarios=Usuario.query.all(),
                               categorias=Gasto.CATEGORIAS,
                               total=sum(g.monto for g in lista))

    @app.route("/gastos/nuevo", methods=["POST"])
    def nuevo_gasto():
        f = request.form
        g = Gasto(
            categoria=f.get("categoria") or "Otro",
            descripcion=f.get("descripcion", "").strip(),
            monto=float(f.get("monto") or 0),
            fecha=_parse_fecha(f.get("fecha")),
            usuario_id=int(f["usuario_id"]) if f.get("usuario_id") else None,
        )
        if g.monto <= 0:
            flash("El monto debe ser mayor a 0.", "error")
        else:
            db.session.add(g)
            db.session.commit()
            flash("Gasto registrado.", "ok")
        return redirect(url_for("gastos"))

    @app.route("/gastos/<int:gid>/editar", methods=["GET", "POST"])
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
                               usuarios=Usuario.query.all(),
                               categorias=Gasto.CATEGORIAS)

    @app.route("/gastos/<int:gid>/eliminar", methods=["POST"])
    def eliminar_gasto(gid):
        db.session.delete(Gasto.query.get_or_404(gid))
        db.session.commit()
        return redirect(url_for("gastos"))

    @app.route("/gastos/export.csv")
    def exportar_gastos():
        per = _contexto_periodo()
        filas = _filtrar_mes(Gasto.query, Gasto.fecha, per) \
            .order_by(Gasto.fecha.asc(), Gasto.id.asc()).all()
        rows = [[
            g.fecha, g.categoria, g.descripcion or "",
            g.usuario.nombre if g.usuario else "", g.monto
        ] for g in filas]
        return _csv_response(f"gastos_{per['periodo']}.csv",
                             ["Fecha", "Categoría", "Descripción", "Pagó", "Monto"],
                             rows)

    # ---------- Balance / Reparto ----------
    @app.route("/balance")
    def balance():
        per = _contexto_periodo()
        return render_template("balance.html",
                               bal=calcular_balance(per["anio"], per["mes"]), per=per)

    # Filtro para formatear plata en las plantillas
    @app.template_filter("money")
    def money(v):
        try:
            return "${:,.0f}".format(float(v or 0))
        except (ValueError, TypeError):
            return "$0"


app = crear_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
