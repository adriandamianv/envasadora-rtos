"""Creación de la base de datos y datos iniciales (semillas).

Uso: python seeds.py
Crea usuarios (clave "1234"), los 4 productos y el inventario inicial.
Es idempotente: si ya hay datos, no duplica.
"""
from werkzeug.security import generate_password_hash

from app import create_app
from dominio.modelos import InventarioMateriaPrima, Producto, Usuario
from extensions import db


def sembrar():
    app = create_app(iniciar_mqtt=False)  # sin MQTT para sembrar
    with app.app_context():
        db.create_all()

        if db.session.query(Usuario).count() > 0:
            print("La base ya tiene datos; no se duplica nada.")
            return

        clave = generate_password_hash("1234")
        db.session.add_all([
            Usuario(nombre="Gabriela Gerente", usuario="gerente", clave_hash=clave, rol="gerente"),
            Usuario(nombre="Santiago Supervisor", usuario="supervisor", clave_hash=clave, rol="supervisor"),
            Usuario(nombre="Olga Operadora", usuario="operador", clave_hash=clave, rol="operador"),
        ])

        db.session.add_all([
            Producto(nombre="Maní", presentacion_gr=25),
            Producto(nombre="Maní", presentacion_gr=50),
            Producto(nombre="Pasas", presentacion_gr=25),
            Producto(nombre="Pasas", presentacion_gr=50),
        ])

        db.session.add_all([
            InventarioMateriaPrima(materia_prima="mani", cantidad_disponible=50.0, unidad_medida="kg"),
            InventarioMateriaPrima(materia_prima="pasas", cantidad_disponible=40.0, unidad_medida="kg"),
            InventarioMateriaPrima(materia_prima="fundas", cantidad_disponible=5000.0, unidad_medida="unidades"),
        ])

        db.session.commit()
        print("Base de datos creada y sembrada:")
        print("  usuarios: gerente / supervisor / operador (clave: 1234)")
        print("  productos: Maní 25g, Maní 50g, Pasas 25g, Pasas 50g")
        print("  inventario: maní 50 kg, pasas 40 kg, fundas 5000 u.")


if __name__ == "__main__":
    sembrar()
