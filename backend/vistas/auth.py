"""Autenticación con sesión de Flask + decoradores de rol.

Roles: operador (panel), supervisor (+ órdenes e inventario),
gerente (todo + reportes).
"""
import functools

from flask import (Blueprint, flash, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash

from dominio.modelos import Usuario
from extensions import db

bp = Blueprint("auth", __name__)


def login_requerido(vista):
    """Redirige al login si no hay sesión iniciada."""
    @functools.wraps(vista)
    def envoltura(*args, **kwargs):
        if "usuario_id" not in session:
            flash("Inicia sesión para continuar.", "error")
            return redirect(url_for("auth.login"))
        return vista(*args, **kwargs)
    return envoltura


def rol_requerido(*roles: str):
    """Exige que el rol en sesión esté en la lista permitida."""
    def decorador(vista):
        @functools.wraps(vista)
        def envoltura(*args, **kwargs):
            if "usuario_id" not in session:
                flash("Inicia sesión para continuar.", "error")
                return redirect(url_for("auth.login"))
            if session.get("rol") not in roles:
                flash("No tienes permisos para acceder a esa sección.", "error")
                return redirect(url_for("panel.inicio"))
            return vista(*args, **kwargs)
        return envoltura
    return decorador


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        nombre_usuario = request.form.get("usuario", "").strip()
        clave = request.form.get("clave", "")
        usuario = db.session.query(Usuario).filter_by(usuario=nombre_usuario).first()
        if usuario is not None and check_password_hash(usuario.clave_hash, clave):
            session.clear()
            session["usuario_id"] = usuario.id
            session["nombre"] = usuario.nombre
            session["rol"] = usuario.rol
            return redirect(url_for("panel.inicio"))
        flash("Usuario o clave incorrectos.", "error")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada.", "ok")
    return redirect(url_for("auth.login"))
