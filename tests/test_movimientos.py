import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.afiliados.services import cambiar_estado
from apps.aportaciones import services
from apps.aportaciones.models import MetodoPago, MovimientoAfiliado, TipoMovimiento
from apps.core import parametros
from apps.core.models import HistorialAuditoria, Parametro

from .conftest import dias_atras

D = Decimal


# ------------------------------------------------------------------ registro y saldos

def test_registrar_aportacion_y_deposito_actualiza_saldos(afiliado, mov):
    m1 = mov(afiliado, "APO", "1000.00")
    m2 = mov(afiliado, "DEP", "250.50")
    assert m1.numero_operacion == "OP-000001" and m2.numero_operacion == "OP-000002"
    assert services.saldos_afiliado(afiliado) == {"aportaciones": D("1000.00"), "depositos": D("250.50"),
                                                  "total": D("1250.50")}


def test_saldos_individuales_independientes(nuevo_afiliado, mov):
    a, b = nuevo_afiliado(), nuevo_afiliado()
    mov(a, "APO", 300)
    mov(b, "APO", 700)
    mov(b, "DEP", 50)
    assert services.saldos_afiliado(a)["total"] == D("300.00")
    assert services.saldos_afiliado(b)["total"] == D("750.00")
    assert services.totales_generales() == {"aportaciones": D("1000.00"), "depositos": D("50.00")}


def test_saldos_anotados_coinciden_con_servicio(nuevo_afiliado, mov):
    from apps.afiliados.models import Afiliado
    a, b = nuevo_afiliado(), nuevo_afiliado()
    mov(a, "APO", "100.10")
    mov(a, "DEP", "40")
    mov(a, "RDEP", "15.05")
    mov(b, "APO", "5")
    for af in services.anotar_saldos(Afiliado.objects.all()):
        s = services.saldos_afiliado(af)
        assert (af.saldo_aportaciones, af.saldo_depositos) == (s["aportaciones"], s["depositos"])


@pytest.mark.parametrize("monto", ["0", "-10", "10.001", "1000000000000"])
def test_montos_invalidos(afiliado, mov, monto):
    with pytest.raises(ValidationError) as e:
        mov(afiliado, "APO", monto)
    assert "monto" in e.value.message_dict
    assert MovimientoAfiliado.objects.count() == 0


def test_afiliado_inexistente(mov, afiliado):
    afiliado.pk = 999999
    with pytest.raises(ValidationError) as e:
        mov(afiliado, "APO", 10)
    assert "afiliado" in e.value.message_dict


def test_fecha_futura_y_anterior_al_ingreso(nuevo_afiliado, mov, hoy):
    a = nuevo_afiliado(fecha_ingreso=dias_atras(10))
    with pytest.raises(ValidationError):
        mov(a, "APO", 10, fecha=hoy + timedelta(days=1))
    with pytest.raises(ValidationError):
        mov(a, "APO", 10, fecha=dias_atras(11))


def test_metodo_y_cuenta_coherentes(afiliado, mov, banco, caja):
    with pytest.raises(ValidationError) as e:  # efectivo en banco
        mov(afiliado, "APO", 10, cuenta_fondo=banco)
    assert "cuenta_fondo" in e.value.message_dict
    with pytest.raises(ValidationError) as e:  # transferencia sin referencia
        mov(afiliado, "APO", 10, metodo_pago=MetodoPago.TRANSFERENCIA, cuenta_fondo=banco)
    assert "referencia" in e.value.message_dict
    with pytest.raises(ValidationError):  # transferencia a caja
        mov(afiliado, "APO", 10, metodo_pago=MetodoPago.TRANSFERENCIA, cuenta_fondo=caja, referencia="T-1")
    ok = mov(afiliado, "APO", 10, metodo_pago=MetodoPago.TRANSFERENCIA, cuenta_fondo=banco, referencia="T-1")
    assert ok.pk


def test_tipo_o_cuenta_inactivos(afiliado, mov, tipos, caja):
    caja.activa = False
    caja.save()
    with pytest.raises(ValidationError):
        mov(afiliado, "APO", 10)


