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

    # Estados de proyecto que ya consumieron filamento (todo lo que se imprimió)
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

    ESTADOS = ["Diseñando", "Imprimiendo", "Terminado", "Entregado"]

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    cliente = db.Column(db.String(120))
    estado = db.Column(db.String(20), default="Diseñando")

    # Datos técnicos
    peso_g = db.Column(db.Float, default=0.0)                 # gramos de la pieza
    tiempo_estimado_h = db.Column(db.Float, default=0.0)      # horas estimadas
    filamento_id = db.Column(db.Integer, db.ForeignKey("filamentos.id"))

    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    creado = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def costo_filamento(self):
        """Costo automático del filamento para esta pieza."""
        if not self.filamento:
            return 0.0
        return round(self.peso_g * self.filamento.precio_por_gramo, 2)

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
