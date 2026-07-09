"""Simulador embebido de la envasadora (ESP32/FreeRTOS emulado en proceso).

Por qué existe
--------------
El panel se alimenta de telemetría MQTT que publica el ESP32 corriendo en
Wokwi (una pestaña del navegador). En Render no hay quien corra Wokwi: sin
esa pestaña abierta el panel queda "muerto". Este módulo replica la FSM del
firmware DENTRO del backend, en un hilo supervisado, de modo que Render sea
autónomo: peso, estado, unidades y alarmas viven aunque nadie tenga Wokwi.

Fidelidad
---------
La FSM (ESPERA→DOSIFICANDO→ASENTANDO→VALIDANDO→DESCARGA) y el modelo físico
del peso son un port directo de `firmware/src/main.cpp` (modo demo). La
telemetría NO toma un atajo: sale por `mqtt_in.despachar(...)`, el mismo
camino que usa el ESP32 real, así el panel se comporta idéntico.

Robustez
--------
Hilo daemon anclado al PID (`_pid`): si gunicorn forkea, el watchdog de la
app lo revive dentro del worker (ver `asegurar_simulador`). No muere nunca.

Se activa con SIMULADOR_AUTONOMO=1 (default en la demo de Render). Con la
variable en 0 el backend solo escucha al ESP32 real por MQTT.
"""
import os
import random
import threading
import time

from dominio import reglas

# --- parámetros de proceso (port de firmware/src/main.cpp) -----------------
_FLUJO_G_S = 12.0          # caudal de la válvula
_ANTICIPO_G = 0.8          # cierre anticipado por producto en vuelo
_MS_ASENTAR = 0.4          # espera a que el peso se asiente (s)
_MS_DESCARGA = 0.5         # cambio de funda (s)
_DT = 0.1                  # periodo del lazo (s) -> 10 Hz
_PERIODO_PESO = 0.5        # telemetría de peso a 2 Hz (s)

_app = None
_hilo: threading.Thread | None = None
_pid: int | None = None
_ultimo_latido: float = 0.0
_lock = threading.Lock()
_cola_cmd: "list[dict]" = []       # comandos pendientes (protegida por _lock)


def init_simulador(app):
    """Registra la app. El arranque real es perezoso (`asegurar_simulador`)
    para ocurrir dentro del worker de gunicorn, no en el maestro."""
    global _app
    _app = app


def activo() -> bool:
    return bool(_app) and _app.config.get("SIMULADOR_AUTONOMO", False)


def asegurar_simulador():
    """Arranca (o revive) el hilo del simulador. Idempotente y fork-safe."""
    global _hilo, _pid
    if not activo():
        return
    pid = os.getpid()
    if _hilo is not None and _hilo.is_alive() and _pid == pid:
        return
    with _lock:
        pid = os.getpid()
        if _hilo is not None and _hilo.is_alive() and _pid == pid:
            return
        _pid = pid
        _hilo = threading.Thread(
            target=_bucle, name="simulador", daemon=True)
        _hilo.start()


def vivo() -> bool:
    return _hilo is not None and _hilo.is_alive() and _pid == os.getpid()


def latido_hace() -> float | None:
    if not _ultimo_latido:
        return None
    return round(time.monotonic() - _ultimo_latido, 1)


def enviar_cmd(payload: dict) -> bool:
    """Encola un comando para la FSM (pausar/reanudar/reiniciar/iniciar).
    Devuelve True si el simulador está activo y lo aceptó."""
    if not activo():
        return False
    with _lock:
        _cola_cmd.append(dict(payload))
    return True


# --------------------------------------------------------------------------
# Núcleo: la FSM corre en su propio hilo
# --------------------------------------------------------------------------

class _Maquina:
    """Estado de la envasadora simulada (equivalente al `struct Orden` +
    variables compartidas del firmware)."""

    def __init__(self):
        self.fsm = "ESPERA"
        self.activa = False
        self.orden_id: int | None = None
        self.orden_demo_id: int | None = None   # orden creada por el simulador
        self.numero_lote = "-"
        self.producto = "Maní"
        self.presentacion = 25
        self.tam_lote = 50
        self.producidas = 0
        self.rechazos = 0
        # físico
        self.valvula = False
        self.descarga = False
        self.peso = 0.0
        self.en_vuelo = 0.0
        self.valvula_prev = False
        self.t_marca = 0.0


