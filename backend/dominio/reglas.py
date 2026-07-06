"""Reglas de negocio puras (sin Flask, sin base de datos).

Aquí vive la lógica que se puede probar de forma aislada:
validación de peso, consumo de materia prima, caducidad y la
máquina de estados de la orden de producción.
"""
from datetime import date, timedelta

DIAS_CADUCIDAD = 180

# Máquina de estados de la orden: desde cada estado, a dónde se puede ir.
TRANSICIONES_ORDEN = {
    "pendiente": {"en_proceso"},
    "en_proceso": {"completada", "pendiente"},  # 'pendiente' = orden detenida
    "completada": set(),
}


def validar_peso(peso: float, objetivo: float, tolerancia: float) -> bool:
    """Una unidad es aceptable si |peso - objetivo| <= tolerancia (gramos)."""
    return abs(peso - objetivo) <= tolerancia


def consumo_materia_prima(presentacion_gr: int, unidades: int) -> float:
    """Kilogramos de materia prima consumidos por 'unidades' fundas."""
    return (presentacion_gr * unidades) / 1000.0


def calcular_fecha_caducidad(fecha_produccion: date) -> date:
    """La caducidad es 180 días después de la producción."""
    return fecha_produccion + timedelta(days=DIAS_CADUCIDAD)


def transicion_valida(estado_actual: str, estado_nuevo: str) -> bool:
    """¿La orden puede pasar de estado_actual a estado_nuevo?"""
    return estado_nuevo in TRANSICIONES_ORDEN.get(estado_actual, set())


def generar_numero_lote(secuencia: int) -> str:
    """Formatea el número de lote: 1 -> 'L-0001'."""
    return f"L-{secuencia:04d}"


def porcentaje_rechazo(producidas: int, rechazadas: int) -> float:
    """% de unidades rechazadas sobre el total procesado."""
    total = producidas + rechazadas
    if total == 0:
        return 0.0
    return round(rechazadas * 100.0 / total, 2)
