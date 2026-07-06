"""Panel en vivo (dashboard '/').

Muestra la orden activa, inventario y últimas unidades; el resto
llega en tiempo real por Socket.IO (peso, estado FSM, alarmas).
"""
from flask import Blueprint, flash, redirect, render_template, url_for

from adaptadores import repositorio
from vistas.auth import login_requerido, rol_requerido

bp = Blueprint("panel", __name__)

ACCIONES_MAQUINA = {
    "pausar": "Máquina pausada (válvula cerrada).",
    "reanudar": "Producción reanudada.",
    "reiniciar": "Lote reiniciado: contadores de la máquina a cero.",
}


@bp.route("/")
@login_requerido
def inicio():
    return render_template(
        "panel.html",
        orden=repositorio.orden_activa(),
        inventario=repositorio.listar_inventario(),
        unidades=repositorio.ultimas_unidades(10),
    )


@bp.route("/salud")
def salud():
    """Diagnóstico: estado del backend, conexión MQTT y publish de prueba."""
    import threading
    from flask import current_app
    from adaptadores import mqtt_in

    return {
        "estado": "ok",
        "mqtt_conectado": mqtt_in.conectado(),
        "publish_diag_confirmado": mqtt_in.publicar("diag", {"ping": 1}, timeout=3),
        "broker": current_app.config.get("MQTT_BROKER_URL"),
        "puerto": current_app.config.get("MQTT_BROKER_PORT"),
        "hilos": [t.name for t in threading.enumerate()],
    }


@bp.route("/maquina/<accion>", methods=["POST"])
@rol_requerido("supervisor", "gerente")
def maquina(accion: str):
    """Control de la simulación desde la web: pausar / reanudar / reiniciar."""
    from vistas.ordenes import _publicar_cmd

    if accion not in ACCIONES_MAQUINA:
        flash("Acción de máquina desconocida.", "error")
        return redirect(url_for("panel.inicio"))
    if _publicar_cmd({"accion": accion}):
        flash(ACCIONES_MAQUINA[accion], "ok")
    return redirect(url_for("panel.inicio"))
