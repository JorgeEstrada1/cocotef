from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class Usuario(db.Model):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    nombre = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.now)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Pedido(db.Model):
    __tablename__ = 'pedidos'
    id = db.Column(db.Integer, primary_key=True)
    cliente_nombre = db.Column(db.String(100), nullable=False)
    cliente_telefono = db.Column(db.String(50))
    modelo = db.Column(db.String(200), nullable=False)
    material = db.Column(db.String(50))
    color = db.Column(db.String(50))
    cantidad = db.Column(db.Integer, default=1)
    gramos_totales = db.Column(db.Float, default=0)
    costo_materiales = db.Column(db.Float, default=0)
    precio_total = db.Column(db.Float, default=0)
    ganancia = db.Column(db.Float, default=0)
    horas_impresion = db.Column(db.Float, default=0)
    fecha_pedido = db.Column(db.Date, default=date.today)
    fecha_entrega = db.Column(db.Date, nullable=True)
    estado = db.Column(db.String(20), default='pendiente')
    impresora_id = db.Column(db.Integer, db.ForeignKey('impresoras.id'), nullable=True)
    notas = db.Column(db.Text)
    foto = db.Column(db.String(200))
    archivo_stl = db.Column(db.String(200))
    es_recurrente = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    impresora = db.relationship('Impresora', backref='pedidos')

    def calcular_costo_materiales(self, gramos, filamento):
        if filamento and filamento.peso_total > 0:
            self.costo_materiales = round((gramos / filamento.peso_total) * filamento.costo, 2)
            filamento.peso_restante -= gramos
            if filamento.peso_restante < 0:
                filamento.peso_restante = 0

    def calcular_ganancia(self):
        self.ganancia = round(self.precio_total - self.costo_materiales, 2)

class Filamento(db.Model):
    __tablename__ = 'filamentos'
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(50), nullable=False)
    color = db.Column(db.String(50))
    marca = db.Column(db.String(100))
    peso_total = db.Column(db.Float, default=1000)
    peso_restante = db.Column(db.Float, default=1000)
    costo = db.Column(db.Float, default=0)
    fecha_compra = db.Column(db.Date, default=date.today)
    activo = db.Column(db.Boolean, default=True)
    stock_alerta = db.Column(db.Float, default=200)

class GastoGeneral(db.Model):
    __tablename__ = 'gastos_generales'
    id = db.Column(db.Integer, primary_key=True)
    descripcion = db.Column(db.String(200), nullable=False)
    monto = db.Column(db.Float, default=0)
    categoria = db.Column(db.String(50))
    fecha = db.Column(db.Date, default=date.today)
    pagado_por = db.Column(db.String(20), default='ambos')

class Deuda(db.Model):
    __tablename__ = 'deudas'
    id = db.Column(db.Integer, primary_key=True)
    deudor = db.Column(db.String(50), nullable=False)
    acreedor = db.Column(db.String(50), nullable=False)
    monto = db.Column(db.Float, default=0)
    motivo = db.Column(db.String(200))
    fecha = db.Column(db.Date, default=date.today)
    estado = db.Column(db.String(20), default='pendiente')
    fecha_pago = db.Column(db.Date, nullable=True)

class Impresora(db.Model):
    __tablename__ = 'impresoras'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    activa = db.Column(db.Boolean, default=True)
    horas_diarias = db.Column(db.Float, default=24)

class HoraPorFecha(db.Model):
    __tablename__ = 'horas_por_fecha'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False)
    impresora_id = db.Column(db.Integer, db.ForeignKey('impresoras.id'), nullable=False)
    horas_ocupadas = db.Column(db.Float, default=0)

    impresora = db.relationship('Impresora', backref='horas_ocupadas')

class Proveedor(db.Model):
    __tablename__ = 'proveedores'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    contacto = db.Column(db.String(100))
    telefono = db.Column(db.String(50))
    email = db.Column(db.String(100))
    direccion = db.Column(db.String(200))
    notas = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)

class Mantenimiento(db.Model):
    __tablename__ = 'mantenimientos'
    id = db.Column(db.Integer, primary_key=True)
    impresora_id = db.Column(db.Integer, db.ForeignKey('impresoras.id'), nullable=False)
    tipo = db.Column(db.String(50), nullable=False)
    descripcion = db.Column(db.Text)
    fecha = db.Column(db.Date, default=date.today)
    fecha_proximo = db.Column(db.Date, nullable=True)
    costo = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)
    impresora = db.relationship('Impresora', backref='mantenimientos')

class Nota(db.Model):
    __tablename__ = 'notas'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    texto = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    usuario = db.relationship('Usuario', backref='notas')

