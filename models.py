"""Modelos de base de datos (SQLite via SQLAlchemy)."""
from datetime import date, datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


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
    proyectos = db.relationship("Proyecto", backref="usuario", lazy=True)

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

    # Flujo completo: Diseñando -> Por imprimir -> Imprimiendo -> Terminado -> Entregado
    ESTADOS = ["Diseñando", "Por imprimir", "Imprimiendo", "Terminado", "Entregado"]

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    cliente = db.Column(db.String(120))
    estado = db.Column(db.String(20), default="Diseñando")

    # Datos técnicos
    peso_g = db.Column(db.Float, default=0.0)                 # gramos de la pieza
    tiempo_estimado_h = db.Column(db.Float, default=0.0)      # horas estimadas
    filamento_id = db.Column(db.Integer, db.ForeignKey("filamentos.id"))
    fecha_entrega = db.Column(db.Date)                        # fecha comprometida de entrega
    gcode_filename = db.Column(db.String(120))               # nombre del archivo G-code/3MF en disco

    # Cobranza (adelantos / saldos). El proyecto ES la venta: unifica ambos módulos.
    precio_total = db.Column(db.Float, default=0.0)           # precio acordado del pedido
    adelanto = db.Column(db.Float, default=0.0)               # dinero ya cobrado (parcial o total)

    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    creado = db.Column(db.DateTime, default=datetime.utcnow)

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
    def dias_restantes(self):
        """Días hasta la entrega (negativo = retrasado). None si no tiene fecha."""
        if not self.fecha_entrega:
            return None
        return (self.fecha_entrega - date.today()).days

    @property
    def es_urgente(self):
        """Vence en <= 2 días o ya está retrasado, y aún no se ha entregado."""
        if self.estado == "Entregado" or self.dias_restantes is None:
            return False
        return self.dias_restantes <= 2

    def __repr__(self):
        return f"<Proyecto {self.nombre} ({self.estado})>"


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
    def deuda_total(self):
        """Deuda original (para mostrar el progreso del abono)."""
        return self.deuda_inicial(self.aporte_jorge, self.aporte_tefi)

    @property
    def abonado(self):
        """Cuánto se ha abonado ya de la deuda."""
        return round(max(self.deuda_total - (self.deuda_pendiente or 0.0), 0.0), 2)

    def __repr__(self):
        return f"<Inversion {self.descripcion} ({self.estado})>"


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
