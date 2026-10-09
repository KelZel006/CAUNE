import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.afiliados.services import crear_afiliado
from apps.aportaciones.models import MetodoPago, TipoMovimiento
from apps.aportaciones.services import registrar_movimiento
from apps.core.models import CuentaFondo

NOMBRES = ["Ana", "Luis", "María", "José", "Carmen", "Pedro", "Lucía", "Jorge"]
APELLIDOS = ["Demo Pérez", "Demo López", "Demo Martínez", "Demo Flores", "Demo Reyes"]
CLAVE_DEMO = "Demo-CAUNE-2026"  # solo desarrollo; el comando se niega a correr con DEBUG desactivado
USUARIOS_DEMO = {
    "demo.admin": "Administrador",
    "demo.tesorero": "Tesorero",
    "demo.supervisor": "Contador o supervisor",
}


class Command(BaseCommand):
    help = "Carga datos FICTICIOS de demostración. Solo funciona con DJANGO_DEBUG=true y nunca en producción."

    def add_arguments(self, parser):
        parser.add_argument("--afiliados", type=int, default=8)

    @transaction.atomic
    def handle(self, *args, **opciones):
        if not settings.DEBUG:
            raise CommandError("Los datos de demostración solo se cargan en desarrollo (DJANGO_DEBUG=true).")
        call_command("inicializar_caune")
        User = get_user_model()
        for username, rol in USUARIOS_DEMO.items():
            u, _ = User.objects.get_or_create(username=username, defaults={"first_name": f"{rol} (demo)"})
            u.set_password(CLAVE_DEMO)
            u.save()
            u.groups.add(Group.objects.get(name=rol))
        usuario = User.objects.get(username="demo.tesorero")  # recarga caché de permisos
        caja = CuentaFondo.objects.filter(tipo=CuentaFondo.Tipo.CAJA, activa=True).first()
        aportacion = TipoMovimiento.objects.get(codigo="APO")
        deposito = TipoMovimiento.objects.get(codigo="DEP")
        hoy = timezone.localdate()
        rnd = random.Random(2026)
        for i in range(opciones["afiliados"]):
            ingreso = hoy - timedelta(days=rnd.randint(120, 400))
            afiliado = crear_afiliado({
                "nombres": rnd.choice(NOMBRES), "apellidos": rnd.choice(APELLIDOS),
                "identidad": f"9999{rnd.randint(1950, 2005)}{i:05d}", "telefono": f"9{rnd.randint(1000000, 9999999)}",
                "direccion": "Dirección de demostración", "fecha_ingreso": ingreso,
            }, usuario)
            fecha = ingreso
            while fecha <= hoy:
                registrar_movimiento(afiliado=afiliado, tipo=aportacion, fecha=fecha,
                                     monto=Decimal(rnd.choice([500, 1000, 1500])), metodo_pago=MetodoPago.EFECTIVO,
                                     cuenta_fondo=caja, usuario=usuario, observacion="DEMO")
                if rnd.random() < 0.4:
                    registrar_movimiento(afiliado=afiliado, tipo=deposito, fecha=fecha,
                                         monto=Decimal(rnd.randint(2, 20) * 100), metodo_pago=MetodoPago.EFECTIVO,
                                         cuenta_fondo=caja, usuario=usuario, observacion="DEMO")
                fecha += timedelta(days=30)
        self.stdout.write(self.style.WARNING(
            f"Datos FICTICIOS cargados (identidades 9999…, apellidos «Demo»). "
            f"Usuarios: {', '.join(USUARIOS_DEMO)} (clave en cargar_demo.py)"))
