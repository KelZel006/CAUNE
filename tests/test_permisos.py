"""Los permisos se validan en el servidor: aunque alguien escriba la URL a mano, recibe 403."""
import uuid

import pytest
from django.urls import reverse

from apps.aportaciones.models import MovimientoAfiliado


def test_anonimo_redirigido_al_login(client):
    for url in ("/", "/afiliados/", "/movimientos/", "/reportes/", "/configuracion/usuarios/"):
        r = client.get(url)
        assert r.status_code == 302 and r.url.startswith("/cuenta/ingresar/"), url


def _get(client, usuario, nombre, *args):
    client.force_login(usuario)
    return client.get(reverse(nombre, args=args)).status_code


@pytest.mark.parametrize("vista", [
    "afiliados:lista", "afiliados:crear", "aportaciones:lista", "aportaciones:crear", "reportes:indice",
])
def test_tesorero_accede_a_operacion(client, tesorero, vista):
    assert _get(client, tesorero, vista) == 200


@pytest.mark.parametrize("vista", [
    "core:auditoria", "core:usuarios", "core:roles", "core:parametros", "aportaciones:tipo_crear",
    "core:cuenta_crear", "core:secuencias",
])
def test_tesorero_tiene_acceso_total(client, tesorero, vista):
    assert _get(client, tesorero, vista) == 200


def test_tesorero_no_anula_su_propia_operacion(client, tesorero, afiliado, mov):
    """Acceso total no elimina el control de doble persona: otra persona debe autorizar la anulación."""
    m = mov(afiliado, "APO", 10)
    client.force_login(tesorero)
    r = client.post(reverse("aportaciones:anular", args=[m.pk]), {"motivo": "Intento de autoanulación", "confirmar": "on"})
    assert r.status_code == 200 and "distinto" in str(r.context["form"].errors)
    m.refresh_from_db()
    assert m.estado == "CONFIRMADO"


@pytest.mark.parametrize("vista", [
    "core:dashboard", "afiliados:lista", "reportes:indice", "reportes:afiliados", "reportes:movimientos",
    "aportaciones:lista",
])
def test_presidente_consulta_reportes(client, presidente, vista):
    assert _get(client, presidente, vista) == 200


@pytest.mark.parametrize("vista", [
    "afiliados:crear", "aportaciones:crear", "core:usuarios", "core:auditoria", "core:parametros",
    "core:cuenta_crear",
])
def test_presidente_no_modifica_nada(client, presidente, vista):
    assert _get(client, presidente, vista) == 403


def test_presidente_ve_saldos_financieros(client, presidente, afiliado, mov):
    mov(afiliado, "APO", 300)
    client.force_login(presidente)
    assert client.get(reverse("core:dashboard")).context["financiero"] is True
    assert client.get(reverse("afiliados:estado_cuenta", args=[afiliado.pk])).status_code == 200
    r = client.post(reverse("aportaciones:anular", args=[afiliado.movimientos.get().pk]), {"motivo": "x" * 20})
    assert r.status_code == 403


def test_supervisor_consulta_y_anula_pero_no_registra(client, supervisor, afiliado, mov, caja, tipos, hoy):
    m = mov(afiliado, "APO", 10)
    assert _get(client, supervisor, "core:auditoria") == 200
    assert _get(client, supervisor, "afiliados:estado_cuenta", afiliado.pk) == 200
    assert _get(client, supervisor, "aportaciones:crear") == 403
    r = client.post(reverse("aportaciones:crear"), {
        "clave_idempotencia": uuid.uuid4(), "afiliado": afiliado.pk, "tipo": tipos["APO"].pk, "fecha": hoy.isoformat(),
        "monto": "50", "metodo_pago": "EFECTIVO", "cuenta_fondo": caja.pk})
    assert r.status_code == 403
    assert MovimientoAfiliado.objects.count() == 1
    r = client.post(reverse("aportaciones:anular", args=[m.pk]), {"motivo": "Error de digitación", "confirmar": "on"})
    assert r.status_code == 302
    m.refresh_from_db()
    assert m.estado == "ANULADO"


def test_encargado_prestamos_solo_consulta_afiliados(client, prestamos, afiliado):
    assert _get(client, prestamos, "afiliados:lista") == 200
    assert _get(client, prestamos, "afiliados:crear") == 403
    assert _get(client, prestamos, "afiliados:cambiar_estado", afiliado.pk) == 403
    assert _get(client, prestamos, "aportaciones:lista") == 403
    assert _get(client, prestamos, "reportes:indice") == 403


def test_usuario_sin_rol_solo_ve_panel_basico(client, sin_rol):
    client.force_login(sin_rol)
    r = client.get(reverse("core:dashboard"))
    assert r.status_code == 200 and "financiero" not in r.context
    assert client.get(reverse("afiliados:lista")).status_code == 403


def test_administrador_accede_a_configuracion(client, admin_caune):
    for vista in ("core:usuarios", "core:roles", "core:parametros", "core:cuentas", "core:secuencias",
                  "aportaciones:tipos", "core:auditoria"):
        assert _get(client, admin_caune, vista) == 200, vista


def test_bloqueo_por_intentos_fallidos(client, tesorero):
    for _ in range(5):
        client.post(reverse("login"), {"username": "tesorero", "password": "incorrecta"})
    r = client.post(reverse("login"), {"username": "tesorero", "password": "Prueba-segura-123"})
    assert r.status_code == 429
    assert "_auth_user_id" not in client.session
