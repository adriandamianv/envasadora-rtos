"""Listado y ajuste manual del inventario de materias primas."""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from adaptadores import repositorio
from vistas.auth import rol_requerido

bp = Blueprint("inventario", __name__, url_prefix="/inventario")


@bp.route("/")
@rol_requerido("supervisor", "gerente")
def listar():
    return render_template("inventario.html", items=repositorio.listar_inventario())


@bp.route("/<int:item_id>/ajustar", methods=["POST"])
@rol_requerido("supervisor", "gerente")
def ajustar(item_id: int):
    try:
        nueva_cantidad = float(request.form["cantidad"])
    except (KeyError, ValueError):
        flash("Cantidad inválida.", "error")
        return redirect(url_for("inventario.listar"))
    if repositorio.ajustar_inventario(item_id, nueva_cantidad):
        flash("Inventario actualizado.", "ok")
    else:
        flash("No se pudo ajustar el inventario.", "error")
    return redirect(url_for("inventario.listar"))
