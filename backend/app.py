"""Punto de entrada: fábrica de aplicación de la envasadora.

Uso local:  python seeds.py && python app.py
Producción: gunicorn --workers 1 --threads 8 wsgi:application
"""
from flask import Flask

from config import Config
from extensions import db, socketio


def create_app(iniciar_mqtt: bool = True) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    # Extensiones
    db.init_app(app)
    socketio.init_app(app)

    # Modelos (deben importarse antes de create_all / consultas)
    from dominio import modelos  # noqa: F401

    # Blueprints (vistas)
    from vistas import auth, inventario, ordenes, panel, reportes
    app.register_blueprint(auth.bp)
    app.register_blueprint(panel.bp)
    app.register_blueprint(ordenes.bp)
    app.register_blueprint(inventario.bp)
    app.register_blueprint(reportes.bp)

    # Adaptador MQTT (se omite en seeds/pruebas)
    if iniciar_mqtt:
        from adaptadores.mqtt_in import init_mqtt
        init_mqtt(app)

    # Asegura que las tablas existan (idempotente; los datos los crea seeds.py)
    with app.app_context():
        db.create_all()

    return app


if __name__ == "__main__":
    aplicacion = create_app()
    # use_reloader=False: el reloader duplicaría la conexión MQTT
    socketio.run(aplicacion, host="0.0.0.0", port=5000,
                 debug=True, use_reloader=False, allow_unsafe_werkzeug=True)
