"""Repositorio: toda la persistencia pasa por aquí.

Las vistas y los handlers MQTT llaman a estas funciones; ninguna
otra parte del código hace db.session directamente.
"""
from datetime import date, datetime

from sqlalchemy import case, func

from dominio import reglas
from dominio.modelos import (
    HistoricoProduccion,
    InventarioMateriaPrima,
    Lote,
    OrdenProduccion,
    Producto,
    Usuario,
)
from extensions import db

# --------------------------------------------------------------------------
# Órdenes de producción
# --------------------------------------------------------------------------

def crear_orden(producto_id: int, tam_lote: int, cantidad_solicitada: int,
                operador_id: int | None) -> OrdenProduccion:
    orden = OrdenProduccion(
        producto_id=producto_id,
        tam_lote=tam_lote,
        cantidad_solicitada=cantidad_solicitada,
        operador_id=operador_id,
    )
    db.session.add(orden)
    db.session.commit()
    return orden


def iniciar_orden(orden_id: int) -> Lote | None:
    """Pasa la orden a 'en_proceso' y abre un lote nuevo. None si no procede.

    Si la orden ya está en proceso devuelve su último lote, para poder
    reenviar el comando a la máquina (p. ej. si el cmd MQTT se perdió por
    un arranque en frío del servidor o un reinicio del dispositivo)."""
    orden = db.session.get(OrdenProduccion, orden_id)
    if orden is None:
        return None
    if orden.estado == "en_proceso" and orden.lotes:
        return orden.lotes[-1]
    if not reglas.transicion_valida(orden.estado, "en_proceso"):
        return None
    orden.estado = "en_proceso"
    secuencia = (db.session.query(func.max(Lote.id)).scalar() or 0) + 1
    lote = Lote(
        numero_lote=reglas.generar_numero_lote(secuencia),
        orden_id=orden.id,
        fecha_produccion=date.today(),
        fecha_caducidad=reglas.calcular_fecha_caducidad(date.today()),
    )
    db.session.add(lote)
    db.session.commit()
    return lote


def nuevo_lote(orden_id: int) -> Lote | None:
    """Abre un lote nuevo sobre una orden ya en proceso (reinicio de lote
    desde el panel): la producción previa queda en el histórico y los
    contadores arrancan de cero en un lote fresco."""
    orden = db.session.get(OrdenProduccion, orden_id)
    if orden is None or orden.estado != "en_proceso":
        return None
    secuencia = (db.session.query(func.max(Lote.id)).scalar() or 0) + 1
    lote = Lote(
        numero_lote=reglas.generar_numero_lote(secuencia),
        orden_id=orden.id,
        fecha_produccion=date.today(),
        fecha_caducidad=reglas.calcular_fecha_caducidad(date.today()),
    )
    db.session.add(lote)
    db.session.commit()
    return lote


def completar_orden(orden_id: int) -> bool:
    """Marca la orden como completada (usado por el simulador al hacer
    relevo entre su orden de demostración y una orden real del usuario)."""
    orden = db.session.get(OrdenProduccion, orden_id)
    if orden is None or not reglas.transicion_valida(orden.estado, "completada"):
        return False
    orden.estado = "completada"
    db.session.commit()
    return True


def producto_demo() -> Producto | None:
    """Un producto cualquiera para la orden autónoma del simulador
    (el de menor presentación: Maní/Pasas 25 g)."""
    return db.session.query(Producto).order_by(Producto.presentacion_gr).first()


def lote_por_numero(numero_lote: str) -> Lote | None:
    return db.session.query(Lote).filter_by(numero_lote=numero_lote).first()


def detener_orden(orden_id: int) -> bool:
    """Devuelve la orden a 'pendiente' (paro manual desde el panel)."""
    orden = db.session.get(OrdenProduccion, orden_id)
    if orden is None or not reglas.transicion_valida(orden.estado, "pendiente"):
        return False
    orden.estado = "pendiente"
    db.session.commit()
    return True


