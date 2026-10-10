from django.core.management.base import BaseCommand
from django.db import transaction

from apps.aportaciones.services import asegurar_tipos_iniciales
from apps.caja.services import asegurar_categorias
from apps.core.models import CuentaFondo
from apps.core.parametros import asegurar_parametros
from apps.core.roles import configurar_roles
from apps.core.secuencias import asegurar_secuencias


class Command(BaseCommand):
    help = "Crea la configuración inicial de CAUNE (roles, parámetros, numeración, tipos, categorías de caja y caja general). Idempotente."

    def add_arguments(self, parser):
        parser.add_argument("--restablecer-roles", action="store_true",
                            help="Devuelve los permisos de los roles iniciales a sus valores por defecto.")

    @transaction.atomic
    def handle(self, *args, **opciones):
        roles = configurar_roles(restablecer=opciones["restablecer_roles"])
        asegurar_parametros()
        asegurar_secuencias()
        asegurar_tipos_iniciales()
        asegurar_categorias()
        if not CuentaFondo.objects.exists():
            CuentaFondo.objects.create(tipo=CuentaFondo.Tipo.CAJA, nombre="Caja general")
            self.stdout.write("Creada «Caja general».")
        for nombre, creado in roles.items():
            self.stdout.write(f"Rol {nombre}: {'creado' if creado else 'ya existía'}")
        self.stdout.write(self.style.SUCCESS("Configuración inicial lista."))
