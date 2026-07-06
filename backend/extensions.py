"""Extensiones compartidas (patrón app factory).

Se instancian sin app y se enlazan en create_app() para evitar
importaciones circulares entre vistas, adaptadores y modelos.
"""
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base declarativa tipada (SQLAlchemy 2)."""


db = SQLAlchemy(model_class=Base)

# async_mode='threading': compatible con gunicorn --threads y con
# los hilos de paho-mqtt (NO usar eventlet junto con Flask-MQTT).
socketio = SocketIO(async_mode="threading", cors_allowed_origins="*")