def _bucle():
    global _ultimo_latido
    from adaptadores import mqtt_in

    m = _Maquina()
    with _app.app_context():
        _provisionar(m)                 # asegura una orden/lote donde producir

    ultimo_peso = 0.0
    while _pid == os.getpid():
        inicio = time.monotonic()
        _ultimo_latido = inicio
        try:
            _procesar_comandos(m, mqtt_in)
            _fisica(m)
            _fsm(m, mqtt_in)
            if inicio - ultimo_peso >= _PERIODO_PESO:
                ultimo_peso = inicio
                mqtt_in.despachar("peso", {"g": round(m.peso, 2),
                                           "ts": int(inicio * 1000)})
        except Exception:
            _app.logger.exception("Fallo en el lazo del simulador")
        # cadencia estable ~10 Hz
        resto = _DT - (time.monotonic() - inicio)
        if resto > 0:
            time.sleep(resto)


def _fisica(m: _Maquina):
    """Modelo de peso: caudal ~12 g/s con ruido + material en vuelo al
    cerrar la válvula (port del MODO_DEMO de la tarea_bascula)."""
    if m.descarga:
        m.peso = 0.0
        m.en_vuelo = 0.0
    else:
        if m.valvula:
            m.peso += _FLUJO_G_S * _DT + random.uniform(0.0, 0.2)
        if m.valvula_prev and not m.valvula:
            m.en_vuelo = 0.30 + random.uniform(0.0, 0.5)
        if not m.valvula and m.en_vuelo > 0.0:
            d = min(0.35, m.en_vuelo)
            m.peso += d
            m.en_vuelo -= d
    m.valvula_prev = m.valvula


def _fsm(m: _Maquina, mqtt_in):
    """Lazo de control determinista (port de tarea_control)."""
    ahora = time.monotonic()
    objetivo = float(m.presentacion)

    if m.fsm == "ESPERA":
        if m.activa:
            m.descarga = False
            m.valvula = True
            m.fsm = "DOSIFICANDO"
            _emitir_estado(m, mqtt_in)

    elif m.fsm == "DOSIFICANDO":
        if m.peso >= objetivo - _ANTICIPO_G:
            m.valvula = False
            m.t_marca = ahora
            m.fsm = "ASENTANDO"

    elif m.fsm == "ASENTANDO":
        if ahora - m.t_marca >= _MS_ASENTAR:
            m.fsm = "VALIDANDO"

    elif m.fsm == "VALIDANDO":
        tol = _app.config.get("TOLERANCIA_GR", 1.0)
        ok = reglas.validar_peso(m.peso, objetivo, tol)
        if ok:
            m.producidas += 1
            n = m.producidas
        else:
            m.rechazos += 1
            n = m.rechazos
        mqtt_in.despachar("unidad", {
            "lote": m.numero_lote, "n": n, "peso": round(m.peso, 2),
            "ok": ok, "producto": m.producto, "presentacion_gr": m.presentacion,
        })
        _emitir_estado(m, mqtt_in)
        if not ok:
            mqtt_in.despachar("alarma", {
                "tipo": "FUERA_TOLERANCIA", "peso": round(m.peso, 2)})
        m.descarga = True
        m.t_marca = ahora
        m.fsm = "DESCARGA"

    elif m.fsm == "DESCARGA":
        if ahora - m.t_marca >= _MS_DESCARGA:
            m.descarga = False
            if m.producidas >= m.tam_lote:
                m.activa = False
                m.valvula = False
                m.fsm = "ESPERA"
                _emitir_estado(m, mqtt_in)
                # demo continua: arranca el siguiente lote
                with _app.app_context():
                    _provisionar(m)
            else:
                m.valvula = True
                m.fsm = "DOSIFICANDO"
                _emitir_estado(m, mqtt_in)

    elif m.fsm == "PARADA":
        pass   # se sale con reanudar/iniciar