def test_afiliado_inactivo_no_admite_movimientos(afiliado, mov, admin_caune, hoy, tesorero):
    cambiar_estado(afiliado, estado_nuevo="INACTIVO", fecha_efectiva=hoy, motivo="Prueba de inactivación",
                   usuario=admin_caune)
    with pytest.raises(ValidationError):
        mov(afiliado, "APO", 10)
    # con el parámetro habilitado sí se permite
    parametros.actualizar(Parametro.objects.get(clave="afiliados.permitir_movimientos_inactivos"), "true",
                          admin_caune, "Autorizado por la directiva en acta 1")
    assert mov(afiliado, "APO", 10).pk


# ------------------------------------------------------------------ retiros

def test_retiro_dentro_del_saldo(afiliado, mov):
    mov(afiliado, "DEP", 500, fecha=dias_atras(5))
    mov(afiliado, "RDEP", 200)
    assert services.saldos_afiliado(afiliado)["depositos"] == D("300.00")


def test_retiro_mayor_al_saldo_rechazado(afiliado, mov):
    mov(afiliado, "DEP", 100)
    mov(afiliado, "APO", 1000)  # las aportaciones no respaldan retiros de depósitos
    with pytest.raises(ValidationError) as e:
        mov(afiliado, "RDEP", "100.01")
    assert "monto" in e.value.message_dict


def test_retiro_con_fecha_anterior_que_deja_saldo_negativo(afiliado, mov):
    mov(afiliado, "DEP", 100, fecha=dias_atras(10))
    mov(afiliado, "RDEP", 100, fecha=dias_atras(5))
    mov(afiliado, "DEP", 100, fecha=dias_atras(1))
    # Al día -5 el saldo era 0: un retiro fechado el día -7 lo dejaría negativo ese día.
    with pytest.raises(ValidationError):
        mov(afiliado, "RDEP", 50, fecha=dias_atras(7))


def test_retiro_de_aportaciones_no_permitido_por_defecto(admin_caune):
    from apps.aportaciones.forms import TipoMovimientoForm
    form = TipoMovimientoForm(data={"codigo": "RAP", "nombre": "Retiro aportación", "clase": "APORTACION",
                                    "naturaleza": "SALIDA", "activo": True})
    assert not form.is_valid()


# ------------------------------------------------------------------ duplicados e inmutabilidad

def test_misma_clave_no_registra_dos_veces(afiliado, mov):
    clave = uuid.uuid4()
    m1 = mov(afiliado, "APO", 100, clave_idempotencia=clave)
    m2 = mov(afiliado, "APO", 100, clave_idempotencia=clave)
    assert m1.pk == m2.pk
    assert MovimientoAfiliado.objects.count() == 1


def test_movimiento_confirmado_no_se_edita_ni_elimina(afiliado, mov):
    m = mov(afiliado, "APO", 100)
    m.monto = D("999")
    with pytest.raises(ValidationError):
        m.save()
    with pytest.raises(ValidationError):
        m.delete()
    with pytest.raises(ValidationError):
        MovimientoAfiliado.objects.all().delete()
    with pytest.raises(ValidationError):
        MovimientoAfiliado.objects.update(monto=1)
    m.refresh_from_db()
    assert m.monto == D("100.00")


def test_base_de_datos_rechaza_monto_no_positivo(afiliado, tipos, caja, tesorero, hoy):
    with pytest.raises(IntegrityError), transaction.atomic():
        MovimientoAfiliado.objects.bulk_create([MovimientoAfiliado(
            numero_operacion="X-1", afiliado=afiliado, tipo=tipos["APO"], fecha=hoy, monto=D("0"),
            metodo_pago="EFECTIVO", cuenta_fondo=caja, registrado_por=tesorero)])


def test_base_de_datos_rechaza_anulacion_incoherente(afiliado, tipos, caja, tesorero, hoy):
    with pytest.raises(IntegrityError), transaction.atomic():
        MovimientoAfiliado.objects.bulk_create([MovimientoAfiliado(
            numero_operacion="X-2", afiliado=afiliado, tipo=tipos["APO"], fecha=hoy, monto=D("5"),
            metodo_pago="EFECTIVO", cuenta_fondo=caja, registrado_por=tesorero, estado="ANULADO")])


# ------------------------------------------------------------------ anulación

