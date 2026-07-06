"""Adaptador MQTT (entrada y salida) con paho puro.

Antes usábamos Flask-MQTT, pero bajo gunicorn su hilo de red moría en
silencio dejando `connected=True` obsoleto: los publish devolvían rc=0
y se encolaban hacia la nada. Este adaptador maneja el ciclo de vida a
mano: un hilo propio con loop_forever y reintento eterno, y publish
con confirmación real del broker (wait_for_publish, QoS 1).

Los callbacks corren en el hilo de paho, FUERA del contexto de la
aplicación, por eso guardamos la app y usamos `with _app.app_context()`.
"""
import json
import threading
import time

import paho.mqtt.client as paho

from extensions import socketio

_app = None
_cliente: paho.Client | None = None


def init_mqtt(app):
    """Crea el cliente y arranca el hilo de red (no bloquea el arranque)."""
    global _app, _cliente
    _app = app
    _cliente = paho.Client(client_id=app.config["MQTT_CLIENT_ID"], clean_session=True)
    _cliente.on_connect = _al_conectar
    _cliente.on_message = _al_mensaje
    threading.Thread(target=_bucle_red, name="mqtt-bucle", daemon=True).start()


def _bucle_red():
    """Conecta y atiende la red. Si el broker echa la conexión, el DNS
    falla o hay cualquier excepción, espera 5 s y vuelve a intentar:
    este hilo no muere nunca (y aparece como 'mqtt-bucle' en /salud)."""
    while True:
        try:
            _cliente.connect(
                _app.config["MQTT_BROKER_URL"],
                _app.config["MQTT_BROKER_PORT"],
                keepalive=60,
            )
            _cliente.loop_forever()   # reconexiones internas incluidas
        except Exception as exc:
            _app.logger.warning("MQTT sin conexión (%s); reintento en 5 s", exc)
        time.sleep(5)


def conectado() -> bool:
    return _cliente is not None and _cliente.is_connected()


def publicar(subtopico: str, payload: dict, timeout: float = 5.0) -> bool:
    """Publica con QoS 1 y espera la confirmación del broker.

    Devuelve False si el cliente está desconectado o el broker no
    confirma a tiempo — el llamador decide qué mostrarle al usuario."""
    if _cliente is None:
        return False
    topico = f"{_app.config['TOPIC_BASE']}/{subtopico}"
    info = _cliente.publish(topico, json.dumps(payload), qos=1)
    if info.rc != paho.MQTT_ERR_SUCCESS:
        _app.logger.warning("publish en %s falló de inmediato (rc=%s)", topico, info.rc)
        return False
    try:
        info.wait_for_publish(timeout=timeout)
    except Exception:
        pass
    if not info.is_published():
        _app.logger.warning("publish en %s sin confirmación del broker", topico)
        return False
    _app.logger.info("cmd publicado en %s: %s", topico, payload)
    return True


def _al_conectar(client, userdata, flags, rc):
    base = _app.config["TOPIC_BASE"]
    client.subscribe(f"{base}/#", qos=1)
    _app.logger.info("MQTT conectado (rc=%s), suscrito a %s/#", rc, base)


def _al_mensaje(client, userdata, message):
    # OJO: una excepción aquí muere silenciosa en el hilo de paho,
    # por eso todo el despacho va dentro de try/except con log.
    subtopico = message.topic.rsplit("/", 1)[-1]
    try:
        datos = json.loads(message.payload.decode())
    except (ValueError, UnicodeDecodeError):
        _app.logger.warning("Payload MQTT inválido en %s", message.topic)
        return
    try:
        if subtopico == "peso":
            _manejar_peso(datos)
        elif subtopico == "estado":
            _manejar_estado(datos)
        elif subtopico == "unidad":
            _manejar_unidad(datos)
        elif subtopico == "alarma":
            _manejar_alarma(datos)
        # 'cmd' y 'diag' los publica el propio backend: se ignoran aquí
    except Exception:
        _app.logger.exception("Error procesando %s", message.topic)


# --------------------------------------------------------------------------
# Handlers por tópico
# --------------------------------------------------------------------------

def _manejar_peso(datos: dict):
    """{"g": 12.4, "ts": 123} -> solo se reemite al navegador, NO se persiste."""
    socketio.emit("peso", {"g": datos.get("g"), "ts": datos.get("ts")})


def _manejar_estado(datos: dict):
    """{"fsm": "DOSIFICANDO", "unidad": 12, "lote": "L-0001"} -> reemitir."""
    socketio.emit("estado", datos)


def _manejar_unidad(datos: dict):
    """{"lote": "L-0001", "n": 12, "peso": 25.3, "ok": true} -> persistir."""
    from adaptadores import repositorio  # import tardío para evitar ciclos

    with _app.app_context():
        resumen = repositorio.registrar_unidad(
            numero_lote=datos.get("lote", ""),
            peso_real=float(datos.get("peso", 0)),
            ok=bool(datos.get("ok", False)),
        )
    if resumen is None:
        _app.logger.warning("Unidad recibida para lote desconocido: %s", datos)
        return
    resumen["n"] = datos.get("n")
    socketio.emit("unidad", resumen)
    if resumen["completado"]:
        socketio.emit("lote_completado", {"lote": resumen["lote"]})


def _manejar_alarma(datos: dict):
    """{"tipo": "FUERA_TOLERANCIA", "peso": 26.4} -> reemitir al panel."""
    socketio.emit("alarma", datos)