def _procesar_comandos(m: _Maquina, mqtt_in):
    with _lock:
        pendientes = _cola_cmd[:]
        _cola_cmd.clear()
    for cmd in pendientes:
        accion = cmd.get("accion", "")
        if accion in ("parar", "pausar"):
            if m.activa and m.fsm != "PARADA":
                m.valvula = False
                m.fsm = "PARADA"
                _emitir_estado(m, mqtt_in)
        elif accion == "reanudar":
            if m.fsm == "PARADA":
                m.valvula = True
                m.fsm = "DOSIFICANDO"
                _emitir_estado(m, mqtt_in)
        elif accion == "reiniciar":
            if m.activa:
                # reinicio del lote en curso: lote nuevo en la MISMA orden,
                # contadores de la máquina a cero (la producción previa queda
                # en el histórico). No huérfana la orden actual.
                with _app.app_context():
                    _reiniciar_lote(m)
                _emitir_estado(m, mqtt_in)
        elif accion == "iniciar":
            with _app.app_context():
                _adoptar_orden(m, cmd)
            _emitir_estado(m, mqtt_in)


def _emitir_estado(m: _Maquina, mqtt_in):
    mqtt_in.despachar("estado", {
        "fsm": m.fsm, "lote": m.numero_lote, "unidad": m.producidas,
        "rechazos": m.rechazos, "tam_lote": m.tam_lote,
        "producto": m.producto, "presentacion_gr": m.presentacion,
    })


# --------------------------------------------------------------------------
# Provisión de órdenes (requiere app_context activo)
# --------------------------------------------------------------------------

def _reiniciar_lote(m: _Maquina):
    """Reinicia el lote en curso: abre un lote nuevo en la misma orden y
    pone la máquina a cero. Si por algún motivo no hay orden, reprovisiona."""
    from adaptadores import repositorio

    lote = repositorio.nuevo_lote(m.orden_id) if m.orden_id else None
    if lote is None:
        _provisionar(m)
        return
    _cargar(m, lote.orden, lote)


def _provisionar(m: _Maquina):
    """Asegura una orden en proceso donde el simulador pueda producir.

    - Si ya hay una orden activa (p. ej. iniciada por el usuario), la adopta.
    - Si no, crea una orden de demostración (Maní 25 g × 50) y la inicia.
    Deja `m` listo para dosificar."""
    from adaptadores import repositorio

    orden = repositorio.orden_activa()
    if orden is not None:
        lote = orden.lotes[-1] if orden.lotes else repositorio.iniciar_orden(orden.id)
        m.orden_demo_id = None
        _cargar(m, orden, lote)
        return

    producto = repositorio.producto_demo()
    if producto is None:
        _app.logger.warning("Sin productos: el simulador no puede provisionar.")
        return
    orden = repositorio.crear_orden(producto.id, tam_lote=50,
                                    cantidad_solicitada=50, operador_id=None)
    lote = repositorio.iniciar_orden(orden.id)
    m.orden_demo_id = orden.id
    _cargar(m, orden, lote)
    _app.logger.info("Simulador: orden demo #%s lote %s",
                     orden.id, lote.numero_lote)


def _adoptar_orden(m: _Maquina, cmd: dict):
    """Comando 'iniciar' desde la web: el simulador pasa a producir la
    orden real del usuario. Hace relevo cerrando su orden de demo si la
    tenía abierta (evita dos órdenes 'en_proceso' a la vez)."""
    from adaptadores import repositorio

    numero_lote = cmd.get("lote", "")
    lote = repositorio.lote_por_numero(numero_lote)
    if lote is None:
        _app.logger.warning("Simulador: 'iniciar' con lote desconocido %s", numero_lote)
        return
    if m.orden_demo_id and m.orden_demo_id != lote.orden_id:
        repositorio.completar_orden(m.orden_demo_id)
        m.orden_demo_id = None
    _cargar(m, lote.orden, lote)


def _cargar(m: _Maquina, orden, lote):
    """Copia la receta y el progreso a la máquina y la deja lista para
    dosificar (contadores tomados de la BD como fuente de verdad)."""
    m.orden_id = orden.id
    m.numero_lote = lote.numero_lote
    m.producto = orden.producto.nombre
    m.presentacion = orden.producto.presentacion_gr
    m.tam_lote = orden.tam_lote
    m.producidas = lote.cantidad_producida
    m.rechazos = lote.cantidad_rechazada
    m.activa = True
    m.valvula = False
    m.descarga = False
    m.peso = 0.0
    m.en_vuelo = 0.0
    m.fsm = "ESPERA"
