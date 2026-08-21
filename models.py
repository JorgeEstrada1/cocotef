"""Modelos de base de datos (SQLite via SQLAlchemy)."""
import secrets
from datetime import date, datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


def _token_seguimiento():
    """Token corto e irrepetible para el link público de seguimiento."""
    return secrets.token_urlsafe(8)


class User(UserMixin, db.Model):
    """
    Socio del emprendimiento con capacidad de autenticación (jorge / tefi).
    Tabla 'usuarios': se mantiene el nombre para conservar las claves foráneas
    existentes (Venta/Gasto/Proyecto -> usuario_id).
    """
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True)       # usuario de inicio de sesión
    password_hash = db.Column(db.String(200))              # hash bcrypt
    nombre = db.Column(db.String(80), nullable=False)      # nombre visible ("Jorge")
    color = db.Column(db.String(20), default="#2dd4bf")    # color para la UI

    ventas = db.relationship("Venta", backref="usuario", lazy=True)
    gastos = db.relationship("Gasto", backref="usuario", lazy=True)
    # Proyecto tiene 2 FK a usuarios (quién registró y quién cobró): desambiguamos.
    proyectos = db.relationship("Proyecto", backref="usuario", lazy=True,
                                foreign_keys="Proyecto.usuario_id")

    def __repr__(self):
        return f"<User {self.username}>"


class Filamento(db.Model):
    """Inventario de filamento con su precio por rollo."""
    __tablename__ = "filamentos"

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(40), nullable=False)          # PLA, PETG, TPU, Resina...
    color = db.Column(db.String(40), nullable=False)
    precio_rollo = db.Column(db.Float, nullable=False)        # precio del rollo ($)
    peso_rollo_g = db.Column(db.Float, default=1000.0)        # gramos por rollo (1kg default)
    stock_minimo = db.Column(db.Float, default=200.0)         # umbral de alerta (gramos)

    proyectos = db.relationship("Proyecto", backref="filamento", lazy=True)

    # Estados de proyecto que ya consumieron filamento (todo lo físicamente impreso).
    # "Por imprimir" NO consume: la pieza está en cola pero aún no se imprimió.
    ESTADOS_CONSUMIDOS = ("Imprimiendo", "Terminado", "Entregado")

    @property
    def precio_por_gramo(self):
        if not self.peso_rollo_g:
            return 0.0
        return self.precio_rollo / self.peso_rollo_g

    @property
    def gramos_consumidos(self):
        """Gramos usados por proyectos que ya se imprimieron."""
        return sum(p.peso_g or 0 for p in self.proyectos
                   if p.estado in self.ESTADOS_CONSUMIDOS)

    @property
    def gramos_restantes(self):
        return (self.peso_rollo_g or 0) - self.gramos_consumidos

    @property
    def bajo_stock(self):
        return self.gramos_restantes < (self.stock_minimo or 0)

    @property
    def etiqueta(self):
        return f"{self.tipo} {self.color}"

    def __repr__(self):
        return f"<Filamento {self.etiqueta}>"


