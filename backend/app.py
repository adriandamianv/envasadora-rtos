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

    # Adaptadores de máquina (MQTT real + simulador embebido). Se omiten en
    # seeds/pruebas. NO arrancan hilos aquí: el arranque es perezoso dentro
    # del worker (watchdog) para sobrevivir al fork de gunicorn.
    if iniciar_mqtt:
        from adaptadores.mqtt_in import asegurar_mqtt, init_mqtt
        from adaptadores.simulador import asegurar_simulador, init_simulador
        init_mqtt(app)
        init_simulador(app)

        @app.before_request
        def _watchdog_maquina():
            # Idempotente y barato: si un hilo no existe, murió o venimos de
            # un fork, lo revive en ESTE proceso. Así el panel nunca queda
            # "muerto" por un worker reciclado o forkeado.
            asegurar_mqtt()
            asegurar_simulador()

    # Asegura tablas y datos iniciales (idempotente): en Render no hay shell
    # para correr seeds.py, así que la app se autosiembra si la base está vacía.
    with app.app_context():
        from seeds import sembrar_datos
        if sembrar_datos():
            app.logger.info("Base vacía: datos iniciales sembrados.")

    return app


if __name__ == "__main__":
    aplicacion = create_app()
    # use_reloader=False: el reloader duplicaría la conexión MQTT
    socketio.run(aplicacion, host="0.0.0.0", port=5000,
                 debug=True, use_reloader=False, allow_unsafe_werkzeug=True)
