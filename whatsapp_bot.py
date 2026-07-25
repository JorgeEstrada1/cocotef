import os, sys, json, logging
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, PlainTextResponse
from pydantic import BaseModel
from groq import Groq
import requests
import agente_ventas

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("whatsapp_bot")

app = FastAPI(title="Asistente WhatsApp - Gestion 3D")

clientes_chat = {}

def get_groq_client():
    cfg = agente_ventas.get_config()
    api_key = cfg.get('groq_api_key', '')
    if not api_key:
        raise HTTPException(status_code=500, detail="Groq API Key no configurada")
    return Groq(api_key=api_key)

def get_modelo():
    cfg = agente_ventas.get_config()
    return cfg.get('groq_modelo', 'llama-3.1-8b-instant')

def get_nombre_negocio():
    cfg = agente_ventas.get_config()
    return cfg.get('nombre_negocio', 'Cotef')

def enviar_whatsapp(telefono, texto):
    cfg = agente_ventas.get_config()
    token = cfg.get('whatsapp_token', '')
    phone_id = cfg.get('whatsapp_phone_id', '')
    if not token or not phone_id:
        log.warning("WhatsApp no configurado - token/phone_id faltantes")
        return False
    url = f"https://graph.facebook.com/v25.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": telefono,
        "type": "text",
        "text": {"preview_url": False, "body": texto}
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        if r.status_code == 200:
            log.info(f"Mensaje enviado a {telefono}")
            return True
        else:
            log.error(f"Error Meta API: {r.status_code} - {r.text}")
            return False
    except Exception as e:
        log.error(f"Error al enviar WhatsApp: {e}")
        return False

def procesar_con_groq(telefono, texto_usuario):
    cliente = get_groq_client()
    modelo = get_modelo()
    nombre_negocio = get_nombre_negocio()

    if telefono not in clientes_chat:
        cfg = agente_ventas.get_config()
        bienvenida = cfg.get('whatsapp_bienvenida', 'Hola! Soy el asistente virtual.').replace('{nombre_negocio}', nombre_negocio)
        system_prompt = agente_ventas.PROMPT_SISTEMA.format(nombre_negocio=nombre_negocio)
        clientes_chat[telefono] = [
            {"role": "system", "content": system_prompt},
            {"role": "assistant", "content": bienvenida}
        ]
        enviar_whatsapp(telefono, bienvenida)
        return

    messages = clientes_chat[telefono]
    messages.append({"role": "user", "content": texto_usuario})

    try:
        response = cliente.chat.completions.create(
            model=modelo,
            messages=messages,
            tools=agente_ventas.FUNCIONES_DISPONIBLES,
            tool_choice="auto",
            temperature=0.2
        )

        msg = response.choices[0].message

        if msg.tool_calls:
            messages.append(msg)
            for tc in msg.tool_calls:
                nombre_func = tc.function.name
                args = json.loads(tc.function.arguments)
                log.info(f"Ejecutando: {nombre_func}({args})")
                if nombre_func in agente_ventas.FUNCIONES_MAP:
                    try:
                        resultado = agente_ventas.FUNCIONES_MAP[nombre_func](**args)
                    except Exception as e:
                        resultado = f"Error al ejecutar {nombre_func}: {e}"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": str(resultado)
                    })

            segunda_resp = cliente.chat.completions.create(
                model=modelo,
                messages=messages,
                temperature=0.2
            )
            texto_final = segunda_resp.choices[0].message.content
        else:
            texto_final = msg.content

        if not texto_final:
            texto_final = "Disculpa, no pude procesar tu consulta. Un asesor te ayudara pronto."

        messages.append({"role": "assistant", "content": texto_final})
        if len(messages) > 20:
            clientes_chat[telefono] = [messages[0]] + messages[-18:]

        enviar_whatsapp(telefono, texto_final)

    except Exception as e:
        log.error(f"Error en Groq: {e}")
        enviar_whatsapp(telefono, "Disculpa, tengo un problema tecnico. Un asesor humano te respondera pronto.")

@app.on_event("startup")
def startup():
    agente_ventas.recargar_config()
    log.info("WhatsApp Bot iniciado")

@app.get("/whatsapp")
async def verificar_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    cfg = agente_ventas.get_config()
    expected_token = cfg.get('whatsapp_verify_token', 'MiTokenGestion3D2026')
    if mode == "subscribe" and token == expected_token:
        return PlainTextResponse(content=challenge)
    raise HTTPException(status_code=403, detail="Token de verificacion invalido")

@app.post("/whatsapp")
async def recibir_mensaje(request: Request):
    try:
        body = await request.json()
        cambios = body["entry"][0]["changes"][0]["value"]
        if "messages" in cambios:
            mensaje = cambios["messages"][0]
            telefono = str(mensaje["from"]).strip()
            texto = mensaje["text"]["body"]
            log.info(f"Mensaje de {telefono}: {texto}")
            procesar_con_groq(telefono, texto)
        return {"status": "ok"}
    except Exception as e:
        log.error(f"Error en webhook: {e}")
        return {"status": "error"}

@app.post("/api/reload-config")
def reload_config():
    agente_ventas.recargar_config()
    return {"status": "ok", "config_cargada": True}

@app.get("/api/status")
def status():
    cfg = agente_ventas.get_config()
    return {
        "nombre_negocio": cfg.get('nombre_negocio', ''),
        "groq_configurado": bool(cfg.get('groq_api_key')),
        "whatsapp_configurado": bool(cfg.get('whatsapp_token') and cfg.get('whatsapp_phone_id')),
        "chat_activos": len(clientes_chat)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)