class Proyecto(db.Model):
    """Pieza o proyecto de impresión."""
    __tablename__ = "proyectos"

    # Flujo completo: En espera -> Diseñando -> Por imprimir -> Imprimiendo -> Terminado -> Entregado
    #   "En espera"  = el cliente nos mandó su diseño y espera respuesta (cola previa).
    #   "Cancelado"  = pedido anulado (estado terminal, fuera del flujo lineal).
    ESTADOS = ["En espera", "Diseñando", "Por imprimir", "Imprimiendo",
               "Terminado", "Entregado", "Cancelado"]
    # Estados que sacan el pedido del tablero de producción activa.
    ESTADOS_CERRADOS = ("Entregado", "Cancelado")

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    cliente = db.Column(db.String(120))
    telefono = db.Column(db.String(40))                      # WhatsApp del cliente (para avisar)
    estado = db.Column(db.String(20), default="En espera")

    # Datos técnicos
    peso_g = db.Column(db.Float, default=0.0)                 # gramos de la pieza
    tiempo_estimado_h = db.Column(db.Float, default=0.0)      # horas estimadas (slicer)
    horas_impresion = db.Column(db.Float, default=0.0)        # horas reales de impresión (monitor)
    inicio_impresion = db.Column(db.DateTime)                 # cuándo se puso a imprimir (para el timer)
    filamento_id = db.Column(db.Integer, db.ForeignKey("filamentos.id"))
    fecha_entrega = db.Column(db.Date)                        # fecha comprometida de entrega
    gcode_filename = db.Column(db.String(120))               # nombre del archivo G-code/3MF en disco
    imagen_filename = db.Column(db.String(120))              # foto principal de la pieza (JPG/PNG/WEBP)
    orden = db.Column(db.Integer, default=0)                  # orden manual en la cola de impresión
    public_token = db.Column(db.String(24), default=_token_seguimiento, unique=True)  # link público

    # Cobranza (adelantos / saldos). El proyecto ES la venta: unifica ambos módulos.
    precio_total = db.Column(db.Float, default=0.0)           # precio acordado del pedido
    adelanto = db.Column(db.Float, default=0.0)               # dinero ya cobrado (parcial o total)

    # Quién cobró la plata del cliente (se ELIGE, no se asume). Y si esa persona
    # ya le pasó su parte al otro socio (saldo de la deuda interna del pedido).
    cobrador_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    saldado = db.Column(db.Boolean, default=False)           # ¿ya me pasó mi parte de este pedido?
    fecha_saldado = db.Column(db.DateTime)
    fecha_entregado = db.Column(db.DateTime)                  # cuándo pasó a 'Entregado'

    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))   # quién registró el pedido
    creado = db.Column(db.DateTime, default=datetime.utcnow)

    cobrador = db.relationship("User", foreign_keys=[cobrador_id])

    @property
    def saldo_pendiente(self):
        """Lo que falta por cobrar = precio_total - adelanto."""
        return round((self.precio_total or 0.0) - (self.adelanto or 0.0), 2)

    @property
    def pagado_completo(self):
        """El pedido está cancelado en su totalidad (hay precio y no queda saldo)."""
        return (self.precio_total or 0.0) > 0 and self.saldo_pendiente <= 0

    @property
    def ingreso_reconocido(self):
        """
        Regla contable: el precio del pedido solo se cuenta como ingreso cuando
        el estado es 'Entregado' o el saldo pendiente es 0 (pedido cancelado
        en su totalidad). Los adelantos/pagos parciales NO se reconocen antes.
        """
        if self.estado == "Cancelado":
            return 0.0
        if self.estado == "Entregado" or self.pagado_completo:
            return self.precio_total or 0.0
        return 0.0

    @property
    def costo_filamento(self):
        """Costo automático del filamento para esta pieza."""
        if not self.filamento:
            return 0.0
        return round(self.peso_g * self.filamento.precio_por_gramo, 2)

    @property
    def ganancia(self):
        """Ganancia estimada del pedido = precio acordado - costo de filamento."""
        return round((self.precio_total or 0.0) - self.costo_filamento, 2)

    @property
    def parte_socio(self):
        """
        Lo que le corresponde a CADA socio de este pedido (reparto 50/50 del
        precio cobrado). Sirve para la deuda interna: si un socio cobró todo,
        le debe esta parte al otro hasta marcar el pedido como 'saldado'.
        """
        return round((self.precio_total or 0.0) / 2.0, 2)

    @property
    def deuda_interna_pendiente(self):
        """
        True si este pedido genera una deuda entre socios aún sin saldar:
        fue cobrado (hay cobrador y dinero) y todavía no se pasó la parte.
        """
        return bool(self.cobrador_id) and not self.saldado and (self.precio_total or 0.0) > 0

    @property
    def cerrado(self):
        """El pedido salió del tablero de producción (Entregado o Cancelado)."""
        return self.estado in self.ESTADOS_CERRADOS

    @property
    def dias_restantes(self):
        """Días hasta la entrega (negativo = retrasado). None si no tiene fecha."""
        if not self.fecha_entrega:
            return None
        return (self.fecha_entrega - date.today()).days

    @property
    def es_urgente(self):
        """Vence en <= 2 días o ya está retrasado, y sigue en producción."""
        if self.cerrado or self.estado == "En espera" or self.dias_restantes is None:
            return False
        return self.dias_restantes <= 2

    @property
    def horas_totales_impresion(self):
        """Duración a usar por el monitor: horas reales si se cargaron, si no las del slicer."""
        return self.horas_impresion or self.tiempo_estimado_h or 0.0

    @property
    def fin_impresion_estimado(self):
        """datetime en que debería terminar la impresión (None si no está imprimiendo)."""
        if self.estado != "Imprimiendo" or not self.inicio_impresion:
            return None
        horas = self.horas_totales_impresion
        if not horas:
            return None
        from datetime import timedelta
        return self.inicio_impresion + timedelta(hours=horas)

    def __repr__(self):
        return f"<Proyecto {self.nombre} ({self.estado})>"


