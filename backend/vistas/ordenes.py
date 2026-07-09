"""CRUD de órdenes de producción + comandos MQTT hacia el ESP32.

Al iniciar una orden se publica en envasadora/ENV01/cmd un JSON con
la receta; al detenerla, la acción 'parar'.
"""
import json

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, session, url_for)

from adaptadores import repositorio
from vistas.auth import rol_requerido

bp = Blueprint("ordenes", __name__, url_prefix="/ordenes")


def _publicar_cmd(payload: dict) -> bool:
    """Entrega un comando a la máquina (simulador embebido y/o ESP32 real)."""
    from adaptadores import despacho

    if despacho.enviar_comando(payload):
        return True
    flash("Aviso: no se pudo enviar el comando a la máquina (broker sin "
          "conexión). Vuelve a intentarlo en unos segundos.", "error")
    return False


@bp.route("/")
@rol_requerido("supervisor", "gerente")
def listar():
    return render_template(
        "ordenes.html",
        ordenes=repositorio.listar_ordenes(),
        productos=repositorio.listar_productos(),
    )


@bp.route("/crear", methods=["POST"])
@rol_requerido("supervisor", "gerente")
def crear():
    try:
        producto_id = int(request.form["producto_id"])
        tam_lote = int(request.form["tam_lote"])
        cantidad = int(request.form["cantidad_solicitada"])
    except (KeyError, ValueError):
        flash("Datos de la orden inválidos.", "error")
        return redirect(url_for("ordenes.listar"))
    if tam_lote not in (50, 100) or cantidad <= 0:
        flash("El tamaño de lote debe ser 50 o 100 y la cantidad positiva.", "error")
        return redirect(url_for("ordenes.listar"))
    repositorio.crear_orden(producto_id, tam_lote, cantidad, session.get("usuario_id"))
    flash("Orden creada.", "ok")
    return redirect(url_for("ordenes.listar"))


@bp.route("/<int:orden_id>/iniciar", methods=["POST"])
@rol_requerido("supervisor", "gerente")
def iniciar(orden_id: int):
    lote = repositorio.iniciar_orden(orden_id)
    if lote is None:
        flash("La orden no puede iniciarse en su estado actual.", "error")
        return redirect(url_for("ordenes.listar"))
    producto = lote.orden.producto
    _publicar_cmd({
        "accion": "iniciar",
        "producto": producto.nombre,
        "presentacion_gr": producto.presentacion_gr,
        "tam_lote": lote.orden.tam_lote,
        "lote": lote.numero_lote,
    })
    flash(f"Orden iniciada. Lote {lote.numero_lote} enviado a la envasadora.", "ok")
    return redirect(url_for("ordenes.listar"))


@bp.route("/<int:orden_id>/detener", methods=["POST"])
@rol_requerido("supervisor", "gerente")
def detener(orden_id: int):
    if not repositorio.detener_orden(orden_id):
        flash("La orden no está en proceso.", "error")
        return redirect(url_for("ordenes.listar"))
    _publicar_cmd({"accion": "parar"})
    flash("Orden detenida y comando de paro enviado.", "ok")
    return redirect(url_for("ordenes.listar"))
