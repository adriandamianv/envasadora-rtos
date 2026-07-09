"""Despacho de comandos hacia la máquina (simulador embebido y/o ESP32 real).

Las vistas no deben saber si detrás hay un simulador en proceso o un ESP32
en Wokwi: llaman a `enviar_comando(payload)` y este módulo decide.

- Si el simulador está activo (SIMULADOR_AUTONOMO=1), le entrega el comando
  de inmediato (sin red) y ADEMÁS lo publica al broker sin esperar
  confirmación, por si hay un ESP32 real escuchando.
- Si no, es el camino clásico: publica por MQTT y espera el PUBACK del
  broker para poder avisar al usuario si el comando no llegó.
"""
from adaptadores import mqtt_in, simulador


def enviar_comando(payload: dict) -> bool:
    """Devuelve True si algún consumidor (simulador o broker) aceptó el
    comando; False si nadie lo recibió (para que la vista avise)."""
    if simulador.activo():
        aceptado = simulador.enviar_cmd(payload)
        # espejo best-effort al ESP32 real, sin bloquear la request
        mqtt_in.publicar("cmd", payload, timeout=0)
        return aceptado
    return mqtt_in.publicar("cmd", payload)