class FotoPedido(db.Model):
    """Fotos adicionales de un pedido (galería de proceso y resultado)."""
    __tablename__ = "fotos_pedido"

    id = db.Column(db.Integer, primary_key=True)
    proyecto_id = db.Column(db.Integer, db.ForeignKey("proyectos.id"), nullable=False)
    filename = db.Column(db.String(120), nullable=False)
    nota = db.Column(db.String(160))
    creado = db.Column(db.DateTime, default=datetime.utcnow)

    proyecto = db.relationship(
        "Proyecto",
        backref=db.backref("fotos", lazy=True, cascade="all, delete-orphan"))


class Impresora(db.Model):
    """Impresora del taller con control de horas y mantenimiento de boquilla."""
    __tablename__ = "impresoras"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), nullable=False)
    horas_totales = db.Column(db.Float, default=0.0)          # horas de uso acumuladas
    horas_ultimo_mant = db.Column(db.Float, default=0.0)      # horas al último mantenimiento
    intervalo_mant_h = db.Column(db.Float, default=250.0)     # cada cuántas horas revisar boquilla
    nota = db.Column(db.String(200))
    activa = db.Column(db.Boolean, default=True)
    creado = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def horas_desde_mant(self):
        return round((self.horas_totales or 0.0) - (self.horas_ultimo_mant or 0.0), 1)

    @property
    def necesita_mant(self):
        return self.horas_desde_mant >= (self.intervalo_mant_h or 0)

    def __repr__(self):
        return f"<Impresora {self.nombre}>"


class Venta(db.Model):
    """Ingreso: dinero cobrado."""
    __tablename__ = "ventas"

    METODOS = ["Efectivo", "Transferencia", "Nequi", "Daviplata", "Tarjeta", "Otro"]

    id = db.Column(db.Integer, primary_key=True)
    descripcion = db.Column(db.String(160))
    monto = db.Column(db.Float, nullable=False)
    metodo_pago = db.Column(db.String(30), default="Efectivo")
    fecha = db.Column(db.Date, default=date.today)

    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))       # quién cobró
    proyecto_id = db.Column(db.Integer, db.ForeignKey("proyectos.id"))     # opcional

    proyecto = db.relationship("Proyecto")

    def __repr__(self):
        return f"<Venta ${self.monto}>"


