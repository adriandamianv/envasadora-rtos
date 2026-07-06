"""Panel en vivo (dashboard '/').

Muestra la orden activa, inventario y últimas unidades; el resto
llega en tiempo real por Socket.IO (peso, estado FSM, alarmas).
"""
from flask import Blueprint, render_template

from adaptadores import repositorio
from vistas.auth import login_requerido

bp = Blueprint("panel", __name__)


@bp.route("/")
@login_requerido
def inicio():
    return render_template(
        "panel.html",
        orden=repositorio.orden_activa(),
        inventario=repositorio.listar_inventario(),
        unidades=repositorio.ultimas_unidades(10),
    )
