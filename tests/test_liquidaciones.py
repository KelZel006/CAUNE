"""Liquidación de un afiliado que se retira: devolución de lo suyo, cobro de sus deudas, baja y anulación."""
from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.aportaciones import services as ms
from apps.aportaciones.services import saldos_afiliado
from apps.caja import services as cs
from apps.caja.models import CategoriaCaja
from apps.core.models import Parametro
from apps.distribucion import services as ds
from apps.liquidaciones import services as ls
from apps.prestamos import services as ps
from apps.prestamos.models import Prestamo
from apps.reportes import financieros as fin


@pytest.fixture
def socio(sin_mora, tesorero, admin_caune, nuevo_afiliado, mov, nuevo_prestamo, caja, hoy):
    """Afiliado con 5,000 de aportaciones, 800 de depósitos, un préstamo de 1,000 y una ganancia aprobada."""
    otro = nuevo_afiliado(nombres="Otro")
    mov(otro, "APO", 5000, fecha=hoy - timedelta(days=60))
    a = nuevo_afiliado(nombres="Socio")
    mov(a, "APO", 5000, fecha=hoy - timedelta(days=60))
    mov(a, "DEP", 800, fecha=hoy - timedelta(days=30))
    nuevo_prestamo(a, monto="1000", plazo=2)
    cs.registrar_movimiento(tipo="INGRESO", fecha=hoy - timedelta(days=1), concepto="Intereses", monto=D("400"),
                            metodo_pago="EFECTIVO", cuenta_fondo=caja, usuario=tesorero,
                            categoria=CategoriaCaja.objects.get(nombre="Intereses bancarios"))
    ds.aprobar(ds.crear_distribucion(desde=hoy - timedelta(days=9), hasta=hoy, usuario=tesorero), usuario=admin_caune)
    return a


def test_calculo_de_haberes_y_deudas(socio):
    c = ls.calcular(socio)
    deuda = ps.resumen(socio.prestamos.get()).total_pendiente  # capital + intereses del cuadro
    assert (c["aportaciones"], c["depositos"]) == (D("5000.00"), D("800.00"))
    assert c["ganancias"] == D("200.00")  # mitad de 400: aporta lo mismo que el otro afiliado
    assert c["deuda_prestamos"] == deuda == D("1015.02")
    assert c["neto"] == D("5000.00") + D("800.00") + D("200.00") - deuda
    assert c["bloqueos"] == []


def test_ejecutar_liquida_y_da_de_baja(socio, tesorero, admin_caune, caja, hoy):
    dinero_antes = cs.saldo(caja)
    liq = ls.crear(socio, motivo="Renuncia voluntaria por cambio de domicilio", usuario=tesorero)
    with pytest.raises(ValidationError):  # quien la calcula no la aprueba
        ls.ejecutar(liq, usuario=tesorero, cuenta_fondo=caja, metodo_pago="EFECTIVO")
    liq = ls.ejecutar(liq, usuario=admin_caune, cuenta_fondo=caja, metodo_pago="EFECTIVO")
    socio.refresh_from_db()
    assert liq.estado == "EJECUTADA" and not socio.activo
    assert saldos_afiliado(socio)["total"] == D("0.00")
    p = socio.prestamos.get()
    assert p.estado == Prestamo.Estado.PAGADO and ps.resumen(p).total_pendiente == 0
    assert socio.pagos_ganancia.get().monto == D("200.00")
    # Solo sale de la caja el neto: el préstamo se compensa con sus haberes.
    assert cs.saldo(caja) == dinero_antes - liq.neto
    assert fin.situacion(hoy)["diferencia"] == D("0.00")
    # Lo que la liquidación generó no se anula por separado.
    rapo = liq.movimientos.get(tipo__codigo="RAPO")
    with pytest.raises(ValidationError) as e:
        ms.anular_movimiento(rapo, usuario=tesorero, motivo="Intento de anular solo esto")
    assert liq.numero in str(e.value)
    # Un afiliado dado de baja no admite movimientos.
    with pytest.raises(ValidationError):
        ls.crear(socio, motivo="Segunda liquidación imposible", usuario=tesorero)


