import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.core import parametros
from apps.core.models import HistorialAuditoria, HistorialParametro, Parametro, Secuencia
from apps.core.roles import ROLES


def test_roles_iniciales_creados():
    assert set(Group.objects.values_list("name", flat=True)) == set(ROLES)


def test_parametro_que_afecta_calculos_exige_motivo_y_guarda_historial(admin_caune):
    p = Parametro.objects.get(clave="movimientos.anulacion_requiere_otro_usuario")
    with pytest.raises(ValidationError):
        parametros.actualizar(p, "false", admin_caune, "")
    parametros.actualizar(p, "false", admin_caune, "Directiva autoriza control simple")
    assert parametros.obtener("movimientos.anulacion_requiere_otro_usuario") is False
    h = HistorialParametro.objects.get(parametro=p)
    assert (h.valor_anterior, h.valor_nuevo, h.cambiado_por) == ("true", "false", admin_caune)
    assert HistorialAuditoria.objects.filter(accion="CONFIGURAR", entidad="core.Parametro").exists()


def test_parametro_requiere_permiso(presidente):
    with pytest.raises(ValidationError):
        parametros.actualizar(Parametro.objects.get(clave="coop.rtn"), "08019999999999", presidente)


def test_numeracion_no_retrocede(client, admin_caune, afiliado, mov):
    mov(afiliado, "APO", 1)
    sec = Secuencia.objects.get(prefijo="OP")
    client.force_login(admin_caune)
    r = client.post(reverse("core:secuencia_editar", args=[sec.pk]),
                    {"descripcion": sec.descripcion, "relleno": 6, "siguiente": 1})
    assert r.status_code == 200 and "siguiente" in r.context["form"].errors


def test_auditoria_inmutable(afiliado):
    registro = HistorialAuditoria.objects.first()
    registro.descripcion = "alterado"
    with pytest.raises(ValidationError):
        registro.save()
    with pytest.raises(ValidationError):
        registro.delete()
    with pytest.raises(ValidationError):
        HistorialAuditoria.objects.all().delete()


def test_crear_usuario_con_rol_desde_la_app(client, admin_caune):
    client.force_login(admin_caune)
    r = client.post(reverse("core:usuario_crear"), {
        "username": "nuevo.presidente", "first_name": "Nuevo", "last_name": "Presidente", "email": "",
        "roles": [Group.objects.get(name="Presidente").pk], "password1": "Clave-Muy-Segura-2026",
        "password2": "Clave-Muy-Segura-2026"})
    assert r.status_code == 302
    from django.contrib.auth import get_user_model
    u = get_user_model().objects.get(username="nuevo.presidente")
    assert u.has_perm("core.ver_reportes")
    assert not u.has_perm("aportaciones.add_movimientoafiliado")
    assert u.password != "Clave-Muy-Segura-2026" and u.check_password("Clave-Muy-Segura-2026")


def test_contrasena_debil_rechazada(client, admin_caune):
    client.force_login(admin_caune)
    r = client.post(reverse("core:usuario_crear"), {
        "username": "debil", "password1": "12345", "password2": "12345"})
    assert r.status_code == 200 and "password1" in r.context["form"].errors


def test_admin_no_se_desactiva_a_si_mismo(client, admin_caune):
    client.force_login(admin_caune)
    r = client.post(reverse("core:usuario_editar", args=[admin_caune.pk]),
                    {"first_name": "A", "last_name": "B", "email": "", "roles": []})
    assert r.status_code == 200
    admin_caune.refresh_from_db()
    assert admin_caune.is_active