class Liquidacion(db.Model):
    """
    Transferencia de dinero entre socios para 'quedar a mano' en el reparto de
    un mes. NO es ingreso ni gasto: solo mueve efectivo de un socio a otro para
    que el ajuste del periodo quede en Bs. 0. Afecta el 'en mano' de cada socio
    en calcular_balance(), nunca la ganancia neta ni la gráfica financiera.
    """
    __tablename__ = "liquidaciones"

    id = db.Column(db.Integer, primary_key=True)
    anio = db.Column(db.Integer, nullable=False)
    mes = db.Column(db.Integer, nullable=False)
    fecha = db.Column(db.Date, default=date.today)
    monto = db.Column(db.Float, nullable=False)

    pagador_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))   # quién paga (tenía de más)
    receptor_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))  # quién recibe (tenía de menos)

    pagador = db.relationship("User", foreign_keys=[pagador_id])
    receptor = db.relationship("User", foreign_keys=[receptor_id])

    def __repr__(self):
        return f"<Liquidacion {self.monto} {self.anio}-{self.mes}>"


class Inversion(db.Model):
    """
    Deuda de capital / inversión en activos (ej. una impresora). Es un módulo
    100% INDEPENDIENTE de la operación: no toca ingresos, gastos ni la gráfica
    financiera mensual. Solo registra cuánto puso cada socio en un activo y la
    deuda resultante para quedar 50/50 en la propiedad del mismo.
    """
    __tablename__ = "inversiones"

    ESTADOS = ["Pendiente", "Saldada"]

    id = db.Column(db.Integer, primary_key=True)
    descripcion = db.Column(db.String(160), nullable=False)   # "Compra Bambu Lab A2"
    monto_total = db.Column(db.Float, default=0.0)            # costo del activo (Bs.)
    aporte_jorge = db.Column(db.Float, default=0.0)           # lo que puso Jorge (Bs.)
    aporte_tefi = db.Column(db.Float, default=0.0)            # lo que puso Tefi (Bs.)
    deuda_pendiente = db.Column(db.Float, default=0.0)        # saldo que falta para quedar 50/50
    estado = db.Column(db.String(20), default="Pendiente")
    fecha = db.Column(db.Date, default=date.today)

    @staticmethod
    def deuda_inicial(aporte_jorge, aporte_tefi):
        """Deuda para igualar aportes al 50/50 = mitad de la diferencia aportada."""
        return round(abs((aporte_jorge or 0.0) - (aporte_tefi or 0.0)) / 2, 2)

    @property
    def total_aportado(self):
        return round((self.aporte_jorge or 0.0) + (self.aporte_tefi or 0.0), 2)

    @property
    def deudor(self):
        """Nombre del socio que aportó de menos (debe al otro). None si están parejos."""
        if (self.aporte_jorge or 0.0) < (self.aporte_tefi or 0.0):
            return "Jorge"
        if (self.aporte_tefi or 0.0) < (self.aporte_jorge or 0.0):
            return "Tefi"
        return None

    @property
    def acreedor(self):
        """Socio que aportó de más (le deben)."""
        d = self.deudor
        if d == "Jorge":
            return "Tefi"
        if d == "Tefi":
            return "Jorge"
        return None

    @property
    def deudor_username(self):
        """username del socio deudor (para control de permisos). None si parejos."""
        return self.deudor.lower() if self.deudor else None

    @property
    def acreedor_username(self):
        return self.acreedor.lower() if self.acreedor else None

    @property
    def deuda_total(self):
        """Deuda original (para mostrar el progreso del abono)."""
        return self.deuda_inicial(self.aporte_jorge, self.aporte_tefi)

    @property
    def abonado(self):
        """Cuánto se ha abonado ya de la deuda."""
        return round(max(self.deuda_total - (self.deuda_pendiente or 0.0), 0.0), 2)

    # Historial de abonos hechos a esta deuda (se borran junto con la inversión)
    abonos = db.relationship("AbonoInversion", backref="inversion",
                             cascade="all, delete-orphan",
                             order_by="AbonoInversion.id")

    def __repr__(self):
        return f"<Inversion {self.descripcion} ({self.estado})>"