def test_anular_revierte_todo(socio, tesorero, admin_caune, supervisor, caja, hoy):
    dinero_antes = cs.saldo(caja)
    saldos_antes = saldos_afiliado(socio)
    liq = ls.ejecutar(ls.crear(socio, motivo="Renuncia voluntaria presentada", usuario=tesorero),
                      usuario=admin_caune, cuenta_fondo=caja, metodo_pago="EFECTIVO")
    ls.anular(liq, usuario=supervisor, motivo="El afiliado desistió de retirarse")
    socio.refresh_from_db()
    assert socio.activo and saldos_afiliado(socio) == saldos_antes
    assert socio.prestamos.get().estado == Prestamo.Estado.VIGENTE
    assert not socio.pagos_ganancia.filter(estado="CONFIRMADO").exists()
    assert cs.saldo(caja) == dinero_antes
    # Ya se puede volver a liquidar.
    assert ls.crear(socio, motivo="Ahora sí se retira definitivamente", usuario=tesorero).estado == "CALCULADA"


def test_bloqueos(sin_mora, tesorero, admin_caune, nuevo_afiliado, mov, nuevo_prestamo, caja, hoy):
    a = nuevo_afiliado()
    mov(a, "APO", 300, fecha=hoy - timedelta(days=60))
    nuevo_prestamo(a, monto="1000", plazo=2)
    c = ls.calcular(a)
    assert c["neto"] < 0 and any("deudas superan" in b for b in c["bloqueos"])
    liq = ls.crear(a, motivo="Quiere retirarse pero debe más", usuario=tesorero)
    with pytest.raises(ValidationError):
        ls.ejecutar(liq, usuario=admin_caune, cuenta_fondo=caja, metodo_pago="EFECTIVO")


def test_si_cambian_los_saldos_hay_que_recalcular(socio, tesorero, admin_caune, mov, caja):
    liq = ls.crear(socio, motivo="Renuncia voluntaria presentada", usuario=tesorero)
    mov(socio, "DEP", 100)
    with pytest.raises(ValidationError) as e:
        ls.ejecutar(liq, usuario=admin_caune, cuenta_fondo=caja, metodo_pago="EFECTIVO")
    assert "Recalcule" in str(e.value)
    liq = ls.recalcular(liq, usuario=tesorero)
    assert liq.depositos == D("900.00")
    assert ls.ejecutar(liq, usuario=admin_caune, cuenta_fondo=caja, metodo_pago="EFECTIVO").estado == "EJECUTADA"


def test_sin_efectivo_suficiente_no_se_ejecuta_nada(socio, tesorero, admin_caune, caja, banco):
    liq = ls.crear(socio, motivo="Renuncia voluntaria presentada", usuario=tesorero)
    with pytest.raises(ValidationError):  # el banco está vacío
        ls.ejecutar(liq, usuario=admin_caune, cuenta_fondo=banco, metodo_pago="TRANSFERENCIA", referencia="T-9")
    socio.refresh_from_db()
    assert socio.activo and saldos_afiliado(socio)["aportaciones"] == D("5000.00")


def test_la_devolucion_de_aportaciones_no_se_registra_a_mano(socio, mov):
    with pytest.raises(ValidationError):
        mov(socio, "RAPO", 100)


def test_flujo_por_la_web(client, socio, tesorero, admin_caune, presidente, caja):
    client.force_login(tesorero)
    assert "Liquidar y dar de baja" in client.get(reverse("afiliados:detalle", args=[socio.pk])).content.decode()
    r = client.get(reverse("liquidaciones:crear", args=[socio.pk]))
    assert r.status_code == 200 and r.context["c"]["neto"] == ls.calcular(socio)["neto"]
    r = client.post(reverse("liquidaciones:crear", args=[socio.pk]), {"motivo": "Renuncia voluntaria presentada"})
    liq = socio.liquidaciones.get()
    assert r.status_code == 302
    client.force_login(admin_caune)
    r = client.post(reverse("liquidaciones:ejecutar", args=[liq.pk]),
                    {"cuenta_fondo": caja.pk, "metodo_pago": "EFECTIVO", "confirmar": "on"})
    assert r.status_code == 302
    liq.refresh_from_db()
    assert liq.estado == "EJECUTADA"
    pdf = client.get(reverse("liquidaciones:detalle", args=[liq.pk]) + "?formato=pdf")
    assert pdf.content.startswith(b"%PDF")
    assert client.get(reverse("liquidaciones:lista")).status_code == 200
    client.force_login(presidente)
    assert client.get(reverse("liquidaciones:detalle", args=[liq.pk])).status_code == 200
    assert client.get(reverse("liquidaciones:crear", args=[socio.pk])).status_code == 403


def test_parametro_de_doble_persona(socio, tesorero, caja):
    Parametro.objects.filter(clave="afiliados.liquidacion_requiere_otro_usuario").update(valor="false")
    liq = ls.crear(socio, motivo="Renuncia voluntaria presentada", usuario=tesorero)
    assert ls.ejecutar(liq, usuario=tesorero, cuenta_fondo=caja, metodo_pago="EFECTIVO").estado == "EJECUTADA"


