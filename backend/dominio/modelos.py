"""Modelos de dominio (SQLAlchemy 2, estilo Mapped/mapped_column).

Seis tablas: Producto, OrdenProduccion, Lote, InventarioMateriaPrima,
HistoricoProduccion y Usuario.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from extensions import db


class Producto(db.Model):
    __tablename__ = "productos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    presentacion_gr: Mapped[int] = mapped_column(Integer, nullable=False)  # 25 | 50

    ordenes: Mapped[list["OrdenProduccion"]] = relationship(back_populates="producto")

    def __repr__(self) -> str:
        return f"<Producto {self.nombre} {self.presentacion_gr}g>"


class OrdenProduccion(db.Model):
    __tablename__ = "ordenes_produccion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), nullable=False)
    tam_lote: Mapped[int] = mapped_column(Integer, nullable=False)  # 50 | 100
    cantidad_solicitada: Mapped[int] = mapped_column(Integer, nullable=False)
    # 'pendiente' -> 'en_proceso' -> 'completada'
    estado: Mapped[str] = mapped_column(String(20), default="pendiente")
    operador_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id"))

    producto: Mapped["Producto"] = relationship(back_populates="ordenes")
    operador: Mapped[Optional["Usuario"]] = relationship()
    lotes: Mapped[list["Lote"]] = relationship(back_populates="orden")


class Lote(db.Model):
    __tablename__ = "lotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    numero_lote: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # "L-0001"
    orden_id: Mapped[int] = mapped_column(ForeignKey("ordenes_produccion.id"), nullable=False)
    fecha_produccion: Mapped[date] = mapped_column(Date, default=date.today)
    fecha_caducidad: Mapped[date] = mapped_column(Date, nullable=False)  # produccion + 180 dias
    cantidad_producida: Mapped[int] = mapped_column(Integer, default=0)
    cantidad_rechazada: Mapped[int] = mapped_column(Integer, default=0)

    orden: Mapped["OrdenProduccion"] = relationship(back_populates="lotes")
    historico: Mapped[list["HistoricoProduccion"]] = relationship(back_populates="lote")


class InventarioMateriaPrima(db.Model):
    __tablename__ = "inventario_materias_primas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    materia_prima: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    cantidad_disponible: Mapped[float] = mapped_column(Float, default=0.0)
    unidad_medida: Mapped[str] = mapped_column(String(20), nullable=False)  # 'kg' | 'unidades'


class HistoricoProduccion(db.Model):
    __tablename__ = "historico_produccion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lotes.id"), nullable=False)
    peso_real: Mapped[float] = mapped_column(Float, nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fecha_hora: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    operador_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id"))

    lote: Mapped["Lote"] = relationship(back_populates="historico")
    operador: Mapped[Optional["Usuario"]] = relationship()


class Usuario(db.Model):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    usuario: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    clave_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # 'operador' | 'supervisor' | 'gerente'
    rol: Mapped[str] = mapped_column(String(20), nullable=False, default="operador")

    def __repr__(self) -> str:
        return f"<Usuario {self.usuario} ({self.rol})>"