class AbonoInversion(db.Model):
    """
    Registro de cada abono/pago hecho para reducir la deuda de una Inversion.
    Guarda quién abonó, el monto, el saldo que quedó tras el abono y una nota
    opcional. Es trazabilidad del módulo de capital (independiente de la caja).
    """
    __tablename__ = "abonos_inversion"

    id = db.Column(db.Integer, primary_key=True)
    inversion_id = db.Column(db.Integer, db.ForeignKey("inversiones.id"))
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))   # socio que abonó
    monto = db.Column(db.Float, nullable=False)
    saldo_restante = db.Column(db.Float, default=0.0)                  # deuda tras el abono
    nota = db.Column(db.String(200))
    fecha = db.Column(db.Date, default=date.today)

    usuario = db.relationship("User")

    def __repr__(self):
        return f"<AbonoInversion {self.monto} inv={self.inversion_id}>"


class Gasto(db.Model):
    """Egreso: filamento, cajas, envíos, luz, etc."""
    __tablename__ = "gastos"

    CATEGORIAS = ["Filamento", "Resina", "Cajas/Empaque", "Envíos",
                  "Luz/Servicios", "Repuestos", "Herramientas", "Otro"]

    id = db.Column(db.Integer, primary_key=True)
    categoria = db.Column(db.String(40), default="Otro")
    descripcion = db.Column(db.String(160))
    monto = db.Column(db.Float, nullable=False)
    fecha = db.Column(db.Date, default=date.today)

    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))       # quién pagó (aporte)

    def __repr__(self):
        return f"<Gasto {self.categoria} ${self.monto}>"


# --------------------------------------------------------------------------
#  Módulo de Ferias y Eventos (POS móvil para vender en vivo)
# --------------------------------------------------------------------------
class Feria(db.Model):
    """
    Un evento/feria donde se sale a vender. Lleva su propio inventario saliente
    y sus ventas rápidas. Al cerrarse calcula el balance del día.
    """
    __tablename__ = "ferias"

    ESTADOS = ["Activa", "Finalizada"]

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)        # "Feria Navideña Plaza"
    fecha = db.Column(db.Date, default=date.today)
    costo_stand = db.Column(db.Float, default=0.0)            # alquiler del puesto (Bs.)
    costo_material = db.Column(db.Float, default=0.0)         # costo del material/mercadería (Bs.)
    estado = db.Column(db.String(20), default="Activa")
    total_recaudado = db.Column(db.Float, default=0.0)        # se actualiza con cada venta
    creado = db.Column(db.DateTime, default=datetime.utcnow)

    inventario = db.relationship("FeriaInventario", backref="feria",
                                 cascade="all, delete-orphan",
                                 order_by="FeriaInventario.id")
    ventas = db.relationship("FeriaVenta", backref="feria",
                             cascade="all, delete-orphan",
                             order_by="FeriaVenta.id")

    @property
    def unidades_vendidas(self):
        return sum(i.cantidad_vendida or 0 for i in self.inventario)

    @property
    def unidades_llevadas(self):
        return sum(i.cantidad_llevada or 0 for i in self.inventario)

    @property
    def unidades_merma(self):
        """Piezas dadas de baja: dañadas, muestras gratis o canjes."""
        return sum(i.cantidad_merma or 0 for i in self.inventario)

    @property
    def unidades_restantes(self):
        return sum(i.cantidad_restante for i in self.inventario)

    @property
    def total_proyectado(self):
        """Valor total de la mercadería llevada (cantidad_llevada * precio)."""
        return round(sum(i.valor_proyectado for i in self.inventario), 2)

    @property
    def valor_restante_mesa(self):
        """Valor de lo que aún queda por vender en la mesa (a precio de venta)."""
        return round(sum(i.valor_restante for i in self.inventario), 2)

    @property
    def ganancia_neta(self):
        """Recaudado menos el costo del stand y del material (Bs.)."""
        return round((self.total_recaudado or 0.0)
                     - (self.costo_stand or 0.0)
                     - (self.costo_material or 0.0), 2)

    @property
    def porcentaje_vendido(self):
        """% de unidades vendidas respecto de lo llevado."""
        llevadas = self.unidades_llevadas
        if not llevadas:
            return 0.0
        return round(self.unidades_vendidas / llevadas * 100, 1)

    @property
    def producto_estrella(self):
        """El ítem con más unidades vendidas (o None si no se vendió nada)."""
        vendidos = [i for i in self.inventario if (i.cantidad_vendida or 0) > 0]
        if not vendidos:
            return None
        top = max(vendidos, key=lambda i: (i.cantidad_vendida or 0, i.recaudado))
        return {
            "producto_nombre": top.producto_nombre,
            "unidades": top.cantidad_vendida or 0,
            "recaudado": top.recaudado,
        }

    def __repr__(self):
        return f"<Feria {self.nombre} ({self.estado})>"


