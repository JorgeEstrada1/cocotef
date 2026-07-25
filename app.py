import os, csv, uuid, io, smtplib, secrets
from datetime import date, datetime, timedelta
from functools import wraps
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, jsonify, session, send_from_directory, Response)
from models import (db, Usuario, Pedido, Filamento, GastoGeneral, Deuda,
                    Impresora, HoraPorFecha, Proveedor, Mantenimiento, Nota,
                    Configuracion, Feria, FeriaInventario, FeriaVenta)
from authlib.integrations.flask_client import OAuth

BASE = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__,
    template_folder=os.path.join(BASE, 'templates'),
    static_folder=os.path.join(BASE, 'static'))
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE, 'gestion3d.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(BASE, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

db.init_app(app)

oauth = OAuth(app)
oauth.register(
    name='google',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

PUBLIC_FOLDER = os.path.join(BASE, 'public')

# --- CORS para la PWA (frontend en Vercel u otro origen) ---
@app.after_request
def add_cors_headers(response):
    if request.path.startswith('/api/'):
        response.headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', '*')
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response

@app.before_request
def handle_preflight():
    if request.method == 'OPTIONS' and request.path.startswith('/api/'):
        resp = Response()
        resp.headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', '*')
        resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        resp.headers['Access-Control-Allow-Credentials'] = 'true'
        return resp

with app.app_context():
    db.create_all()
    # Migrar columnas nuevas a configuracion si no existen
    import sqlite3
    try:
        conn = sqlite3.connect(app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', ''))
        cursor = conn.execute("PRAGMA table_info(configuracion)")
        cols = [row[1] for row in cursor.fetchall()]
        nuevas = {
            'google_client_id': 'VARCHAR(500) DEFAULT \'\'',
            'google_client_secret': 'VARCHAR(500) DEFAULT \'\'',
            'smtp_server': 'VARCHAR(200) DEFAULT \'smtp.gmail.com\'',
            'smtp_port': 'INTEGER DEFAULT 587',
            'smtp_user': 'VARCHAR(200) DEFAULT \'\'',
            'smtp_pass': 'VARCHAR(200) DEFAULT \'\'',
            'smtp_from': 'VARCHAR(200) DEFAULT \'\'',
            'notify_email': 'VARCHAR(200) DEFAULT \'\'',
            'groq_api_key': 'VARCHAR(200) DEFAULT \'\'',
            'groq_modelo': 'VARCHAR(100) DEFAULT \'llama-3.1-8b-instant\'',
            'whatsapp_token': 'VARCHAR(500) DEFAULT \'\'',
            'whatsapp_phone_id': 'VARCHAR(100) DEFAULT \'\'',
            'whatsapp_verify_token': 'VARCHAR(100) DEFAULT \'MiTokenGestion3D2026\'',
            'whatsapp_bienvenida': 'TEXT DEFAULT \'Hola! Soy el asistente virtual.\'',
        }
        for col, tipo in nuevas.items():
            if col not in cols:
                conn.execute(f'ALTER TABLE configuracion ADD COLUMN {col} {tipo}')
        conn.commit()
        conn.close()
    except:
        pass
    if Impresora.query.count() == 0:
        for i in range(4):
            db.session.add(Impresora(nombre=f'Impresora {i+1}', activa=True, horas_diarias=24))
        db.session.commit()
    if Configuracion.query.count() == 0:
        db.session.add(Configuracion(nombre_negocio='Cotef'))
        db.session.commit()

def formatear_fecha(f):
    return f.strftime('%d/%m/%Y') if f else ''

def hoy():
    return date.today()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if not Usuario.query.get(session['user_id']):
            session.clear()
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.context_processor
def inject_now():
    user = None
    if 'user_id' in session:
        user = Usuario.query.get(session['user_id'])
        if not user:
            session.clear()
    config = Configuracion.query.first()
    return {'hoy': hoy(), 'formatear_fecha': formatear_fecha, 'current_user': user, 'config': config}

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = Usuario.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            session['user_id'] = user.id
            session['username'] = user.username
            return redirect(url_for('index'))
        flash('Usuario o contraseña incorrectos', 'danger')
    config = Configuracion.query.first()
    return render_template('login.html', config=config)

@app.route('/login/google')
def google_login():
    config = Configuracion.query.first()
    if config and config.google_client_id:
        oauth.google.client_id = config.google_client_id
        oauth.google.client_secret = config.google_client_secret
        redirect_uri = url_for('google_callback', _external=True)
        return oauth.google.authorize_redirect(redirect_uri)
    flash('Google login no configurado. Configuralo en Ajustes.', 'warning')
    return redirect(url_for('login'))

@app.route('/login/google/callback')
def google_callback():
    config = Configuracion.query.first()
    if config and config.google_client_id:
        oauth.google.client_id = config.google_client_id
        oauth.google.client_secret = config.google_client_secret
    try:
        token = oauth.google.authorize_access_token()
        userinfo = token.get('userinfo')
        if not userinfo:
            userinfo = oauth.google.parse_id_token(token)
        email = userinfo.get('email', '')
        name = userinfo.get('name', email.split('@')[0])
        username = email.split('@')[0]
        user = Usuario.query.filter_by(username=username).first()
        if not user:
            user = Usuario(username=username, nombre=name)
            user.set_password(secrets.token_hex(16))
            db.session.add(user)
            db.session.commit()
        session['user_id'] = user.id
        session['username'] = user.username
        return redirect(url_for('index'))
    except Exception as e:
        flash(f'Error al iniciar sesión con Google: {str(e)}', 'danger')
        return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    config = Configuracion.query.first()
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        nombre = request.form.get('nombre', '').strip()
        if not username or not password:
            flash('Completá todos los campos', 'danger')
            return render_template('register.html', config=config)
        if Usuario.query.filter_by(username=username).first():
            flash('Ese usuario ya existe', 'danger')
            return render_template('register.html', config=config)
        user = Usuario(username=username, nombre=nombre or username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('Usuario creado correctamente. Ahora iniciá sesión.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', config=config)

@app.route('/')
@login_required
def index():
    pedidos_pendientes = Pedido.query.filter(Pedido.estado != 'entregado').count()
    pedidos_hoy = Pedido.query.filter(Pedido.fecha_entrega == hoy(), Pedido.estado != 'entregado').count()
    pedidos_vencidos = Pedido.query.filter(Pedido.fecha_entrega < hoy(), Pedido.estado != 'entregado').count()

    mes_actual = date.today().replace(day=1)
    ingresos_mes = db.session.query(db.func.sum(Pedido.precio_total)).filter(
        Pedido.estado == 'entregado', Pedido.fecha_entrega >= mes_actual).scalar() or 0
    ganancia_mes = db.session.query(db.func.sum(Pedido.ganancia)).filter(
        Pedido.estado == 'entregado', Pedido.fecha_entrega >= mes_actual).scalar() or 0
    gastos_mes = db.session.query(db.func.sum(GastoGeneral.monto)).filter(
        GastoGeneral.fecha >= mes_actual).scalar() or 0
    deudas_pendientes = db.session.query(db.func.sum(Deuda.monto)).filter(
        Deuda.estado == 'pendiente').scalar() or 0

    filamento_bajo = Filamento.query.filter(
        Filamento.activo == True, Filamento.peso_restante <= Filamento.stock_alerta).all()

    total_horas_dia = sum(i.horas_diarias for i in Impresora.query.filter_by(activa=True).all())
    ocupadas_hoy = db.session.query(db.func.sum(HoraPorFecha.horas_ocupadas)).filter(
        HoraPorFecha.fecha == hoy()).scalar() or 0

    pedidos_recientes = Pedido.query.order_by(Pedido.fecha_entrega.asc()).limit(10).all()

    hace_30_dias = hoy() - timedelta(days=30)
    inactivos = db.session.query(
        Pedido.cliente_nombre,
        db.func.max(Pedido.fecha_entrega).label('ultimo_pedido'),
        db.func.count(Pedido.id).label('total')
    ).filter(Pedido.fecha_entrega < hace_30_dias).group_by(Pedido.cliente_nombre).having(
        db.func.count(Pedido.id) >= 2
    ).order_by(db.func.max(Pedido.fecha_entrega).asc()).limit(5).all()

    return render_template('index.html',
        pedidos_pendientes=pedidos_pendientes, pedidos_hoy=pedidos_hoy,
        pedidos_vencidos=pedidos_vencidos, ingresos_mes=ingresos_mes,
        ganancia_mes=ganancia_mes, gastos_mes=gastos_mes,
        deudas_pendientes=deudas_pendientes, filamento_bajo=filamento_bajo,
        total_horas_dia=total_horas_dia, ocupadas_hoy=ocupadas_hoy,
        pedidos_recientes=pedidos_recientes, inactivos=inactivos)

@app.route('/pedidos')
@login_required
def pedidos():
    estado = request.args.get('estado', '')
    busqueda = request.args.get('busqueda', '')
    cliente = request.args.get('cliente', '')
    query = Pedido.query
    if estado:
        query = query.filter(Pedido.estado == estado)
    if busqueda:
        query = query.filter(
            Pedido.cliente_nombre.contains(busqueda) |
            Pedido.modelo.contains(busqueda))
    if cliente:
        query = query.filter(Pedido.cliente_nombre == cliente)
    pedidos_list = query.order_by(Pedido.fecha_entrega.asc()).all()
    return render_template('pedidos.html', pedidos=pedidos_list, estado=estado, busqueda=busqueda, cliente=cliente)

@app.route('/pedidos/nuevo', methods=['GET', 'POST'])
@login_required
def pedido_nuevo():
    if request.method == 'POST':
        pedido = Pedido(
            cliente_nombre=request.form['cliente_nombre'],
            cliente_telefono=request.form.get('cliente_telefono', ''),
            modelo=request.form['modelo'],
            material=request.form.get('material', ''),
            color=request.form.get('color', ''),
            cantidad=int(request.form.get('cantidad', 1)),
            gramos_totales=float(request.form.get('gramos_totales', 0)),
            precio_total=float(request.form.get('precio_total', 0)),
            horas_impresion=float(request.form.get('horas_impresion', 0)),
            fecha_entrega=datetime.strptime(request.form['fecha_entrega'], '%Y-%m-%d').date() if request.form.get('fecha_entrega') else None,
            notas=request.form.get('notas', ''),
            es_recurrente='es_recurrente' in request.form)

        foto = request.files.get('foto')
        if foto and foto.filename:
            ext = foto.filename.rsplit('.', 1)[-1].lower() if '.' in foto.filename else 'jpg'
            filename = f"{uuid.uuid4().hex}.{ext}"
            foto.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            pedido.foto = filename

        stl = request.files.get('archivo_stl')
        if stl and stl.filename:
            ext = stl.filename.rsplit('.', 1)[-1].lower() if '.' in stl.filename else 'stl'
            filename = f"{uuid.uuid4().hex}.{ext}"
            stl.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            pedido.archivo_stl = filename

        filamento_id = request.form.get('filamento_id')
        if filamento_id:
            filamento = Filamento.query.get(int(filamento_id))
            if filamento:
                pedido.calcular_costo_materiales(pedido.gramos_totales, filamento)
                pedido.impresora_id = request.form.get('impresora_id', type=int)

        db.session.add(pedido)
        db.session.commit()

        if pedido.horas_impresion > 0 and pedido.impresora_id:
            ocupacion = HoraPorFecha.query.filter_by(fecha=pedido.fecha_entrega, impresora_id=pedido.impresora_id).first()
            if ocupacion:
                ocupacion.horas_ocupadas += pedido.horas_impresion
            else:
                db.session.add(HoraPorFecha(fecha=pedido.fecha_entrega, impresora_id=pedido.impresora_id, horas_ocupadas=pedido.horas_impresion))
            db.session.commit()

        flash('Pedido creado', 'success')
        return redirect(url_for('pedidos'))

    filamentos = Filamento.query.filter_by(activo=True).order_by(Filamento.tipo, Filamento.color).all()
    impresoras = Impresora.query.filter_by(activa=True).all()
    return render_template('pedido_form.html', pedido=None, filamentos=filamentos, impresoras=impresoras, hoy=hoy())

@app.route('/pedidos/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def pedido_editar(id):
    pedido = Pedido.query.get_or_404(id)
    if request.method == 'POST':
        horas_antes = pedido.horas_impresion
        impresora_antes = pedido.impresora_id
        gramos_antes = pedido.gramos_totales

        pedido.cliente_nombre = request.form['cliente_nombre']
        pedido.cliente_telefono = request.form.get('cliente_telefono', '')
        pedido.modelo = request.form['modelo']
        pedido.material = request.form.get('material', '')
        pedido.color = request.form.get('color', '')
        pedido.cantidad = int(request.form.get('cantidad', 1))
        pedido.gramos_totales = float(request.form.get('gramos_totales', 0))
        pedido.precio_total = float(request.form.get('precio_total', 0))
        pedido.horas_impresion = float(request.form.get('horas_impresion', 0))
        pedido.fecha_entrega = datetime.strptime(request.form['fecha_entrega'], '%Y-%m-%d').date() if request.form.get('fecha_entrega') else None
        pedido.notas = request.form.get('notas', '')
        pedido.impresora_id = request.form.get('impresora_id', type=int)
        pedido.es_recurrente = 'es_recurrente' in request.form

        foto = request.files.get('foto')
        if foto and foto.filename:
            if pedido.foto:
                old_path = os.path.join(app.config['UPLOAD_FOLDER'], pedido.foto)
                if os.path.exists(old_path):
                    os.remove(old_path)
            ext = foto.filename.rsplit('.', 1)[-1].lower() if '.' in foto.filename else 'jpg'
            filename = f"{uuid.uuid4().hex}.{ext}"
            foto.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            pedido.foto = filename

        stl = request.files.get('archivo_stl')
        if stl and stl.filename:
            if pedido.archivo_stl:
                old_stl = os.path.join(app.config['UPLOAD_FOLDER'], pedido.archivo_stl)
                if os.path.exists(old_stl): os.remove(old_stl)
            ext = stl.filename.rsplit('.', 1)[-1].lower() if '.' in stl.filename else 'stl'
            filename = f"{uuid.uuid4().hex}.{ext}"
            stl.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            pedido.archivo_stl = filename

        filamento_id = request.form.get('filamento_id')
        if filamento_id:
            filamento = Filamento.query.get(int(filamento_id))
            if filamento:
                if gramos_antes > 0 and pedido.gramos_totales != gramos_antes:
                    filamento.peso_restante += gramos_antes
                    pedido.calcular_costo_materiales(pedido.gramos_totales, filamento)

        db.session.commit()

        if pedido.impresora_id != impresora_antes or pedido.horas_impresion != horas_antes:
            if impresora_antes:
                ocupacion_vieja = HoraPorFecha.query.filter_by(fecha=pedido.fecha_entrega, impresora_id=impresora_antes).first()
                if ocupacion_vieja:
                    ocupacion_vieja.horas_ocupadas = max(0, ocupacion_vieja.horas_ocupadas - horas_antes)
            if pedido.impresora_id and pedido.horas_impresion > 0:
                ocupacion = HoraPorFecha.query.filter_by(fecha=pedido.fecha_entrega, impresora_id=pedido.impresora_id).first()
                if ocupacion:
                    ocupacion.horas_ocupadas += pedido.horas_impresion
                else:
                    db.session.add(HoraPorFecha(fecha=pedido.fecha_entrega, impresora_id=pedido.impresora_id, horas_ocupadas=pedido.horas_impresion))
            db.session.commit()

        flash('Pedido actualizado', 'success')
        return redirect(url_for('pedidos'))

    filamentos = Filamento.query.filter_by(activo=True).order_by(Filamento.tipo, Filamento.color).all()
    impresoras = Impresora.query.filter_by(activa=True).all()
    return render_template('pedido_form.html', pedido=pedido, filamentos=filamentos, impresoras=impresoras, hoy=hoy())

@app.route('/pedidos/<int:id>/eliminar', methods=['POST'])
@login_required
def pedido_eliminar(id):
    pedido = Pedido.query.get_or_404(id)
    if pedido.impresora_id and pedido.horas_impresion > 0:
        ocupacion = HoraPorFecha.query.filter_by(fecha=pedido.fecha_entrega, impresora_id=pedido.impresora_id).first()
        if ocupacion:
            ocupacion.horas_ocupadas = max(0, ocupacion.horas_ocupadas - pedido.horas_impresion)
    if pedido.gramos_totales > 0:
        filamento = Filamento.query.filter(Filamento.tipo == pedido.material, Filamento.color == pedido.color, Filamento.activo == True).first()
        if filamento:
            filamento.peso_restante += pedido.gramos_totales
    if pedido.foto:
        foto_path = os.path.join(app.config['UPLOAD_FOLDER'], pedido.foto)
        if os.path.exists(foto_path): os.remove(foto_path)
    if pedido.archivo_stl:
        stl_path = os.path.join(app.config['UPLOAD_FOLDER'], pedido.archivo_stl)
        if os.path.exists(stl_path): os.remove(stl_path)
    db.session.delete(pedido)
    db.session.commit()
    flash('Pedido eliminado', 'success')
    return redirect(url_for('pedidos'))

@app.route('/pedidos/<int:id>/duplicar', methods=['POST'])
@login_required
def pedido_duplicar(id):
    original = Pedido.query.get_or_404(id)
    nuevo = Pedido(
        cliente_nombre=original.cliente_nombre,
        cliente_telefono=original.cliente_telefono,
        modelo=original.modelo,
        material=original.material,
        color=original.color,
        cantidad=original.cantidad,
        gramos_totales=original.gramos_totales,
        costo_materiales=original.costo_materiales,
        precio_total=original.precio_total,
        horas_impresion=original.horas_impresion,
        notas=original.notas,
        es_recurrente=original.es_recurrente)
    db.session.add(nuevo)
    db.session.commit()
    flash('Pedido duplicado. Editá los datos si es necesario.', 'success')
    return redirect(url_for('pedido_editar', id=nuevo.id))

@app.route('/pedidos/<int:id>/estado', methods=['POST'])
@login_required
def pedido_estado(id):
    pedido = Pedido.query.get_or_404(id)
    nuevo_estado = request.form.get('estado', '')
    if nuevo_estado in ['pendiente', 'en_impresion', 'terminado', 'entregado']:
        pedido.estado = nuevo_estado
        if nuevo_estado == 'entregado':
            pedido.calcular_ganancia()
            db.session.add(GastoGeneral(
                descripcion=f'Pago pedido: {pedido.modelo} - {pedido.cliente_nombre}',
                monto=pedido.precio_total, categoria='ingreso_pedido', fecha=date.today(), pagado_por='ambos'))
            ganancia_mitad = pedido.ganancia / 2
            db.session.add(GastoGeneral(
                descripcion=f'Ganancia 50% - {pedido.modelo} ({pedido.cliente_nombre})',
                monto=ganancia_mitad, categoria='ganancia_pedido', fecha=date.today(), pagado_por='yo'))
            db.session.add(GastoGeneral(
                descripcion=f'Ganancia 50% - {pedido.modelo} ({pedido.cliente_nombre})',
                monto=ganancia_mitad, categoria='ganancia_pedido', fecha=date.today(), pagado_por='novia'))
        db.session.commit()
    return redirect(url_for('pedidos'))

@app.route('/pedidos/<int:id>/presupuesto')
@login_required
def pedido_presupuesto(id):
    pedido = Pedido.query.get_or_404(id)
    config = Configuracion.query.first()
    return render_template('presupuesto.html', pedido=pedido, config=config)

@app.route('/pedidos/<int:id>/presupuesto/pdf')
@login_required
def pedido_presupuesto_pdf(id):
    from fpdf import FPDF
    pedido = Pedido.query.get_or_404(id)
    config = Configuracion.query.first()
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 20)
    pdf.cell(0, 15, f'{config.nombre_negocio if config else "Cotef"}', align='C')
    pdf.ln(5)
    pdf.set_font('Helvetica', '', 10)
    pdf.cell(0, 6, 'Impresion 3D personalizada', align='C')
    pdf.ln(15)
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 10, 'PRESUPUESTO', align='R')
    pdf.ln(4)
    pdf.set_font('Helvetica', '', 10)
    pdf.cell(0, 6, f'Fecha: {hoy().strftime("%d/%m/%Y")}', align='R')
    pdf.ln(15)
    pdf.set_font('Helvetica', 'B', 12)
    pdf.cell(0, 8, 'Cliente:')
    pdf.ln(6)
    pdf.set_font('Helvetica', '', 11)
    pdf.cell(0, 6, f'{pedido.cliente_nombre}')
    if pedido.cliente_telefono:
        pdf.ln(5)
        pdf.cell(0, 6, f'Tel: {pedido.cliente_telefono}')
    pdf.ln(15)
    pdf.set_font('Helvetica', 'B', 12)
    pdf.cell(50, 8, 'Descripcion', border=1)
    pdf.cell(30, 8, 'Cantidad', border=1, align='C')
    pdf.cell(40, 8, 'P. Unitario', border=1, align='C')
    pdf.cell(40, 8, 'Total', border=1, align='C')
    pdf.ln()
    precio_unit = pedido.precio_total / pedido.cantidad if pedido.cantidad > 0 else pedido.precio_total
    pdf.set_font('Helvetica', '', 11)
    pdf.cell(50, 8, f'{pedido.modelo} ({pedido.material} {pedido.color})', border=1)
    pdf.cell(30, 8, str(pedido.cantidad), border=1, align='C')
    pdf.cell(40, 8, f'Bs {precio_unit:.2f}', border=1, align='C')
    pdf.cell(40, 8, f'Bs {pedido.precio_total:.2f}', border=1, align='C')
    pdf.ln(12)
    pdf.set_font('Helvetica', 'B', 14)
    pdf.cell(120, 10, 'TOTAL', align='R')
    pdf.cell(40, 10, f'Bs {pedido.precio_total:.2f}', align='C')
    if pedido.notas:
        pdf.ln(20)
        pdf.set_font('Helvetica', 'B', 11)
        pdf.cell(0, 8, 'Notas:')
        pdf.ln(6)
        pdf.set_font('Helvetica', '', 10)
        pdf.multi_cell(0, 6, pedido.notas)
    pdf.ln(20)
    pdf.set_font('Helvetica', '', 9)
    pdf.cell(0, 6, 'Gracias por confiar en nosotros', align='C')
    return Response(pdf.output(dest='S'), mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename=presupuesto_{pedido.cliente_nombre}_{hoy().strftime("%Y%m%d")}.pdf'})

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/clientes')
@login_required
def clientes():
    resultados = db.session.query(
        Pedido.cliente_nombre,
        Pedido.cliente_telefono,
        db.func.count(Pedido.id).label('total'),
        db.func.sum(Pedido.precio_total).label('gastado'),
        db.func.max(Pedido.fecha_entrega).label('ultimo_pedido')
    ).group_by(Pedido.cliente_nombre).order_by(db.func.count(Pedido.id).desc()).all()
    return render_template('clientes.html', clientes=resultados)

@app.route('/clientes/<nombre>')
@login_required
def cliente_detalle(nombre):
    pedidos_cliente = Pedido.query.filter(Pedido.cliente_nombre == nombre).order_by(Pedido.fecha_pedido.desc()).all()
    total = sum(p.precio_total for p in pedidos_cliente)
    cantidad = len(pedidos_cliente)
    return render_template('cliente_detalle.html', cliente=nombre, pedidos=pedidos_cliente, total=total, cantidad=cantidad)

@app.route('/filamento')
@login_required
def filamento():
    filamentos_list = Filamento.query.order_by(Filamento.tipo, Filamento.color).all()
    return render_template('filamento.html', filamentos=filamentos_list)

@app.route('/filamento/nuevo', methods=['GET', 'POST'])
@login_required
def filamento_nuevo():
    if request.method == 'POST':
        filamento = Filamento(
            tipo=request.form['tipo'], color=request.form.get('color', ''),
            marca=request.form.get('marca', ''),
            peso_total=float(request.form.get('peso_total', 1000)),
            peso_restante=float(request.form.get('peso_restante', 1000)),
            costo=float(request.form.get('costo', 0)),
            fecha_compra=datetime.strptime(request.form['fecha_compra'], '%Y-%m-%d').date() if request.form.get('fecha_compra') else date.today(),
            stock_alerta=float(request.form.get('stock_alerta', 200)))
        db.session.add(filamento)
        db.session.commit()
        flash('Filamento agregado', 'success')
        return redirect(url_for('filamento'))
    return render_template('filamento_form.html', filamento=None, hoy=hoy())

@app.route('/filamento/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def filamento_editar(id):
    filamento = Filamento.query.get_or_404(id)
    if request.method == 'POST':
        filamento.tipo = request.form['tipo']
        filamento.color = request.form.get('color', '')
        filamento.marca = request.form.get('marca', '')
        filamento.peso_total = float(request.form.get('peso_total', 1000))
        filamento.peso_restante = float(request.form.get('peso_restante', 1000))
        filamento.costo = float(request.form.get('costo', 0))
        filamento.fecha_compra = datetime.strptime(request.form['fecha_compra'], '%Y-%m-%d').date() if request.form.get('fecha_compra') else date.today()
        filamento.stock_alerta = float(request.form.get('stock_alerta', 200))
        filamento.activo = 'activo' in request.form
        db.session.commit()
        flash('Filamento actualizado', 'success')
        return redirect(url_for('filamento'))
    return render_template('filamento_form.html', filamento=filamento, hoy=hoy())

@app.route('/filamento/<int:id>/eliminar', methods=['POST'])
@login_required
def filamento_eliminar(id):
    filamento = Filamento.query.get_or_404(id)
    db.session.delete(filamento)
    db.session.commit()
    flash('Filamento eliminado', 'success')
    return redirect(url_for('filamento'))

@app.route('/finanzas')
@login_required
def finanzas():
    mes = request.args.get('mes', str(date.today().month))
    anio = request.args.get('anio', str(date.today().year))
    mes_actual = date(int(anio), int(mes), 1)

    ingresos = db.session.query(db.func.sum(Pedido.precio_total)).filter(
        Pedido.estado == 'entregado',
        db.func.strftime('%Y-%m', Pedido.fecha_entrega) == mes_actual.strftime('%Y-%m')).scalar() or 0
    ganancia = db.session.query(db.func.sum(Pedido.ganancia)).filter(
        Pedido.estado == 'entregado',
        db.func.strftime('%Y-%m', Pedido.fecha_entrega) == mes_actual.strftime('%Y-%m')).scalar() or 0
    gastos = db.session.query(db.func.sum(GastoGeneral.monto)).filter(
        ~GastoGeneral.categoria.in_(['ingreso_pedido', 'ganancia_pedido']),
        db.func.strftime('%Y-%m', GastoGeneral.fecha) == mes_actual.strftime('%Y-%m')).scalar() or 0

    gastos_lista = GastoGeneral.query.filter(
        ~GastoGeneral.categoria.in_(['ingreso_pedido', 'ganancia_pedido']),
        db.func.strftime('%Y-%m', GastoGeneral.fecha) == mes_actual.strftime('%Y-%m')
    ).order_by(GastoGeneral.fecha.desc()).all()

    ganancia_yo = db.session.query(db.func.sum(GastoGeneral.monto)).filter(
        GastoGeneral.categoria == 'ganancia_pedido', GastoGeneral.pagado_por == 'yo',
        db.func.strftime('%Y-%m', GastoGeneral.fecha) == mes_actual.strftime('%Y-%m')).scalar() or 0
    ganancia_novia = db.session.query(db.func.sum(GastoGeneral.monto)).filter(
        GastoGeneral.categoria == 'ganancia_pedido', GastoGeneral.pagado_por == 'novia',
        db.func.strftime('%Y-%m', GastoGeneral.fecha) == mes_actual.strftime('%Y-%m')).scalar() or 0

    meses = [(1, 'Enero'), (2, 'Febrero'), (3, 'Marzo'), (4, 'Abril'), (5, 'Mayo'), (6, 'Junio'),
             (7, 'Julio'), (8, 'Agosto'), (9, 'Septiembre'), (10, 'Octubre'), (11, 'Noviembre'), (12, 'Diciembre')]
    anios = list(range(2024, 2031))

    return render_template('finanzas.html', ingresos=ingresos, ganancia=ganancia, gastos=gastos,
        ganancia_yo=ganancia_yo, ganancia_novia=ganancia_novia, gastos_lista=gastos_lista,
        mes=int(mes), anio=int(anio), meses=meses, anios=anios)

@app.route('/finanzas/gasto/nuevo', methods=['POST'])
@login_required
def gasto_nuevo():
    db.session.add(GastoGeneral(
        descripcion=request.form['descripcion'], monto=float(request.form['monto']),
        categoria=request.form.get('categoria', 'otros'),
        fecha=datetime.strptime(request.form['fecha'], '%Y-%m-%d').date() if request.form.get('fecha') else date.today(),
        pagado_por=request.form.get('pagado_por', 'ambos')))
    db.session.commit()
    flash('Gasto registrado', 'success')
    return redirect(url_for('finanzas', mes=request.form.get('mes', date.today().month), anio=request.form.get('anio', date.today().year)))

@app.route('/finanzas/gasto/<int:id>/eliminar', methods=['POST'])
@login_required
def gasto_eliminar(id):
    gasto = GastoGeneral.query.get_or_404(id)
    mes, anio = gasto.fecha.month, gasto.fecha.year
    db.session.delete(gasto)
    db.session.commit()
    flash('Gasto eliminado', 'success')
    return redirect(url_for('finanzas', mes=mes, anio=anio))

@app.route('/deudas')
@login_required
def deudas():
    deudas_list = Deuda.query.order_by(Deuda.fecha.desc()).all()
    saldo_yo = db.session.query(db.func.sum(Deuda.monto)).filter(
        Deuda.estado == 'pendiente', Deuda.deudor == 'yo').scalar() or 0
    saldo_novia = db.session.query(db.func.sum(Deuda.monto)).filter(
        Deuda.estado == 'pendiente', Deuda.deudor == 'novia').scalar() or 0
    return render_template('deudas.html', deudas=deudas_list, saldo_yo=saldo_yo, saldo_novia=saldo_novia)

@app.route('/deudas/nueva', methods=['POST'])
@login_required
def deuda_nueva():
    db.session.add(Deuda(
        deudor=request.form['deudor'], acreedor=request.form['acreedor'],
        monto=float(request.form['monto']), motivo=request.form.get('motivo', ''),
        fecha=datetime.strptime(request.form['fecha'], '%Y-%m-%d').date() if request.form.get('fecha') else date.today()))
    db.session.commit()
    flash('Deuda registrada', 'success')
    return redirect(url_for('deudas'))

@app.route('/deudas/<int:id>/pagar', methods=['POST'])
@login_required
def deuda_pagar(id):
    deuda = Deuda.query.get_or_404(id)
    deuda.estado = 'pagada'
    deuda.fecha_pago = date.today()
    db.session.commit()
    flash('Deuda pagada', 'success')
    return redirect(url_for('deudas'))

@app.route('/deudas/<int:id>/eliminar', methods=['POST'])
@login_required
def deuda_eliminar(id):
    deuda = Deuda.query.get_or_404(id)
    db.session.delete(deuda)
    db.session.commit()
    flash('Deuda eliminada', 'success')
    return redirect(url_for('deudas'))

@app.route('/impresoras')
@login_required
def impresoras():
    return render_template('impresoras.html', impresoras=Impresora.query.all())

@app.route('/impresoras/nueva', methods=['POST'])
@login_required
def impresora_nueva():
    db.session.add(Impresora(nombre=request.form['nombre'], horas_diarias=float(request.form.get('horas_diarias', 24))))
    db.session.commit()
    flash('Impresora agregada', 'success')
    return redirect(url_for('impresoras'))

@app.route('/impresoras/<int:id>/editar', methods=['POST'])
@login_required
def impresora_editar(id):
    imp = Impresora.query.get_or_404(id)
    imp.nombre = request.form['nombre']
    imp.horas_diarias = float(request.form.get('horas_diarias', 24))
    imp.activa = 'activa' in request.form
    db.session.commit()
    flash('Impresora actualizada', 'success')
    return redirect(url_for('impresoras'))

@app.route('/impresoras/<int:id>/eliminar', methods=['POST'])
@login_required
def impresora_eliminar(id):
    db.session.delete(Impresora.query.get_or_404(id))
    db.session.commit()
    flash('Impresora eliminada', 'success')
    return redirect(url_for('impresoras'))

@app.route('/calendario')
@login_required
def calendario():
    semana_offset = int(request.args.get('semana', 0))
    inicio_semana = date.today() + timedelta(weeks=semana_offset)
    inicio_semana = inicio_semana - timedelta(days=inicio_semana.weekday())
    dias = [inicio_semana + timedelta(days=i) for i in range(7)]

    ocupacion = {}
    for dia in dias:
        ocupacion[dia] = {}
        for r in HoraPorFecha.query.filter_by(fecha=dia).all():
            ocupacion[dia][r.impresora_id] = r.horas_ocupadas

    entregas = {}
    for dia in dias:
        entregas[dia] = Pedido.query.filter_by(fecha_entrega=dia).filter(Pedido.estado != 'entregado').all()

    return render_template('calendario.html', dias=dias, ocupacion=ocupacion, entregas=entregas,
        impresoras=Impresora.query.filter_by(activa=True).all(), semana_offset=semana_offset)

@app.route('/exportar/pedidos/csv')
@login_required
def exportar_pedidos_csv():
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(['Cliente', 'Telefono', 'Modelo', 'Material', 'Color', 'Cantidad', 'Gramos',
                'Precio', 'Costo Mat.', 'Ganancia', 'Horas', 'Fecha Pedido', 'Fecha Entrega', 'Estado', 'Notas'])
    for p in Pedido.query.order_by(Pedido.fecha_entrega.desc()).all():
        w.writerow([p.cliente_nombre, p.cliente_telefono, p.modelo, p.material, p.color,
                    p.cantidad, p.gramos_totales, p.precio_total, p.costo_materiales,
                    p.ganancia, p.horas_impresion, formatear_fecha(p.fecha_pedido),
                    formatear_fecha(p.fecha_entrega), p.estado, p.notas])
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=pedidos_{hoy().strftime("%Y%m%d")}.csv'})

@app.route('/exportar/finanzas/csv')
@login_required
def exportar_finanzas_csv():
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(['Fecha', 'Descripcion', 'Categoria', 'Pagado Por', 'Monto'])
    for g in GastoGeneral.query.order_by(GastoGeneral.fecha.desc()).all():
        w.writerow([formatear_fecha(g.fecha), g.descripcion, g.categoria, g.pagado_por, g.monto])
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=finanzas_{hoy().strftime("%Y%m%d")}.csv'})

@app.route('/api/notificaciones')
def api_notificaciones():
    pedidos_hoy = Pedido.query.filter(Pedido.fecha_entrega == hoy(), Pedido.estado != 'entregado').count()
    pedidos_vencidos = Pedido.query.filter(Pedido.fecha_entrega < hoy(), Pedido.estado != 'entregado').count()
    filamento_bajo = Filamento.query.filter(Filamento.activo == True, Filamento.peso_restante <= Filamento.stock_alerta).count()
    tiene_algo = pedidos_hoy > 0 or pedidos_vencidos > 0 or filamento_bajo > 0
    return jsonify({
        'alerta': tiene_algo,
        'hoy': pedidos_hoy,
        'vencidos': pedidos_vencidos,
        'filamento_bajo': filamento_bajo
    })

@app.route('/api/estadisticas')
def api_estadisticas():
    labels, ingresos_data, gastos_data = [], [], []
    for i in range(5, -1, -1):
        m, a = date.today().month - i, date.today().year
        while m < 1: m += 12; a -= 1
        while m > 12: m -= 12; a += 1
        mes_str = f'{a}-{m:02d}'
        labels.append(f'{m}/{a}')
        ingresos_data.append(float(db.session.query(db.func.sum(Pedido.precio_total)).filter(
            Pedido.estado == 'entregado', db.func.strftime('%Y-%m', Pedido.fecha_entrega) == mes_str).scalar() or 0))
        gastos_data.append(float(db.session.query(db.func.sum(GastoGeneral.monto)).filter(
            ~GastoGeneral.categoria.in_(['ingreso_pedido', 'ganancia_pedido']),
            db.func.strftime('%Y-%m', GastoGeneral.fecha) == mes_str).scalar() or 0))
    return jsonify({'labels': labels, 'ingresos': ingresos_data, 'gastos': gastos_data})

@app.route('/galeria')
@login_required
def galeria():
    pedidos_con_foto = Pedido.query.filter(Pedido.foto != None, Pedido.foto != '').order_by(Pedido.created_at.desc()).all()
    return render_template('galeria.html', pedidos=pedidos_con_foto)

@app.route('/proveedores')
@login_required
def proveedores():
    return render_template('proveedores.html', proveedores=Proveedor.query.order_by(Proveedor.nombre).all())

@app.route('/proveedores/nuevo', methods=['GET', 'POST'])
@login_required
def proveedor_nuevo():
    if request.method == 'POST':
        db.session.add(Proveedor(
            nombre=request.form['nombre'], contacto=request.form.get('contacto', ''),
            telefono=request.form.get('telefono', ''), email=request.form.get('email', ''),
            direccion=request.form.get('direccion', ''), notas=request.form.get('notas', '')))
        db.session.commit()
        flash('Proveedor agregado', 'success')
        return redirect(url_for('proveedores'))
    return render_template('proveedor_form.html', proveedor=None)

@app.route('/proveedores/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def proveedor_editar(id):
    p = Proveedor.query.get_or_404(id)
    if request.method == 'POST':
        p.nombre = request.form['nombre']
        p.contacto = request.form.get('contacto', '')
        p.telefono = request.form.get('telefono', '')
        p.email = request.form.get('email', '')
        p.direccion = request.form.get('direccion', '')
        p.notas = request.form.get('notas', '')
        db.session.commit()
        flash('Proveedor actualizado', 'success')
        return redirect(url_for('proveedores'))
    return render_template('proveedor_form.html', proveedor=p)

@app.route('/proveedores/<int:id>/eliminar', methods=['POST'])
@login_required
def proveedor_eliminar(id):
    db.session.delete(Proveedor.query.get_or_404(id))
    db.session.commit()
    flash('Proveedor eliminado', 'success')
    return redirect(url_for('proveedores'))

@app.route('/mantenimiento')
@login_required
def mantenimiento():
    registros = Mantenimiento.query.order_by(Mantenimiento.fecha.desc()).all()
    return render_template('mantenimiento.html', registros=registros, impresoras=Impresora.query.all())

@app.route('/mantenimiento/nuevo', methods=['POST'])
@login_required
def mantenimiento_nuevo():
    db.session.add(Mantenimiento(
        impresora_id=request.form['impresora_id'], tipo=request.form['tipo'],
        descripcion=request.form.get('descripcion', ''),
        fecha=datetime.strptime(request.form['fecha'], '%Y-%m-%d').date() if request.form.get('fecha') else date.today(),
        fecha_proximo=datetime.strptime(request.form['fecha_proximo'], '%Y-%m-%d').date() if request.form.get('fecha_proximo') else None,
        costo=float(request.form.get('costo', 0))))
    db.session.commit()
    flash('Mantenimiento registrado', 'success')
    return redirect(url_for('mantenimiento'))

@app.route('/mantenimiento/<int:id>/eliminar', methods=['POST'])
@login_required
def mantenimiento_eliminar(id):
    db.session.delete(Mantenimiento.query.get_or_404(id))
    db.session.commit()
    flash('Registro eliminado', 'success')
    return redirect(url_for('mantenimiento'))

@app.route('/notas')
@login_required
def notas():
    notas_list = Nota.query.order_by(Nota.created_at.desc()).all()
    return render_template('notas.html', notas=notas_list)

@app.route('/notas/nueva', methods=['POST'])
@login_required
def nota_nueva():
    db.session.add(Nota(texto=request.form['texto'], usuario_id=session.get('user_id')))
    db.session.commit()
    return redirect(url_for('notas'))

@app.route('/notas/<int:id>/eliminar', methods=['POST'])
@login_required
def nota_eliminar(id):
    db.session.delete(Nota.query.get_or_404(id))
    db.session.commit()
    return redirect(url_for('notas'))

@app.route('/api/estadisticas_mensuales')
def api_estadisticas_mensuales():
    meses, ingresos_m, gastos_m, ganancias_m = [], [], [], []
    for i in range(11, -1, -1):
        m, a = date.today().month - i, date.today().year
        while m < 1: m += 12; a -= 1
        while m > 12: m -= 12; a += 1
        mes_str = f'{a}-{m:02d}'
        meses.append(f'{m}/{a}')
        ing = db.session.query(db.func.sum(Pedido.precio_total)).filter(
            Pedido.estado == 'entregado', db.func.strftime('%Y-%m', Pedido.fecha_entrega) == mes_str).scalar() or 0
        gas = db.session.query(db.func.sum(GastoGeneral.monto)).filter(
            ~GastoGeneral.categoria.in_(['ingreso_pedido', 'ganancia_pedido']),
            db.func.strftime('%Y-%m', GastoGeneral.fecha) == mes_str).scalar() or 0
        gan = db.session.query(db.func.sum(Pedido.ganancia)).filter(
            Pedido.estado == 'entregado', db.func.strftime('%Y-%m', Pedido.fecha_entrega) == mes_str).scalar() or 0
        ingresos_m.append(float(ing)); gastos_m.append(float(gas)); ganancias_m.append(float(gan))
    return jsonify({'labels': meses, 'ingresos': ingresos_m, 'gastos': gastos_m, 'ganancias': ganancias_m})

def enviar_email(asunto, cuerpo_html):
    conf = Configuracion.query.first()
    if not conf or not conf.smtp_user or not conf.smtp_pass or not conf.notify_email:
        return False
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = asunto
        msg['From'] = conf.smtp_from or conf.smtp_user
        msg['To'] = conf.notify_email
        msg.attach(MIMEText(cuerpo_html, 'html', 'utf-8'))
        with smtplib.SMTP(conf.smtp_server, conf.smtp_port) as s:
            s.starttls()
            s.login(conf.smtp_user, conf.smtp_pass)
            s.send_message(msg)
        return True
    except:
        return False

@app.route('/api/enviar-notificaciones')
def api_enviar_notificaciones():
    hoy_local = hoy()
    vencidos = Pedido.query.filter(Pedido.fecha_entrega < hoy_local, Pedido.estado != 'entregado').all()
    entregan_hoy = Pedido.query.filter(Pedido.fecha_entrega == hoy_local, Pedido.estado != 'entregado').all()
    filamento_bajo = Filamento.query.filter(Filamento.activo == True, Filamento.peso_restante <= Filamento.stock_alerta).all()
    partes = []
    if entregan_hoy:
        partes.append(f'<b>Entregan hoy ({len(entregan_hoy)}):</b><br>' + '<br>'.join(f'{p.cliente_nombre} - {p.modelo}' for p in entregan_hoy))
    if vencidos:
        partes.append(f'<b>Vencidos ({len(vencidos)}):</b><br>' + '<br>'.join(f'{p.cliente_nombre} - {p.modelo} ({formatear_fecha(p.fecha_entrega)})' for p in vencidos))
    if filamento_bajo:
        partes.append(f'<b>Filamento bajo stock ({len(filamento_bajo)}):</b><br>' + '<br>'.join(f'{f.tipo} {f.color} - {f.peso_restante:.0f}g' for f in filamento_bajo))
    if partes:
        enviado = enviar_email(f'Notificaciones - Gestion 3D ({hoy_local})', '<br><br>'.join(partes))
        return jsonify({'enviado': enviado, 'notificaciones': len(partes)})
    return jsonify({'enviado': False, 'notificaciones': 0})

@app.route('/configuracion', methods=['GET', 'POST'])
@login_required
def configuracion():
    conf = Configuracion.query.first()
    if not conf:
        conf = Configuracion(nombre_negocio='Cotef')
        db.session.add(conf)
        db.session.commit()
    if request.method == 'POST':
        conf.nombre_negocio = request.form['nombre_negocio']
        conf.google_client_id = request.form.get('google_client_id', '')
        conf.google_client_secret = request.form.get('google_client_secret', '')
        conf.smtp_server = request.form.get('smtp_server', 'smtp.gmail.com')
        conf.smtp_port = int(request.form.get('smtp_port', 587))
        conf.smtp_user = request.form.get('smtp_user', '')
        conf.smtp_pass = request.form.get('smtp_pass', '')
        conf.smtp_from = request.form.get('smtp_from', '')
        conf.notify_email = request.form.get('notify_email', '')
        conf.groq_api_key = request.form.get('groq_api_key', '')
        conf.groq_modelo = request.form.get('groq_modelo', 'llama-3.1-8b-instant')
        conf.whatsapp_token = request.form.get('whatsapp_token', '')
        conf.whatsapp_phone_id = request.form.get('whatsapp_phone_id', '')
        conf.whatsapp_verify_token = request.form.get('whatsapp_verify_token', 'MiTokenGestion3D2026')
        conf.whatsapp_bienvenida = request.form.get('whatsapp_bienvenida', '')
        logo = request.files.get('logo')
        if logo and logo.filename:
            if conf.logo:
                old_logo = os.path.join(app.config['UPLOAD_FOLDER'], conf.logo)
                if os.path.exists(old_logo): os.remove(old_logo)
            ext = logo.filename.rsplit('.', 1)[-1].lower() if '.' in logo.filename else 'png'
            filename = f"logo_{uuid.uuid4().hex}.{ext}"
            logo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            conf.logo = filename
        db.session.commit()
        flash('Configuracion guardada', 'success')
        return redirect(url_for('configuracion'))
    return render_template('configuracion.html', conf=conf)

@app.route('/reportes/ganancias')
@login_required
def reportes_ganancias():
    meses, datos = [], []
    for i in range(11, -1, -1):
        m, a = date.today().month - i, date.today().year
        while m < 1: m += 12; a -= 1
        while m > 12: m -= 12; a += 1
        mes_str = f'{a}-{m:02d}'
        ing = db.session.query(db.func.sum(Pedido.precio_total)).filter(
            Pedido.estado == 'entregado', db.func.strftime('%Y-%m', Pedido.fecha_entrega) == mes_str).scalar() or 0
        gas = db.session.query(db.func.sum(GastoGeneral.monto)).filter(
            ~GastoGeneral.categoria.in_(['ingreso_pedido', 'ganancia_pedido']),
            db.func.strftime('%Y-%m', GastoGeneral.fecha) == mes_str).scalar() or 0
        gan = db.session.query(db.func.sum(Pedido.ganancia)).filter(
            Pedido.estado == 'entregado', db.func.strftime('%Y-%m', Pedido.fecha_entrega) == mes_str).scalar() or 0
        months_es = ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
        meses.append(f'{months_es[m-1]} {a}')
        datos.append({'mes': f'{months_es[m-1]} {a}', 'ingresos': float(ing), 'gastos': float(gas), 'ganancia': float(gan)})
    for i in range(1, len(datos)):
        ant = datos[i-1]['ganancia']
        act = datos[i]['ganancia']
        datos[i]['crecimiento'] = round(((act - ant) / ant * 100) if ant > 0 else 0, 1)
    datos[0]['crecimiento'] = 0
    return render_template('reportes_ganancias.html', datos=datos, meses=meses)

@app.route('/api/top-clientes')
def api_top_clientes():
    resultados = db.session.query(
        Pedido.cliente_nombre,
        db.func.sum(Pedido.precio_total).label('total')
    ).filter(Pedido.estado == 'entregado').group_by(Pedido.cliente_nombre).order_by(db.func.sum(Pedido.precio_total).desc()).limit(5).all()
    return jsonify({
        'labels': [r.cliente_nombre for r in resultados],
        'data': [float(r.total) for r in resultados]
    })

@app.route('/api/material-uso')
def api_material_uso():
    resultados = db.session.query(
        Pedido.material,
        db.func.sum(Pedido.gramos_totales).label('gramos')
    ).filter(Pedido.material != '', Pedido.material.isnot(None)).group_by(Pedido.material).order_by(db.func.sum(Pedido.gramos_totales).desc()).all()
    return jsonify({
        'labels': [r.material for r in resultados],
        'data': [float(r.gramos) for r in resultados]
    })

# ==========================================================================
#  MÓDULO DE FERIAS  —  REST API v1  (consumido por la PWA / POS móvil)
# ==========================================================================

def _guardar_foto(archivo, subdir=''):
    """Guarda un archivo de imagen y devuelve el filename generado, o None."""
    if not archivo or not archivo.filename:
        return None
    ext = archivo.filename.rsplit('.', 1)[-1].lower() if '.' in archivo.filename else 'jpg'
    filename = f"{uuid.uuid4().hex}.{ext}"
    archivo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    return filename

@app.route('/api/v1/ferias', methods=['GET', 'POST'])
def api_ferias():
    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form
        nombre = (data.get('nombre') or '').strip()
        if not nombre:
            return jsonify({'ok': False, 'error': 'El nombre es obligatorio'}), 400
        fecha_str = data.get('fecha')
        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date() if fecha_str else date.today()
        except ValueError:
            fecha = date.today()
        feria = Feria(
            nombre=nombre,
            fecha=fecha,
            costo_stand=float(data.get('costo_stand') or 0),
            estado='Activa')
        db.session.add(feria)
        db.session.commit()
        return jsonify({'ok': True, 'feria': feria.to_dict()}), 201

    # GET -> listar todas
    estado = request.args.get('estado')
    query = Feria.query
    if estado:
        query = query.filter(Feria.estado == estado)
    ferias = query.order_by(Feria.fecha.desc(), Feria.id.desc()).all()
    return jsonify({'ok': True, 'ferias': [f.to_dict() for f in ferias]})

@app.route('/api/v1/ferias/<int:id>', methods=['GET'])
def api_feria_detalle(id):
    feria = Feria.query.get_or_404(id)
    data = feria.to_dict()
    data['inventario'] = [i.to_dict() for i in feria.inventario]
    data['ventas'] = [v.to_dict() for v in
                      sorted(feria.ventas, key=lambda v: v.fecha_hora or datetime.min, reverse=True)]
    return jsonify({'ok': True, 'feria': data})

@app.route('/api/v1/ferias/<int:id>/inventario', methods=['GET', 'POST'])
def api_feria_inventario(id):
    feria = Feria.query.get_or_404(id)
    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form
        nombre = (data.get('producto_nombre') or data.get('nombre') or '').strip()
        if not nombre:
            return jsonify({'ok': False, 'error': 'Falta el nombre del producto'}), 400
        item = FeriaInventario(
            feria_id=feria.id,
            producto_id=(int(data['producto_id']) if data.get('producto_id') else None),
            producto_nombre=nombre,
            cantidad_llevada=int(data.get('cantidad_llevada') or 0),
            precio_unitario=float(data.get('precio_unitario') or 0),
            costo_unitario=float(data.get('costo_unitario') or 0))
        db.session.add(item)
        db.session.commit()
        return jsonify({'ok': True, 'item': item.to_dict()}), 201

    return jsonify({'ok': True, 'inventario': [i.to_dict() for i in feria.inventario]})

@app.route('/api/v1/ferias/<int:id>/venta-rapida', methods=['POST'])
def api_feria_venta_rapida(id):
    """Registra una venta instantánea (1 toque). +cantidad, recalcula total_recaudado."""
    feria = Feria.query.get_or_404(id)
    if feria.estado != 'Activa':
        return jsonify({'ok': False, 'error': 'La feria está finalizada'}), 400

    data = request.get_json(silent=True) or request.form
    cantidad = max(1, int(data.get('cantidad') or 1))

    item = None
    if data.get('inventario_id'):
        item = FeriaInventario.query.filter_by(id=int(data['inventario_id']), feria_id=feria.id).first()
        if not item:
            return jsonify({'ok': False, 'error': 'Producto no encontrado en la feria'}), 404
        precio_unit = item.precio_unitario
        nombre = item.producto_nombre
    else:
        nombre = (data.get('producto_nombre') or '').strip()
        precio_unit = float(data.get('precio_unitario') or data.get('precio') or 0)
        if not nombre:
            return jsonify({'ok': False, 'error': 'Falta producto o inventario_id'}), 400

    precio_total = round(precio_unit * cantidad, 2)

    venta = FeriaVenta(
        feria_id=feria.id,
        inventario_id=item.id if item else None,
        producto_nombre=nombre,
        cantidad=cantidad,
        precio_total=precio_total)
    db.session.add(venta)

    if item:
        item.cantidad_vendida += cantidad
    feria.total_recaudado = round((feria.total_recaudado or 0) + precio_total, 2)
    db.session.commit()

    return jsonify({
        'ok': True,
        'venta': venta.to_dict(),
        'item': item.to_dict() if item else None,
        'total_recaudado': feria.total_recaudado,
        'unidades_vendidas': feria.unidades_vendidas,
    })

@app.route('/api/v1/ferias/<int:id>/cerrar', methods=['POST'])
def api_feria_cerrar(id):
    """Cierra la feria: balance, ganancia neta y devuelve el stock no vendido."""
    feria = Feria.query.get_or_404(id)
    if feria.estado == 'Finalizada':
        return jsonify({'ok': False, 'error': 'La feria ya está finalizada'}), 400

    costo_mercaderia = feria.costo_mercaderia
    ganancia_neta = round((feria.total_recaudado or 0) - (feria.costo_stand or 0) - costo_mercaderia, 2)

    # Stock no vendido -> retorna al inventario general (se reporta el detalle devuelto)
    stock_devuelto = []
    for i in feria.inventario:
        if i.cantidad_restante > 0:
            stock_devuelto.append({
                'producto_id': i.producto_id,
                'producto_nombre': i.producto_nombre,
                'cantidad_devuelta': i.cantidad_restante,
            })

    feria.estado = 'Finalizada'
    feria.ganancia_neta = ganancia_neta
    feria.fecha_cierre = datetime.now()
    db.session.commit()

    return jsonify({
        'ok': True,
        'feria': feria.to_dict(),
        'balance': {
            'total_recaudado': round(feria.total_recaudado or 0, 2),
            'costo_stand': round(feria.costo_stand or 0, 2),
            'costo_mercaderia': round(costo_mercaderia, 2),
            'ganancia_neta': ganancia_neta,
        },
        'stock_devuelto': stock_devuelto,
    })

@app.route('/api/v1/pedidos/<int:id>/foto', methods=['POST'])
def api_pedido_foto(id):
    """Sube/actualiza la foto del resultado final de un pedido (cámara del celular)."""
    pedido = Pedido.query.get_or_404(id)
    foto = request.files.get('foto') or request.files.get('file') or request.files.get('image')
    if not foto or not foto.filename:
        return jsonify({'ok': False, 'error': 'No se recibió ninguna imagen'}), 400
    # Borrar la foto anterior si existía
    if pedido.foto:
        old = os.path.join(app.config['UPLOAD_FOLDER'], pedido.foto)
        if os.path.exists(old):
            os.remove(old)
    pedido.foto = _guardar_foto(foto)
    db.session.commit()
    return jsonify({
        'ok': True,
        'foto': pedido.foto,
        'url': url_for('uploaded_file', filename=pedido.foto),
    })

@app.route('/api/v1/monitor')
def api_monitor():
    """Estado de impresión + alertas para el Service Worker (timers y stock bajo)."""
    activos = Pedido.query.filter(Pedido.estado.in_(['en_impresion', 'pendiente'])).all()
    pedidos = []
    for p in activos:
        pedidos.append({
            'id': p.id,
            'modelo': p.modelo,
            'cliente': p.cliente_nombre,
            'estado': p.estado,
            'horas_impresion': p.horas_impresion or 0,
            'impresora': p.impresora.nombre if p.impresora else None,
        })
    filamento_bajo = [
        {'id': f.id, 'tipo': f.tipo, 'color': f.color, 'peso_restante': round(f.peso_restante, 0)}
        for f in Filamento.query.filter(Filamento.activo == True, Filamento.peso_restante < 100).all()
    ]
    return jsonify({'ok': True, 'pedidos': pedidos, 'filamento_bajo': filamento_bajo})

# ==========================================================================
#  Servir la PWA local (public/) — en Vercel se sirve estático desde /public
# ==========================================================================

@app.route('/app')
@app.route('/app/')
def pwa_index():
    return send_from_directory(PUBLIC_FOLDER, 'index.html')

@app.route('/app/<path:filename>')
def pwa_static(filename):
    return send_from_directory(PUBLIC_FOLDER, filename)

if __name__ == '__main__':
    app.run(debug=False, host='127.0.0.1', port=5005)
