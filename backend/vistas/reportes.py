"""Reportes gerenciales: lotes por día, % de rechazo, producción
por operador. Cada tabla se puede exportar a CSV.
"""
import csv
import io

from flask import Blueprint, Response, render_template

from adaptadores import repositorio
from dominio.reglas import porcentaje_rechazo
from vistas.auth import rol_requerido

bp = Blueprint("reportes", __name__, url_prefix="/reportes")


def _csv_response(nombre: str, cabecera: list[str], filas: list) -> Response:
    """Arma una respuesta CSV descargable a partir de filas de agregación."""
    buffer = io.StringIO()
    escritor = csv.writer(buffer)
    escritor.writerow(cabecera)
    escritor.writerows(filas)
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={nombre}.csv"},
    )


@bp.route("/")
@rol_requerido("gerente")
def inicio():
    lotes_dia = repositorio.reporte_lotes_por_dia()
    rechazo = [
        (r.numero_lote, r.cantidad_producida, r.cantidad_rechazada,
         porcentaje_rechazo(r.cantidad_producida, r.cantidad_rechazada),
         round(r.peso_promedio, 2) if r.peso_promedio is not None else "-")
        for r in repositorio.reporte_rechazo_por_lote()
    ]
    operadores = repositorio.reporte_por_operador()
    return render_template("reportes.html", lotes_dia=lotes_dia,
                           rechazo=rechazo, operadores=operadores)


@bp.route("/lotes-dia.csv")
@rol_requerido("gerente")
def csv_lotes_dia():
    filas = [(r.fecha_produccion, r.lotes, r.producidas or 0, r.rechazadas or 0)
             for r in repositorio.reporte_lotes_por_dia()]
    return _csv_response("lotes_por_dia",
                         ["fecha", "lotes", "producidas", "rechazadas"], filas)


@bp.route("/rechazo.csv")
@rol_requerido("gerente")
def csv_rechazo():
    filas = [
        (r.numero_lote, r.cantidad_producida, r.cantidad_rechazada,
         porcentaje_rechazo(r.cantidad_producida, r.cantidad_rechazada))
        for r in repositorio.reporte_rechazo_por_lote()
    ]
    return _csv_response("rechazo_por_lote",
                         ["lote", "producidas", "rechazadas", "pct_rechazo"], filas)


@bp.route("/operadores.csv")
@rol_requerido("gerente")
def csv_operadores():
    filas = [
        (r.nombre, r.total, r.aceptadas or 0,
         round(r.peso_promedio, 2) if r.peso_promedio is not None else 0)
        for r in repositorio.reporte_por_operador()
    ]
    return _csv_response("produccion_por_operador",
                         ["operador", "total", "aceptadas", "peso_promedio"], filas)