class FeriaInventario(db.Model):
    """Stock que se llevó a una feria: cuánto se llevó, cuánto se vendió y a qué precio."""
    __tablename__ = "ferias_inventario"

    id = db.Column(db.Integer, primary_key=True)
    feria_id = db.Column(db.Integer, db.ForeignKey("ferias.id"), nullable=False)
    producto_id = db.Column(db.Integer)                       # opcional (ref. lógica a un producto)
    producto_nombre = db.Column(db.String(120), nullable=False)
    cantidad_llevada = db.Column(db.Integer, default=0)
    cantidad_vendida = db.Column(db.Integer, default=0)
    cantidad_merma = db.Column(db.Integer, default=0)         # dañadas / muestras / canjes
    precio_unitario = db.Column(db.Float, default=0.0)

    @property
    def cantidad_restante(self):
        return max((self.cantidad_llevada or 0)
                   - (self.cantidad_vendida or 0)
                   - (self.cantidad_merma or 0), 0)

    @property
    def recaudado(self):
        return round((self.cantidad_vendida or 0) * (self.precio_unitario or 0.0), 2)

    @property
    def valor_proyectado(self):
        """Valor de toda la mercadería llevada de este ítem."""
        return round((self.cantidad_llevada or 0) * (self.precio_unitario or 0.0), 2)

    @property
    def valor_restante(self):
        """Valor de lo que queda por vender de este ítem (a precio de venta)."""
        return round(self.cantidad_restante * (self.precio_unitario or 0.0), 2)

    def __repr__(self):
        return f"<FeriaInventario {self.producto_nombre} {self.cantidad_vendida}/{self.cantidad_llevada}>"


class FeriaVenta(db.Model):
    """Cada venta rápida registrada en la feria (1 toque = 1 registro)."""
    __tablename__ = "ferias_ventas"

    id = db.Column(db.Integer, primary_key=True)
    feria_id = db.Column(db.Integer, db.ForeignKey("ferias.id"), nullable=False)
    inventario_id = db.Column(db.Integer, db.ForeignKey("ferias_inventario.id"))
    producto_nombre = db.Column(db.String(120), nullable=False)
    cantidad = db.Column(db.Integer, default=1)
    precio_total = db.Column(db.Float, default=0.0)
    tipo = db.Column(db.String(20), default="venta")          # venta | combo | merma
    nota = db.Column(db.String(200))                          # detalle opcional de la venta
    fecha_hora = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<FeriaVenta {self.producto_nombre} x{self.cantidad} ${self.precio_total}>"


