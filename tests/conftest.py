"""Datos de prueba SINTÉTICOS. No usar nunca información real de afiliados."""
import itertools
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone

from apps.afiliados.services import crear_afiliado
from apps.aportaciones.models import MetodoPago, TipoMovimiento
from apps.aportaciones.services import asegurar_tipos_iniciales, registrar_movimiento
from apps.caja.services import asegurar_categorias
from apps.core.models import CuentaFondo
from apps.core.parametros import asegurar_parametros
from apps.core.roles import configurar_roles
from apps.core.secuencias import asegurar_secuencias

User = get_user_model()
_identidades = itertools.count(1)


@pytest.fixture(autouse=True)
def caune_inicializado(db):
    configurar_roles()
    asegurar_parametros()
    asegurar_secuencias()
    asegurar_tipos_iniciales()
    asegurar_categorias()


def _usuario(username, rol=None):
    u = User.objects.create_user(username=username, password="Prueba-segura-123", first_name=username.title())
    if rol:
        u.groups.add(Group.objects.get(name=rol))
    return User.objects.get(pk=u.pk)  # sin caché de permisos


@pytest.fixture
def sin_mora(db):
    """Para pruebas de intereses y capital: los préstamos que se aprueben no cobran mora."""
    from apps.core.models import Parametro
    Parametro.objects.filter(clave__in=["prestamos.tasa_mora_interna", "prestamos.tasa_mora_externa"]).update(valor="0")


@pytest.fixture
def admin_caune(db):
    return _usuario("admin.caune", "Administrador")


@pytest.fixture
def tesorero(db):
    return _usuario("tesorero", "Tesorero")


@pytest.fixture
def presidente(db):
    return _usuario("presidente", "Presidente")


@pytest.fixture
def supervisor(db):
    return _usuario("supervisor", "Contador o supervisor")


@pytest.fixture
def prestamos(db):
    return _usuario("prestamos", "Encargado de préstamos")


@pytest.fixture
def encargado_actividades(db):
    return _usuario("actividades", "Encargado de actividades")


@pytest.fixture
def fondear(tesorero):
    """Pone en la caja o cuenta el dinero que le falte para una salida (como «Saldo inicial», que no es utilidad).

    Desde la Fase 4 ninguna salida puede dejar una caja en negativo; los datos de prueba deben tener fondos.
    """
    from apps.caja import services as cs
    from apps.caja.models import CategoriaCaja

    def poner(cuenta, monto, fecha):
        faltante = Decimal(str(monto)) - cs.saldo(cuenta, hasta=fecha)
        if faltante > 0:
            metodo = MetodoPago.EFECTIVO if cuenta.tipo == CuentaFondo.Tipo.CAJA else MetodoPago.DEPOSITO_BANCARIO
            cs.registrar_movimiento(tipo="INGRESO", fecha=fecha, concepto="Fondos de prueba", monto=faltante,
                                    metodo_pago=metodo, cuenta_fondo=cuenta, referencia="PRUEBA",
                                    categoria=CategoriaCaja.objects.get(nombre="Saldo inicial"), usuario=tesorero)
    return poner


@pytest.fixture
def nuevo_prestamo(tesorero, caja, fondear):
    """Aprueba (y opcionalmente desembolsa) un préstamo interno con valores por defecto."""
    from apps.prestamos import services as ps

    def crear(afiliado, monto="1000", plazo=2, metodo="CUOTA_FIJA", desembolsar=True, cuenta=None, **extra):
        hoy = timezone.localdate()
        datos = dict(usuario=tesorero, tipo_prestatario="INTERNO", afiliado=afiliado, monto_solicitado=monto,
                     monto_aprobado=monto, plazo=plazo, metodo_amortizacion=metodo,
                     fecha_aprobacion=hoy - timedelta(days=60), fecha_primer_vencimiento=hoy - timedelta(days=30))
        datos.update(extra)
        p = ps.aprobar_prestamo(**datos)
        if desembolsar:
            fondear(cuenta or caja, p.monto_aprobado, hoy - timedelta(days=59))
            p = ps.desembolsar(p, usuario=tesorero, fecha=hoy - timedelta(days=59), cuenta=cuenta or caja,
                               metodo_pago="EFECTIVO")
        return p
    return crear


@pytest.fixture
def sin_rol(db):
    return _usuario("sin.rol")


@pytest.fixture
def caja(db):
    return CuentaFondo.objects.create(tipo=CuentaFondo.Tipo.CAJA, nombre="Caja de prueba")


@pytest.fixture
def banco(db):
    return CuentaFondo.objects.create(tipo=CuentaFondo.Tipo.BANCO, nombre="Banco de prueba", banco="Banco X",
                                      numero_cuenta="000-111")


@pytest.fixture
def tipos(db):
    return {t.codigo: t for t in TipoMovimiento.objects.all()}


@pytest.fixture
def hoy():
    return timezone.localdate()


@pytest.fixture
def nuevo_afiliado(tesorero):
    def crear(nombres="Prueba", apellidos="Sintética", fecha_ingreso=None, usuario=None):
        n = next(_identidades)
        return crear_afiliado({
            "nombres": nombres, "apellidos": apellidos, "identidad": f"9999{n:09d}", "telefono": "99990000",
            "direccion": "Dirección ficticia", "fecha_ingreso": fecha_ingreso or (timezone.localdate() - timedelta(days=365)),
        }, usuario or tesorero)
    return crear


@pytest.fixture
def afiliado(nuevo_afiliado):
    return nuevo_afiliado()


@pytest.fixture
def mov(tesorero, caja, tipos, hoy):
    """Registra un movimiento en efectivo con valores por defecto."""
    def registrar(afiliado, codigo_tipo, monto, fecha=None, usuario=None, **extra):
        datos = dict(afiliado=afiliado, tipo=tipos[codigo_tipo], fecha=fecha or hoy, monto=Decimal(str(monto)),
                     metodo_pago=MetodoPago.EFECTIVO, cuenta_fondo=caja, usuario=usuario or tesorero)
        datos.update(extra)
        movimiento, _ = registrar_movimiento(**datos)
        return movimiento
    return registrar


def dias_atras(n):
    return timezone.localdate() - timedelta(days=n)
