"""Punto de entrada WSGI para gunicorn (Render).

IMPORTANTE: gunicorn debe correr con --workers 1 (Flask-MQTT mantiene
una única conexión al broker; varios workers duplicarían mensajes).
"""
from app import create_app

application = create_app()