# --------------------------------------------------------------------------
#  Módulo de Venta de Filamentos: reventa de rollos + deuda con Sirley
#  Módulo autocontenido (como Ferias): no toca el balance general.
# --------------------------------------------------------------------------
class FilamentoTienda(db.Model):
    """Rollo de filamento comprado para REVENTA (distinto del inventario de taller)."""
    __tablename__ = "filamentos_tienda"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)        # "PLA Rojo eSun 1kg"
    material = db.Column(db.String(40), default="PLA")
    color = db.Column(db.String(60))
    cantidad = db.Column(db.Integer, default=0)               # rollos en stock
    costo_unitario = db.Column(db.Float, default=0.0)         # lo que costó cada rollo (Bs.)
    precio_venta = db.Column(db.Float, default=0.0)           # precio al público (Bs.)
    creado = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def ganancia_unitaria(self):
        return round((self.precio_venta or 0.0) - (self.costo_unitario or 0.0), 2)

    @property
    def valor_stock(self):
        """Valor de lo que queda en estante, a precio de venta."""
        return round((self.cantidad or 0) * (self.precio_venta or 0.0), 2)

    def __repr__(self):
        return f"<FilamentoTienda {self.nombre} x{self.cantidad}>"


class VentaFilamento(db.Model):
    """Cada venta de rollos registrada en la tienda de filamentos."""
    __tablename__ = "ventas_filamento"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("filamentos_tienda.id"))
    item_nombre = db.Column(db.String(120), nullable=False)   # se conserva aunque se borre el ítem
    cantidad = db.Column(db.Integer, default=1)
    precio_total = db.Column(db.Float, default=0.0)
    abono_deuda = db.Column(db.Float, default=0.0)            # parte que fue a la deuda
    nota = db.Column(db.String(200))
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))   # quién vendió
    fecha = db.Column(db.Date, default=date.today)

    usuario = db.relationship("User")

    def __repr__(self):
        return f"<VentaFilamento {self.item_nombre} x{self.cantidad} ${self.precio_total}>"


class DeudaFilamento(db.Model):
    """
    Deuda con quien financió los filamentos (ej. Sirley). Configurable:
    monto total y % de cada venta que se destina automáticamente a abonarla.
    Independiente de la caja general (como el módulo de Inversiones).
    """
    __tablename__ = "deuda_filamentos"

    id = db.Column(db.Integer, primary_key=True)
    acreedor = db.Column(db.String(80), default="Sirley")
    monto_total = db.Column(db.Float, default=0.0)            # deuda original (Bs.)
    porcentaje = db.Column(db.Float, default=100.0)           # % de cada venta que abona (0-100)
    activa = db.Column(db.Boolean, default=True)              # si False, las ventas no abonan
    creado = db.Column(db.DateTime, default=datetime.utcnow)

    abonos = db.relationship("AbonoDeudaFilamento", backref="deuda",
                             cascade="all, delete-orphan",
                             order_by="AbonoDeudaFilamento.id")

    @property
    def abonado(self):
        return round(sum(a.monto or 0.0 for a in self.abonos), 2)

    @property
    def pendiente(self):
        return round(max((self.monto_total or 0.0) - self.abonado, 0.0), 2)

    @property
    def saldada(self):
        return (self.monto_total or 0.0) > 0 and self.pendiente <= 0

    @property
    def progreso_pct(self):
        if not self.monto_total:
            return 0.0
        return round(min(self.abonado / self.monto_total * 100, 100.0), 1)

    def __repr__(self):
        return f"<DeudaFilamento {self.acreedor} pendiente={self.pendiente}>"


class AbonoDeudaFilamento(db.Model):
    """Cada abono a la deuda: automático (ligado a una venta) o manual."""
    __tablename__ = "abonos_deuda_filamentos"

    id = db.Column(db.Integer, primary_key=True)
    deuda_id = db.Column(db.Integer, db.ForeignKey("deuda_filamentos.id"), nullable=False)
    venta_id = db.Column(db.Integer, db.ForeignKey("ventas_filamento.id"))  # None = abono manual
    monto = db.Column(db.Float, nullable=False)
    nota = db.Column(db.String(200))
    fecha = db.Column(db.Date, default=date.today)

    def __repr__(self):
        return f"<AbonoDeudaFilamento {self.monto} deuda={self.deuda_id}>"