@pytest.fixture
def aval_con_externo(tesorero, nuevo_afiliado, mov, caja, fondear, hoy):
    """Afiliado con 2,000 de aportaciones que avala un préstamo externo de 500, ya desembolsado."""
    aval = nuevo_afiliado(nombres="Aval")
    mov(aval, "APO", 2000, fecha=hoy - timedelta(days=60))
    p = ps.aprobar_prestamo(usuario=tesorero, tipo_prestatario="EXTERNO", monto_solicitado="500",
                            monto_aprobado="500", plazo=1, metodo_amortizacion="CUOTA_FIJA",
                            fecha_aprobacion=hoy - timedelta(days=5), fecha_primer_vencimiento=hoy + timedelta(days=25),
                            afiliado_responsable=aval,
                            externo={"nombre_completo": "Tercero Ficticio", "identidad": "8888199000011"})
    fondear(caja, p.monto_aprobado, hoy - timedelta(days=5))
    p = ps.desembolsar(p, usuario=tesorero, fecha=hoy - timedelta(days=5), cuenta=caja, metodo_pago="EFECTIVO")
    return aval, p


def test_prestamos_de_terceros_se_descuentan_si_se_decide(sin_mora, tesorero, admin_caune, aval_con_externo, caja):
    aval, externo = aval_con_externo
    deuda_externo = ps.resumen(externo).total_pendiente
    # Sin descontar: no bloquea, solo avisa, y el préstamo del tercero sigue vigente.
    c = ls.calcular(aval)
    assert c["bloqueos"] == [] and any(externo.numero in a for a in c["avisos"])
    assert c["neto"] == D("2000.00") and c["deuda_prestamos"] == 0
    # Descontando: se le resta lo que debe el tercero.
    c = ls.calcular(aval, descontar_avalados=True)
    assert c["deuda_prestamos"] == deuda_externo and c["neto"] == D("2000.00") - deuda_externo
    liq = ls.crear(aval, motivo="Renuncia voluntaria presentada", usuario=tesorero, descontar_avalados=True)
    ls.ejecutar(liq, usuario=admin_caune, cuenta_fondo=caja, metodo_pago="EFECTIVO")
    externo.refresh_from_db()
    assert externo.estado == Prestamo.Estado.PAGADO


def test_cambiar_la_decision_al_recalcular(sin_mora, tesorero, admin_caune, aval_con_externo, caja):
    aval, externo = aval_con_externo
    liq = ls.crear(aval, motivo="Renuncia voluntaria presentada", usuario=tesorero)
    assert liq.neto == D("2000.00")
    liq = ls.recalcular(liq, usuario=tesorero, descontar_avalados=True)
    assert liq.descontar_avalados and liq.neto == D("2000.00") - ps.resumen(externo).total_pendiente
    ls.ejecutar(liq, usuario=admin_caune, cuenta_fondo=caja, metodo_pago="EFECTIVO")
    externo.refresh_from_db()
    assert externo.estado == Prestamo.Estado.PAGADO


def test_sin_descontar_el_prestamo_del_tercero_sigue_vigente(sin_mora, tesorero, admin_caune, aval_con_externo, caja,
                                                             client, fondear, hoy):
    aval, externo = aval_con_externo
    fondear(caja, D("2000"), hoy)  # sin descontar se le entregan los 2,000 completos
    client.force_login(tesorero)
    r = client.get(reverse("liquidaciones:crear", args=[aval.pk]))
    assert "descontar_avalados" in r.context["form"].fields and r.context["c_descontando"]["deuda_prestamos"] > 0
    client.post(reverse("liquidaciones:crear", args=[aval.pk]), {"motivo": "Renuncia voluntaria presentada"})
    liq = aval.liquidaciones.get()
    assert not liq.descontar_avalados
    ls.ejecutar(liq, usuario=admin_caune, cuenta_fondo=caja, metodo_pago="EFECTIVO")
    externo.refresh_from_db()
    aval.refresh_from_db()
    assert externo.estado == Prestamo.Estado.VIGENTE and not aval.activo


def test_distribucion_en_borrador_solo_avisa(sin_mora, tesorero, nuevo_afiliado, mov, hoy):
    a = nuevo_afiliado()
    mov(a, "APO", 1000, fecha=hoy - timedelta(days=60))
    ds.crear_distribucion(desde=hoy - timedelta(days=9), hasta=hoy, usuario=tesorero)
    c = ls.calcular(a)
    assert c["bloqueos"] == [] and any("sin aprobar" in x for x in c["avisos"])
