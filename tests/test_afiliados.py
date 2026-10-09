from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError

from apps.afiliados import services
from apps.afiliados.forms import AfiliadoForm
from apps.afiliados.models import Afiliado
from apps.aportaciones.models import MovimientoAfiliado
from apps.core.models import HistorialAuditoria

from .conftest import dias_atras


def datos(**extra):
    base = {"nombres": "Ana", "apellidos": "Prueba", "identidad": "9999000000001", "telefono": "9999-0000",
            "direccion": "Ficticia", "fecha_ingreso": dias_atras(10)}
    base.update(extra)
    return base


def test_crear_asigna_codigo_correlativo_y_audita(tesorero):
    a1 = services.crear_afiliado(datos(), tesorero)
    a2 = services.crear_afiliado(datos(identidad="9999000000002"), tesorero)
    assert (a1.codigo, a2.codigo) == ("AF-0001", "AF-0002")
    assert a1.estado == Afiliado.Estado.ACTIVO
    assert a1.creado_por == tesorero
    assert HistorialAuditoria.objects.filter(entidad="afiliados.Afiliado", entidad_id=str(a1.pk), accion="CREAR").exists()


def test_identidad_duplicada_rechazada(tesorero):
    services.crear_afiliado(datos(), tesorero)
    with pytest.raises(ValidationError) as e:
        services.crear_afiliado(datos(nombres="Otro"), tesorero)
    assert "identidad" in e.value.message_dict


def test_formulario_normaliza_identidad_y_nombres():
    form = AfiliadoForm(data={**datos(identidad="0801-1990-12345", nombres="  ana   maría "),
                              "fecha_ingreso": dias_atras(1).isoformat()})
    assert form.is_valid(), form.errors
    assert form.cleaned_data["identidad"] == "0801199012345"
    assert form.cleaned_data["nombres"] == "ana maría"


@pytest.mark.parametrize("identidad", ["123", "0801-1990-1234X", "08011990123456"])
def test_formulario_rechaza_identidad_invalida(identidad):
    form = AfiliadoForm(data={**datos(identidad=identidad), "fecha_ingreso": dias_atras(1).isoformat()})
    assert not form.is_valid()
    assert "identidad" in form.errors


def test_registro_incompleto_rechazado():
    form = AfiliadoForm(data={"nombres": "", "apellidos": "", "identidad": "", "fecha_ingreso": ""})
    assert not form.is_valid()
    assert {"nombres", "apellidos", "identidad", "fecha_ingreso"} <= set(form.errors)


def test_fecha_ingreso_futura_rechazada(tesorero, hoy):
    with pytest.raises(ValidationError):
        services.crear_afiliado(datos(fecha_ingreso=hoy + timedelta(days=1)), tesorero)


def test_editar_audita_solo_cambios(afiliado, tesorero):
    services.actualizar_afiliado(afiliado, {"telefono": "3333-4444"}, tesorero)
    afiliado.refresh_from_db()
    assert afiliado.telefono == "3333-4444"
    registro = HistorialAuditoria.objects.filter(accion="MODIFICAR", entidad_id=str(afiliado.pk)).get()
    assert set(registro.datos_despues) == {"telefono"}


def test_fecha_ingreso_no_puede_quedar_despues_de_movimientos(afiliado, mov, tesorero):
    mov(afiliado, "APO", 100, fecha=dias_atras(30))
    with pytest.raises(ValidationError):
        services.actualizar_afiliado(afiliado, {"fecha_ingreso": dias_atras(5)}, tesorero)


def test_inactivar_conserva_historial(afiliado, mov, admin_caune, hoy):
    mov(afiliado, "APO", 500)
    cambio = services.cambiar_estado(afiliado, estado_nuevo="INACTIVO", fecha_efectiva=hoy,
                                     motivo="Retiro voluntario del afiliado", usuario=admin_caune)
    afiliado.refresh_from_db()
    assert afiliado.estado == "INACTIVO"
    assert cambio.estado_anterior == "ACTIVO"
    assert MovimientoAfiliado.objects.filter(afiliado=afiliado).count() == 1
    assert HistorialAuditoria.objects.filter(accion="CAMBIO_ESTADO", entidad_id=str(afiliado.pk)).exists()


def test_inactivar_exige_motivo_y_permiso(afiliado, admin_caune, presidente, hoy):
    with pytest.raises(ValidationError):
        services.cambiar_estado(afiliado, estado_nuevo="INACTIVO", fecha_efectiva=hoy, motivo="corto",
                                usuario=admin_caune)
    with pytest.raises(ValidationError):  # el presidente solo consulta
        services.cambiar_estado(afiliado, estado_nuevo="INACTIVO", fecha_efectiva=hoy,
                                motivo="Motivo suficientemente largo", usuario=presidente)


def test_reactivar(afiliado, admin_caune, hoy):
    services.cambiar_estado(afiliado, estado_nuevo="INACTIVO", fecha_efectiva=hoy, motivo="Motivo de prueba 1",
                            usuario=admin_caune)
    services.cambiar_estado(afiliado, estado_nuevo="ACTIVO", fecha_efectiva=hoy, motivo="Motivo de prueba 2",
                            usuario=admin_caune)
    afiliado.refresh_from_db()
    assert afiliado.activo
    assert afiliado.cambios_estado.count() == 2


def test_afiliado_no_se_elimina(afiliado):
    with pytest.raises(ValidationError):
        afiliado.delete()
    assert Afiliado.objects.filter(pk=afiliado.pk).exists()
