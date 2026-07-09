"""Adaptador MQTT (entrada y salida) con paho puro.

Antes usábamos Flask-MQTT, pero bajo gunicorn su hilo de red moría en
silencio dejando `connected=True` obsoleto: los publish devolvían rc=0
y se encolaban hacia la nada. Este adaptador maneja el ciclo de vida a
mano.

Dos problemas de fondo, ya resueltos aquí:

1. *Fork de gunicorn*: si el hilo de red arranca en el proceso maestro
   (import) y gunicorn hace fork, el worker hereda un cliente con el flag
   `connected` en True pero SIN el hilo que atiende la red — publish sin
   PUBACK, mensajes entrantes perdidos. Lo evitamos anclando el arranque
   al PID vivo (`_pid`): si detectamos que forkeamos, recreamos cliente e
   hilo dentro del worker. El arranque es perezoso vía `asegurar_mqtt()`,
   que el watchdog de la app llama en cada request (idempotente y barato).

2. *Hilo muerto*: `_bucle_red` reintenta eternamente y el watchdog lo
   revive si `is_alive()` es False. `conectado()` refleja la realidad
   (cliente + hilo vivo), no un flag heredado.

Los callbacks corren en el hilo de paho, FUERA del contexto de la
aplicación, por eso guardamos la app y usamos `with _app.app_context()`.
"""
import json
import os
import threading
import time

import paho.mqtt.client as paho

from extensions import socketio

_app = None
_cliente: paho.Client | None = None
_hilo_red: threading.Thread | None = None
_pid: int | None = None          # PID donde arrancó el hilo (guard anti-fork)
_ultimo_latido: float = 0.0      # monotonic del último evento de red
_lock = threading.Lock()


def init_mqtt(app):
    """Registra la app. NO conecta todavía: el arranque real es perezoso
    (`asegurar_mqtt`) para que ocurra dentro del worker de gunicorn y no
    en el proceso maestro (ver módulo)."""
    global _app
    _app = app


def asegurar_mqtt():
    """Arranca (o revive) el hilo de red MQTT. Idempotente y fork-safe.

    Lo llama el watchdog de la app en cada request: si el hilo no existe,
    murió, o venimos de un fork (PID distinto), recrea cliente e hilo."""
    global _cliente, _hilo_red, _pid
    if _app is None:
        return
    pid = os.getpid()
    if _hilo_red is not None and _hilo_red.is_alive() and _pid == pid:
        return
    with _lock:
        pid = os.getpid()
        if _hilo_red is not None and _hilo_red.is_alive() and _pid == pid:
            return
        _cliente = paho.Client(
            client_id=_app.config["MQTT_CLIENT_ID"], clean_session=True)
        _cliente.on_connect = _al_conectar
        _cliente.on_message = _al_mensaje
        _pid = pid
        _hilo_red = threading.Thread(
            target=_bucle_red, name="mqtt-bucle", daemon=True)
        _hilo_red.start()


def _bucle_red():
    """Conecta y atiende la red. Si el broker echa la conexión, el DNS
    falla o hay cualquier excepción, espera 5 s y vuelve a intentar:
    este hilo no muere nunca (y aparece como 'mqtt-bucle' en /salud).
    Se detiene solo si el proceso forkeó (otro hilo tomará el relevo)."""
    global _ultimo_latido
    cliente = _cliente
    while _pid == os.getpid():
        try:
            _ultimo_latido = time.monotonic()
            cliente.connect(
                _app.config["MQTT_BROKER_URL"],
                _app.config["MQTT_BROKER_PORT"],
                keepalive=60,
            )
            cliente.loop_forever()   # reconexiones internas incluidas
        except Exception as exc:
            _app.logger.warning("MQTT sin conexión (%s); reintento en 5 s", exc)
        time.sleep(5)


def conectado() -> bool:
    """True solo si hay cliente conectado Y el hilo de red está vivo en
    este proceso (no un flag heredado de un fork)."""
    return (_cliente is not None and _cliente.is_connected()
            and _hilo_red is not None and _hilo_red.is_alive()
            and _pid == os.getpid())


def latido_hace() -> float | None:
    """Segundos desde el último evento de red (None si nunca arrancó)."""
    if not _ultimo_latido:
        return None
    return round(time.monotonic() - _ultimo_latido, 1)


def publicar(subtopico: str, payload: dict, timeout: float = 5.0) -> bool:
    """Publica con QoS 1 y espera la confirmación del broker.

    Devuelve False si el cliente está desconectado o el broker no
    confirma a tiempo. Con timeout=0 publica sin esperar (best-effort:
    espejo hacia el ESP32 real cuando el simulador ya atendió el comando)."""
    if _cliente is None:
        return False
    topico = f"{_app.config['TOPIC_BASE']}/{subtopico}"
    info = _cliente.publish(topico, json.dumps(payload), qos=1)
    if info.rc != paho.MQTT_ERR_SUCCESS:
        _app.logger.warning("publish en %s falló de inmediato (rc=%s)", topico, info.rc)
        return False
    if timeout <= 0:
        return True
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
    global _ultimo_latido
    _ultimo_latido = time.monotonic()
    base = _app.config["TOPIC_BASE"]
    client.subscribe(f"{base}/#", qos=1)
    _app.logger.info("MQTT conectado (rc=%s), suscrito a %s/#", rc, base)


def _al_mensaje(client, userdata, message):
    global _ultimo_latido
    _ultimo_latido = time.monotonic()
    subtopico = message.topic.rsplit("/", 1)[-1]
    try:
        datos = json.loads(message.payload.decode())
    except (ValueError, UnicodeDecodeError):
        _app.logger.warning("Payload MQTT inválido en %s", message.topic)
        return
    despachar(subtopico, datos)


# --------------------------------------------------------------------------
# Despacho de telemetría (compartido por MQTT y por el simulador embebido)
# --------------------------------------------------------------------------

def despachar(subtopico: str, datos: dict):
    """Enruta un mensaje de telemetría al handler que corresponda.

    Es el ÚNICO camino de datos hacia el panel: tanto el ESP32 real (vía
    `_al_mensaje`) como el simulador embebido llaman aquí, de modo que el
    panel se comporta idéntico venga de donde venga la telemetría.

    OJO: una excepción aquí muere silenciosa en el hilo que llama, por eso
    todo va dentro de try/except con log."""
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
        _app.logger.exception("Error procesando telemetría %s", subtopico)


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
