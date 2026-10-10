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
        from apps.afiliados.models import Afiliado
        if Afiliado.objects.filter(apellidos__startswith="Demo").exists():
            self.stdout.write("Ya existen afiliados de demostración; solo se agregan datos de las fases 2 y 3.")
            self._fase2(usuario, caja, hoy)
            self._fase3(usuario, caja, hoy)
            return
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
        self._fase2(usuario, caja, hoy)
        self._fase3(usuario, caja, hoy)
        self.stdout.write(self.style.WARNING(
            f"Datos FICTICIOS cargados (identidades 9999…, apellidos «Demo»). "
            f"Usuarios: {', '.join(USUARIOS_DEMO)} (clave en cargar_demo.py)"))

    def _fase2(self, usuario, caja, hoy):
        """Préstamos y actividades ficticios (solo si aún no hay préstamos)."""
        from apps.actividades import services as acs
        from apps.afiliados.models import Afiliado
        from apps.prestamos import services as ps
        from apps.prestamos.models import Prestamo

        if Prestamo.objects.exists():
            return
        afiliados = list(Afiliado.objects.filter(apellidos__startswith="Demo").order_by("codigo")[:3])
        inicio = hoy - timedelta(days=120)
        p1 = ps.aprobar_prestamo(usuario=usuario, tipo_prestatario="INTERNO", afiliado=afiliados[0],
                                 monto_solicitado="15000", monto_aprobado="15000", plazo=12,
                                 metodo_amortizacion="CUOTA_FIJA", fecha_aprobacion=inicio,
                                 fecha_primer_vencimiento=inicio + timedelta(days=30), observaciones="DEMO")
        ps.desembolsar(p1, usuario=usuario, fecha=inicio, cuenta=caja, metodo_pago="EFECTIVO")
        for cuota in p1.cuotas.filter(fecha_vencimiento__lte=hoy).order_by("numero"):
            ps.registrar_pago(p1, usuario=usuario, tipo="PAGO", fecha=cuota.fecha_vencimiento, monto=cuota.cuota,
                              metodo_pago="EFECTIVO", cuenta_fondo=caja, observacion="DEMO")
        p2 = ps.aprobar_prestamo(usuario=usuario, tipo_prestatario="INTERNO", afiliado=afiliados[1],
                                 monto_solicitado="8000", monto_aprobado="8000", plazo=8,
                                 metodo_amortizacion="CAPITAL_FIJO", fecha_aprobacion=hoy - timedelta(days=40),
                                 fecha_primer_vencimiento=hoy - timedelta(days=10), observaciones="DEMO")
        ps.desembolsar(p2, usuario=usuario, fecha=hoy - timedelta(days=40), cuenta=caja, metodo_pago="EFECTIVO")
        ps.registrar_pago(p2, usuario=usuario, tipo="PAGO", fecha=hoy - timedelta(days=9), monto=Decimal("500"),
                          metodo_pago="EFECTIVO", cuenta_fondo=caja, observacion="DEMO: pago parcial")
        ps.aprobar_prestamo(usuario=usuario, tipo_prestatario="EXTERNO",
                            externo={"nombre_completo": "Prestatario Externo Demo", "identidad": "8888199000001"},
                            afiliado_responsable=afiliados[2],
                            monto_solicitado="5000", monto_aprobado="4000", plazo=6,
                            metodo_amortizacion="CUOTA_FIJA", fecha_aprobacion=hoy,
                            fecha_primer_vencimiento=hoy + timedelta(days=30), observaciones="DEMO (por desembolsar)")
        act = acs.crear_actividad({"nombre": "Venta de comida (demo)", "descripcion": "Actividad ficticia",
                                   "fecha_inicio": hoy - timedelta(days=60)}, usuario)
        comida = acs.crear_subactividad(act, {"nombre": "Comida"}, usuario)
        bebidas = acs.crear_subactividad(act, {"nombre": "Bebidas"}, usuario)
        for tipo, sub, concepto, monto in (("INGRESO", comida, "Venta de baleadas", "3200"),
                                           ("GASTO", comida, "Compra de ingredientes", "1450.75"),
                                           ("INGRESO", bebidas, "Venta de refrescos", "980"),
                                           ("GASTO", bebidas, "Compra de refrescos", "620"),
                                           ("GASTO", None, "Alquiler de mesas", "300")):
            acs.registrar_movimiento(actividad=act, subactividad=sub, tipo=tipo, fecha=hoy - timedelta(days=30),
                                     concepto=concepto, monto=Decimal(monto), metodo_pago="EFECTIVO",
                                     cuenta_fondo=caja, usuario=usuario, observacion="DEMO")
        rifa = acs.crear_actividad({"nombre": "Rifa navideña (demo)", "fecha_inicio": hoy - timedelta(days=20)}, usuario)
        acs.registrar_movimiento(actividad=rifa, tipo="INGRESO", fecha=hoy - timedelta(days=5), concepto="Boletos",
                                 monto=Decimal("1500"), metodo_pago="EFECTIVO", cuenta_fondo=caja, usuario=usuario)
        acs.registrar_movimiento(actividad=rifa, tipo="GASTO", fecha=hoy - timedelta(days=5), concepto="Premio",
                                 monto=Decimal("1800"), metodo_pago="EFECTIVO", cuenta_fondo=caja, usuario=usuario)

    def _fase3(self, usuario, caja, hoy):
        """Banco, movimientos de caja y un afiliado que no participa en una actividad (solo si no hay movimientos)."""
        from apps.actividades import services as acs
        from apps.actividades.models import Actividad
        from apps.afiliados.models import Afiliado
        from apps.caja import services as cs
        from apps.caja.models import CategoriaCaja, MovimientoCaja

        if MovimientoCaja.objects.exists():
            return
        banco, _ = CuentaFondo.objects.get_or_create(
            tipo=CuentaFondo.Tipo.BANCO, nombre="Cuenta de ahorro (demo)",
            defaults={"banco": "Banco Demo", "numero_cuenta": "000-DEMO-01", "titular": "CAUNE"})
        cat = {c.nombre: c for c in CategoriaCaja.objects.all()}
        for tipo, categoria, cuenta, metodo, ref, dias, concepto, monto in (
                ("TRANSFERENCIA", None, caja, "DEPOSITO_BANCARIO", "BOL-DEMO-1", 50, "Depósito del efectivo", "6000"),
                ("INGRESO", "Intereses bancarios", banco, "TRANSFERENCIA", "INT-DEMO", 20, "Intereses del mes", "85.40"),
                ("EGRESO", "Comisiones bancarias", banco, "TRANSFERENCIA", "COM-DEMO", 20, "Comisión de manejo", "25"),
                ("EGRESO", "Gastos administrativos", caja, "EFECTIVO", "", 10, "Papelería y copias", "350")):
            cs.registrar_movimiento(tipo=tipo, fecha=hoy - timedelta(days=dias), concepto=concepto,
                                    monto=Decimal(monto), metodo_pago=metodo, cuenta_fondo=cuenta,
                                    categoria=cat.get(categoria), cuenta_destino=banco if tipo == "TRANSFERENCIA" else None,
                                    referencia=ref, observacion="DEMO", usuario=usuario)
        act = Actividad.objects.filter(nombre="Venta de comida (demo)").first()
        afiliado = Afiliado.objects.filter(apellidos__startswith="Demo").order_by("codigo").last()
        if act and afiliado and not act.exclusiones.exists():
            acs.excluir_afiliado(act, afiliado, usuario=usuario, motivo="DEMO: no colaboró en la venta de comida")