def registrar_unidad(numero_lote: str, peso_real: float, ok: bool,
                     operador_id: int | None = None) -> dict | None:
    """Registra una unidad envasada reportada por el ESP32.

    Inserta el histórico, actualiza contadores del lote, descuenta
    inventario si la unidad fue aceptada y, si el lote alcanza el
    tamaño objetivo, marca la orden como completada.
    Devuelve un resumen para emitir por Socket.IO (o None si el lote no existe).
    """
    lote = db.session.query(Lote).filter_by(numero_lote=numero_lote).first()
    if lote is None:
        return None
    orden = lote.orden
    if operador_id is None:
        operador_id = orden.operador_id

    db.session.add(HistoricoProduccion(
        lote_id=lote.id,
        peso_real=peso_real,
        ok=ok,
        fecha_hora=datetime.now(),
        operador_id=operador_id,
    ))

    if ok:
        lote.cantidad_producida += 1
        # Solo se descuenta inventario cuando la unidad sale aceptada
        producto = orden.producto
        materia = "mani" if "man" in producto.nombre.lower() else "pasas"
        descontar_inventario(materia, reglas.consumo_materia_prima(producto.presentacion_gr, 1))
        descontar_inventario("fundas", 1)
    else:
        lote.cantidad_rechazada += 1

    completado = lote.cantidad_producida >= orden.tam_lote
    if completado and reglas.transicion_valida(orden.estado, "completada"):
        orden.estado = "completada"

    db.session.commit()
    return {
        "lote": lote.numero_lote,
        "peso": peso_real,
        "ok": ok,
        "producidas": lote.cantidad_producida,
        "rechazadas": lote.cantidad_rechazada,
        "objetivo": orden.tam_lote,
        "completado": completado,
        "producto": orden.producto.nombre,
    }


# --------------------------------------------------------------------------
# Inventario
# --------------------------------------------------------------------------

def descontar_inventario(materia_prima: str, cantidad: float) -> None:
    item = db.session.query(InventarioMateriaPrima).filter_by(
        materia_prima=materia_prima).first()
    if item is not None:
        item.cantidad_disponible = max(0.0, item.cantidad_disponible - cantidad)


def ajustar_inventario(item_id: int, nueva_cantidad: float) -> bool:
    item = db.session.get(InventarioMateriaPrima, item_id)
    if item is None or nueva_cantidad < 0:
        return False
    item.cantidad_disponible = nueva_cantidad
    db.session.commit()
    return True


def listar_inventario() -> list[InventarioMateriaPrima]:
    return db.session.query(InventarioMateriaPrima).order_by(
        InventarioMateriaPrima.materia_prima).all()


# --------------------------------------------------------------------------
# Consultas para vistas y reportes (SQL de agregación)
# --------------------------------------------------------------------------

def listar_ordenes() -> list[OrdenProduccion]:
    return db.session.query(OrdenProduccion).order_by(
        OrdenProduccion.fecha.desc()).all()


def listar_productos() -> list[Producto]:
    return db.session.query(Producto).order_by(Producto.nombre).all()


def orden_activa() -> OrdenProduccion | None:
    return db.session.query(OrdenProduccion).filter_by(estado="en_proceso").first()


def ultimas_unidades(limite: int = 10) -> list[HistoricoProduccion]:
    return db.session.query(HistoricoProduccion).order_by(
        HistoricoProduccion.fecha_hora.desc()).limit(limite).all()


def reporte_lotes_por_dia() -> list:
    """Lotes producidos por día: fecha, nº lotes, unidades ok y rechazadas."""
    return db.session.query(
        Lote.fecha_produccion,
        func.count(Lote.id).label("lotes"),
        func.sum(Lote.cantidad_producida).label("producidas"),
        func.sum(Lote.cantidad_rechazada).label("rechazadas"),
    ).group_by(Lote.fecha_produccion).order_by(Lote.fecha_produccion.desc()).all()


def reporte_rechazo_por_lote() -> list:
    """% de rechazo y peso promedio por lote (agregación sobre el histórico)."""
    return db.session.query(
        Lote.numero_lote,
        Lote.cantidad_producida,
        Lote.cantidad_rechazada,
        func.avg(HistoricoProduccion.peso_real).label("peso_promedio"),
    ).outerjoin(HistoricoProduccion, HistoricoProduccion.lote_id == Lote.id
    ).group_by(Lote.id).order_by(Lote.numero_lote).all()


def reporte_por_operador() -> list:
    """Unidades procesadas y aceptadas por operador."""
    return db.session.query(
        Usuario.nombre,
        func.count(HistoricoProduccion.id).label("total"),
        func.sum(case((HistoricoProduccion.ok, 1), else_=0)).label("aceptadas"),
        func.avg(HistoricoProduccion.peso_real).label("peso_promedio"),
    ).join(HistoricoProduccion, HistoricoProduccion.operador_id == Usuario.id
    ).group_by(Usuario.id).order_by(Usuario.nombre).all()
