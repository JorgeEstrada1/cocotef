import os, sys, sqlite3
from datetime import date, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, 'gestion3d.db')

CONFIG_CACHE = {}

def recargar_config():
    global CONFIG_CACHE
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM configuracion WHERE id = 1").fetchone()
        conn.close()
        if row:
            CONFIG_CACHE = dict(row)
        return CONFIG_CACHE
    except:
        return {}

def get_config():
    if not CONFIG_CACHE:
        recargar_config()
    return CONFIG_CACHE

def consultar_precios(query_texto: str) -> str:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    pedidos = conn.execute(
        "SELECT DISTINCT modelo, material, precio_total, gramos_totales FROM pedidos WHERE modelo LIKE ? ORDER BY fecha_pedido DESC LIMIT 5",
        (f'%{query_texto}%',)
    ).fetchall()

    resultado = []
    for p in pedidos:
        resultado.append(f"  - {p['modelo']} ({p['material']}): Bs {p['precio_total']:.0f}, {p['gramos_totales']:.0f}g")
    conn.close()

    if resultado:
        return "Pedidos similares encontrados:\n" + "\n".join(resultado)
    return "No se encontraron pedidos previos similares. Los precios base son: Figuras personalizadas desde 180 BS, dioramas complejos 250-400 BS."

def consultar_stock(tipo: str = "", color: str = "") -> str:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    query = "SELECT * FROM filamentos WHERE activo = 1"
    params = []
    if tipo:
        query += " AND tipo LIKE ?"
        params.append(f'%{tipo}%')
    if color:
        query += " AND color LIKE ?"
        params.append(f'%{color}%')
    filamentos = conn.execute(query, params).fetchall()
    conn.close()

    if not filamentos:
        return "No hay filamentos disponibles con esos criterios."
    partes = ["Filamentos disponibles:"]
    for f in filamentos:
        estado = "ALERTA" if f['peso_restante'] <= f['stock_alerta'] else "OK"
        partes.append(f"  - {f['tipo']} {f['color']} ({f['marca']}): {f['peso_restante']:.0f}g restantes [{estado}]")
    return "\n".join(partes)

def buscar_cliente(telefono: str) -> str:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    pedidos = conn.execute(
        "SELECT * FROM pedidos WHERE cliente_telefono LIKE ? ORDER BY fecha_pedido DESC",
        (f'%{telefono}%',)
    ).fetchall()
    conn.close()

    if not pedidos:
        return "Cliente no encontrado en la base de datos."
    p = pedidos[0]
    total_gastado = sum(x['precio_total'] for x in pedidos)
    partes = [
        f"Cliente: {p['cliente_nombre']}",
        f"Telefono: {p['cliente_telefono']}",
        f"Total pedidos: {len(pedidos)}",
        f"Total gastado: Bs {total_gastado:.0f}",
        f"Ultimo pedido: {p['modelo']} ({p['estado']})"
    ]
    return "\n".join(partes)

def crear_pedido(cliente_nombre: str, cliente_telefono: str, modelo: str, material: str, color: str, cantidad: int, precio_total: float, gramos_totales: float = 0, notas: str = "") -> str:
    conn = sqlite3.connect(DB_PATH)
    hoy = date.today().isoformat()
    conn.execute(
        """INSERT INTO pedidos
        (cliente_nombre, cliente_telefono, modelo, material, color, cantidad, gramos_totales, precio_total, fecha_pedido, estado, notas)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pendiente', ?)""",
        (cliente_nombre, cliente_telefono, modelo, material, color, cantidad, gramos_totales, precio_total, hoy, notas)
    )
    conn.commit()
    pedido_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return f"Pedido #{pedido_id} creado exitosamente para {cliente_nombre}: {modelo} - Bs {precio_total:.2f}"

def consultar_disponibilidad(fecha: str = "") -> str:
    if not fecha:
        fecha = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    impresoras = conn.execute("SELECT * FROM impresoras WHERE activa = 1").fetchall()
    ocupacion = conn.execute("SELECT * FROM horas_por_fecha WHERE fecha = ?", (fecha,)).fetchall()
    conn.close()
    ocup_map = {o['impresora_id']: o['horas_ocupadas'] for o in ocupacion}
    partes = [f"Disponibilidad para {fecha}:"]
    for imp in impresoras:
        ocup = ocup_map.get(imp['id'], 0)
        libres = imp['horas_diarias'] - ocup
        partes.append(f"  - {imp['nombre']}: {ocup:.0f}h ocupadas, {libres:.0f}h libres")
    return "\n".join(partes)

PROMPT_SISTEMA = """
Eres el asistente virtual de ventas de {nombre_negocio}, una empresa de impresion 3D personalizada.
Tu tono debe ser amable, entusiasta y conciso.

REGLAS:
1. Saluda al cliente y presentate brevemente.
2. Usa las funciones disponibles para consultar precios, stock y clientes.
3. Si el cliente quiere comprar, pedile: nombre, telefono, modelo, material, color y cantidad.
4. Antes de crear un pedido, confirma todos los datos con el cliente.
5. No inventes precios ni existencias. Si no tenes data exacta, decilo y ofrecelo derivar a un asesor.
6. Habla en Bolivianos (BS) cuando te refieras a dinero.
7. Si el cliente ya compro antes, reconocelo y ofrecele descuentos por recurrencia si aplica.
"""

FUNCIONES_DISPONIBLES = [
    {
        "type": "function",
        "function": {
            "name": "consultar_precios",
            "description": "Busca pedidos anteriores similares para estimar precios",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_texto": {"type": "string", "description": "Modelo o tipo de figura a buscar"}
                },
                "required": ["query_texto"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_stock",
            "description": "Consulta el stock de filamentos disponibles",
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "description": "Tipo de filamento (PLA, ABS, etc)"},
                    "color": {"type": "string", "description": "Color del filamento"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_cliente",
            "description": "Busca un cliente por telefono para ver su historial",
            "parameters": {
                "type": "object",
                "properties": {
                    "telefono": {"type": "string", "description": "Numero de telefono del cliente"}
                },
                "required": ["telefono"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "crear_pedido",
            "description": "Crea un nuevo pedido en el sistema",
            "parameters": {
                "type": "object",
                "properties": {
                    "cliente_nombre": {"type": "string", "description": "Nombre del cliente"},
                    "cliente_telefono": {"type": "string", "description": "Telefono del cliente"},
                    "modelo": {"type": "string", "description": "Nombre del modelo/fiqura"},
                    "material": {"type": "string", "description": "Tipo de material"},
                    "color": {"type": "string", "description": "Color"},
                    "cantidad": {"type": "integer", "description": "Cantidad de unidades"},
                    "precio_total": {"type": "number", "description": "Precio total en BS"},
                    "gramos_totales": {"type": "number", "description": "Gramos totales estimados"},
                    "notas": {"type": "string", "description": "Notas adicionales del pedido"}
                },
                "required": ["cliente_nombre", "cliente_telefono", "modelo", "material", "color", "cantidad", "precio_total"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_disponibilidad",
            "description": "Consulta horas disponibles de impresion para una fecha",
            "parameters": {
                "type": "object",
                "properties": {
                    "fecha": {"type": "string", "description": "Fecha en formato YYYY-MM-DD"}
                }
            }
        }
    }
]

FUNCIONES_MAP = {
    "consultar_precios": consultar_precios,
    "consultar_stock": consultar_stock,
    "buscar_cliente": buscar_cliente,
    "crear_pedido": crear_pedido,
    "consultar_disponibilidad": consultar_disponibilidad,
}