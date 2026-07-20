"""Configuración central de la aplicación."""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # Base de datos SQLite en la carpeta 'instance/'
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "instance", "taller3d.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.environ.get("SECRET_KEY", "cambia-esta-clave-en-produccion")

    # Reparto de ganancias por defecto (50% / 50%)
    REPARTO_EQUITATIVO = True
