"""Configuración para pruebas automatizadas. Nunca usa datos reales.

Por defecto usa SQLite en memoria; para probar contra PostgreSQL defina TEST_DATABASE_URL.
"""
import os

os.environ.setdefault("DJANGO_SECRET_KEY", "clave-de-pruebas-automatizadas")
os.environ["DJANGO_DEBUG"] = "true"
if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
else:
    os.environ["DATABASE_URL"] = "sqlite://:memory:"

from .settings import *  # noqa: E402,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
LOGGING = {"version": 1, "disable_existing_loggers": False}