def test_anulacion_excluye_del_saldo_y_audita(afiliado, mov, supervisor):
    m = mov(afiliado, "APO", 100)
    mov(afiliado, "APO", 50)
    services.anular_movimiento(m, motivo="Monto digitado incorrectamente", usuario=supervisor)
    m.refresh_from_db()
    assert m.estado == "ANULADO" and m.anulado_por == supervisor
    assert services.saldos_afiliado(afiliado)["aportaciones"] == D("50.00")
    assert HistorialAuditoria.objects.filter(accion="ANULAR", entidad_id=str(m.pk)).exists()
    with pytest.raises(ValidationError):
        services.anular_movimiento(m, motivo="Otra vez el mismo motivo", usuario=supervisor)


def test_anulacion_reglas(afiliado, mov, supervisor, presidente, admin_caune):
    m = mov(afiliado, "APO", 100, usuario=admin_caune)
    with pytest.raises(ValidationError):  # sin permiso
        services.anular_movimiento(m, motivo="Motivo suficientemente largo", usuario=presidente)
    with pytest.raises(ValidationError):  # motivo corto
        services.anular_movimiento(m, motivo="error", usuario=supervisor)
    with pytest.raises(ValidationError):  # el mismo usuario que registró
        services.anular_movimiento(m, motivo="Motivo suficientemente largo", usuario=admin_caune)


def test_no_se_anula_deposito_que_respalda_un_retiro(afiliado, mov, supervisor):
    deposito = mov(afiliado, "DEP", 100, fecha=dias_atras(3))
    retiro = mov(afiliado, "RDEP", 80)
    with pytest.raises(ValidationError):
        services.anular_movimiento(deposito, motivo="Depósito registrado por error", usuario=supervisor)
    services.anular_movimiento(retiro, motivo="Retiro registrado por error", usuario=supervisor)
    services.anular_movimiento(deposito, motivo="Depósito registrado por error", usuario=supervisor)
    assert services.saldos_afiliado(afiliado)["depositos"] == D("0.00")


# ------------------------------------------------------------------ estado de cuenta

def test_estado_de_cuenta_cuadra_con_saldos(afiliado, mov, supervisor):
    mov(afiliado, "APO", 1000, fecha=dias_atras(60))
    mov(afiliado, "DEP", 300, fecha=dias_atras(40))
    anulado = mov(afiliado, "APO", 77, fecha=dias_atras(35))
    services.anular_movimiento(anulado, motivo="Prueba de exclusión de anulados", usuario=supervisor)
    mov(afiliado, "APO", 500, fecha=dias_atras(20))
    mov(afiliado, "RDEP", 100, fecha=dias_atras(10))

    completo = services.estado_cuenta(afiliado)
    assert completo.saldo_final == services.saldos_afiliado(afiliado)
    assert completo.saldo_final["total"] == D("1700.00")
    assert len(completo.lineas) == 4  # el anulado no aparece

    periodo = services.estado_cuenta(afiliado, desde=dias_atras(30), hasta=dias_atras(5))
    assert periodo.saldo_inicial == {"aportaciones": D("1000.00"), "depositos": D("300.00"), "total": D("1300.00")}
    assert periodo.totales["entradas_aportaciones"] == D("500")
    assert periodo.totales["retiros_depositos"] == D("100")
    assert periodo.saldo_final == services.saldos_afiliado(afiliado, hasta=dias_atras(5))
    with pytest.raises(ValidationError):
        services.estado_cuenta(afiliado, desde=dias_atras(1), hasta=dias_atras(2))


def test_numeracion_sin_huecos_ni_repeticiones(afiliado, mov):
    numeros = [mov(afiliado, "APO", 1).numero_operacion for _ in range(5)]
    assert numeros == [f"OP-{i:06d}" for i in range(1, 6)]


def test_tipo_con_movimientos_bloquea_clase(afiliado, mov, tipos):
    from apps.aportaciones.forms import TipoMovimientoForm
    mov(afiliado, "DEP", 10)
    form = TipoMovimientoForm(instance=tipos["DEP"])
    assert form.fields["clase"].disabled and form.fields["naturaleza"].disabled
    with pytest.raises(ValidationError):
        tipos["DEP"].delete()
