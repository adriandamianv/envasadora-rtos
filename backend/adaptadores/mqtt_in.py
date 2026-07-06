"""Adaptador de entrada MQTT.

Se suscribe a envasadora/ENV01/# y despacha cada tópico a su handler.
Los callbacks de Flask-MQTT corren en el hilo de paho, FUERA del
contexto de la aplicación, por eso guardamos una referencia global a
la app y usamos `with _app.app_context():` cuando tocamos la base.
"""
import json

from extensions import mqtt, socketio

_app = None  # referencia global a la app (patrón init_mqtt(app))


def init_mqtt(app):
    """Registra los callbacks y arranca la conexión MQTT."""
    global _app
    _app = app

    @mqtt.on_connect()
    def al_conectar(client, userdata, flags, rc):
        base = _app.config["TOPIC_BASE"]
        mqtt.subscribe(f"{base}/#")
        _app.logger.info("MQTT conectado (rc=%s), suscrito a %s/#", rc, base)

    @mqtt.on_message()
    def al_mensaje(client, userdata, message):
        # OJO: una excepción aquí muere silenciosa en el hilo de paho,
        # por eso todo el despacho va dentro de try/except con log.
        subtopico = message.topic.rsplit("/", 1)[-1]
        _app.logger.debug("MQTT %s: %s", message.topic, message.payload[:120])
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
            # el tópico 'cmd' lo publica el propio backend: se ignora aquí
        except Exception:
            _app.logger.exception("Error procesando %s", message.topic)

    # La conexión es asíncrona (MQTT_CONNECT_ASYNC): si el broker no
    # responde, paho reintenta en segundo plano y la app sigue viva.
    try:
        mqtt.init_app(app)
    except Exception as exc:  # sin red, DNS caído, etc.
        app.logger.warning("MQTT no disponible al arrancar: %s", exc)


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