class Feria(db.Model):
    __tablename__ = 'ferias'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    fecha = db.Column(db.Date, default=date.today)
    costo_stand = db.Column(db.Float, default=0)
    estado = db.Column(db.String(20), default='Activa')  # 'Activa', 'Finalizada'
    total_recaudado = db.Column(db.Float, default=0)
    ganancia_neta = db.Column(db.Float, default=0)
    fecha_cierre = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    inventario = db.relationship('FeriaInventario', backref='feria',
                                 cascade='all, delete-orphan', lazy=True)
    ventas = db.relationship('FeriaVenta', backref='feria',
                             cascade='all, delete-orphan', lazy=True)

    @property
    def unidades_vendidas(self):
        return sum(v.cantidad for v in self.ventas)

    @property
    def costo_mercaderia(self):
        # Costo estimado del stock vendido (usa precio_unitario como referencia si no hay costo real)
        return sum(i.cantidad_vendida * (i.costo_unitario or 0) for i in self.inventario)

    def to_dict(self):
        return {
            'id': self.id,
            'nombre': self.nombre,
            'fecha': self.fecha.isoformat() if self.fecha else None,
            'costo_stand': self.costo_stand,
            'estado': self.estado,
            'total_recaudado': round(self.total_recaudado, 2),
            'ganancia_neta': round(self.ganancia_neta, 2),
            'unidades_vendidas': self.unidades_vendidas,
            'fecha_cierre': self.fecha_cierre.isoformat() if self.fecha_cierre else None,
        }

class FeriaInventario(db.Model):
    __tablename__ = 'feria_inventario'
    id = db.Column(db.Integer, primary_key=True)
    feria_id = db.Column(db.Integer, db.ForeignKey('ferias.id'), nullable=False)
    producto_id = db.Column(db.Integer, nullable=True)  # opcional, ref. a producto general
    producto_nombre = db.Column(db.String(150), nullable=False)
    cantidad_llevada = db.Column(db.Integer, default=0)
    cantidad_vendida = db.Column(db.Integer, default=0)
    precio_unitario = db.Column(db.Float, default=0)
    costo_unitario = db.Column(db.Float, default=0)

    @property
    def cantidad_restante(self):
        return max(0, self.cantidad_llevada - self.cantidad_vendida)

    def to_dict(self):
        return {
            'id': self.id,
            'feria_id': self.feria_id,
            'producto_id': self.producto_id,
            'producto_nombre': self.producto_nombre,
            'cantidad_llevada': self.cantidad_llevada,
            'cantidad_vendida': self.cantidad_vendida,
            'cantidad_restante': self.cantidad_restante,
            'precio_unitario': self.precio_unitario,
            'costo_unitario': self.costo_unitario,
        }

class FeriaVenta(db.Model):
    __tablename__ = 'feria_ventas'
    id = db.Column(db.Integer, primary_key=True)
    feria_id = db.Column(db.Integer, db.ForeignKey('ferias.id'), nullable=False)
    inventario_id = db.Column(db.Integer, db.ForeignKey('feria_inventario.id'), nullable=True)
    producto_nombre = db.Column(db.String(150), nullable=False)
    cantidad = db.Column(db.Integer, default=1)
    precio_total = db.Column(db.Float, default=0)
    fecha_hora = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'feria_id': self.feria_id,
            'inventario_id': self.inventario_id,
            'producto_nombre': self.producto_nombre,
            'cantidad': self.cantidad,
            'precio_total': round(self.precio_total, 2),
            'fecha_hora': self.fecha_hora.isoformat() if self.fecha_hora else None,
        }

class Configuracion(db.Model):
    __tablename__ = 'configuracion'
    id = db.Column(db.Integer, primary_key=True)
    nombre_negocio = db.Column(db.String(100), default='Gestión 3D')
    logo = db.Column(db.String(200))
    google_client_id = db.Column(db.String(500), default='')
    google_client_secret = db.Column(db.String(500), default='')
    smtp_server = db.Column(db.String(200), default='smtp.gmail.com')
    smtp_port = db.Column(db.Integer, default=587)
    smtp_user = db.Column(db.String(200), default='')
    smtp_pass = db.Column(db.String(200), default='')
    smtp_from = db.Column(db.String(200), default='')
    notify_email = db.Column(db.String(200), default='')
    groq_api_key = db.Column(db.String(200), default='')
    groq_modelo = db.Column(db.String(100), default='llama-3.1-8b-instant')
    whatsapp_token = db.Column(db.String(500), default='')
    whatsapp_phone_id = db.Column(db.String(100), default='')
    whatsapp_verify_token = db.Column(db.String(100), default='MiTokenGestion3D2026')
    whatsapp_bienvenida = db.Column(db.Text, default='Hola! Soy el asistente virtual de {nombre_negocio}. Consultame precios, disponibilidad o hace tu pedido!')
