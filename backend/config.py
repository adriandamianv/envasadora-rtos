"""Configuración central del backend de la envasadora.

Lee variables de entorno (Render) y provee valores por defecto
para desarrollo local (SQLite + broker público HiveMQ).
"""
import os
import uuid


def _normalizar_url_bd(url: str) -> str:
    """Render entrega postgres:// pero SQLAlchemy exige postgresql://"""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "clave-dev-envasadora")

    # Base de datos: PostgreSQL en Render, SQLite en local
    SQLALCHEMY_DATABASE_URI = _normalizar_url_bd(
        os.environ.get("DATABASE_URL", "sqlite:///envasadora.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # MQTT (broker público, mismo que usa el ESP32 en Wokwi)
    MQTT_BROKER_URL = os.environ.get("MQTT_BROKER_URL", "broker.emqx.io")
    MQTT_BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", 1883))
    MQTT_CLIENT_ID = f"backend-envasadora-{uuid.uuid4().hex[:8]}"
    MQTT_KEEPALIVE = 60
    MQTT_TLS_ENABLED = False
    # Conexión asíncrona: si el broker no responde la app NO muere,
    # paho reintenta en segundo plano.
    MQTT_CONNECT_ASYNC = True

    # Tópico raíz de la máquina envasadora ENV01
    TOPIC_BASE = os.environ.get("TOPIC_BASE", "envasadora/ENV01")

    # Tolerancia de peso aceptada en gramos (± sobre el objetivo)
    TOLERANCIA_GR = float(os.environ.get("TOLERANCIA_GR", 1.0))
