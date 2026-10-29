"""Conciliación bancaria, estado de cuenta con préstamos y ganancias, y edición de prestatarios externos."""
from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.caja import conciliacion as cb
from apps.caja import services as cs
from apps.caja.models import CategoriaCaja, ConciliacionBancaria
from apps.core.models import HistorialAuditoria
from apps.distribucion import services as ds
from apps.prestamos import services as ps
from apps.prestamos.models import PrestatarioExterno


@pytest.fixture
def banco_con_movimientos(afiliado, mov, tesorero, caja, banco, hoy):
    """Banco: transferencia de 3,000 desde la caja, depósito de afiliado de 500 y egreso por cheque de 200."""
    mov(afiliado, "APO", 3000, fecha=hoy - timedelta(days=20))
    cs.registrar_movimiento(tipo="TRANSFERENCIA", fecha=hoy - timedelta(days=15), concepto="Depósito al banco",
                            monto=D("3000"), metodo_pago="DEPOSITO_BANCARIO", cuenta_fondo=caja, cuenta_destino=banco,
                            referencia="BOL-1", usuario=tesorero)
    mov(afiliado, "DEP", 500, fecha=hoy - timedelta(days=2), metodo_pago="DEPOSITO_BANCARIO", cuenta_fondo=banco,
        referencia="BOL-2")
    cs.registrar_movimiento(tipo="EGRESO", fecha=hoy - timedelta(days=1), concepto="Pago de imprenta",
                            monto=D("200"), metodo_pago="CHEQUE", cuenta_fondo=banco, referencia="CH-001",
                            categoria=CategoriaCaja.objects.get(nombre="Gastos administrativos"), usuario=tesorero)
    return banco


def _numeros(conc):
    return {linea.origen: linea.numero for linea, _ in cb.calcular(conc).partidas}


def _todas(conc):
    return [linea.numero for linea, _ in cb.calcular(conc).partidas]


def test_conciliacion_con_partidas_en_transito(banco_con_movimientos, tesorero, hoy):
    banco = banco_con_movimientos
    # El banco solo refleja la transferencia: el depósito y el cheque están en tránsito. Saldo del banco: 3,000.
    conc = cb.crear(cuenta=banco, fecha_corte=hoy, saldo_banco=D("3000.00"), usuario=tesorero)
    r = cb.calcular(conc)
    assert r.saldo_libros == cs.saldo(banco) == D("3300.00")
    # Sin marcar nada, todo está en tránsito: 3,000 + 3,500 de entradas − 200 de salidas = 6,300 frente a 3,300.
    assert len(r.partidas) == 3 and r.diferencia == D("-3000.00")
    transferencia = _numeros(conc)[cs.TRANSFERENCIAS]
    conc = cb.guardar_marcas(conc, numeros=[transferencia], saldo_banco=D("3000.00"), usuario=tesorero)
    r = cb.calcular(conc)
    assert (r.entradas_transito, r.salidas_transito) == (D("500.00"), D("200.00"))
    assert r.saldo_banco_ajustado == D("3300.00") and r.diferencia == 0
    conc = cb.cerrar(conc, usuario=tesorero)
    assert conc.estado == "CERRADA" and conc.saldo_libros == D("3300.00") and conc.conciliadas == [transferencia]
    with pytest.raises(ValidationError):  # el nuevo corte debe ser posterior al último conciliado
        cb.crear(cuenta=banco, fecha_corte=hoy, saldo_banco=D("3300.00"), usuario=tesorero)


def test_no_cierra_si_no_cuadra_y_se_corrige_registrando_la_comision(banco_con_movimientos, tesorero, hoy):
    banco = banco_con_movimientos
    # El banco cobró una comisión de 15 que no está en los libros: su saldo es 3,285 con todo reflejado.
    conc = cb.crear(cuenta=banco, fecha_corte=hoy, saldo_banco=D("3285.00"), usuario=tesorero)
    conc = cb.guardar_marcas(conc, numeros=_todas(conc), saldo_banco=D("3285.00"), usuario=tesorero)
    with pytest.raises(ValidationError) as e:
        cb.cerrar(conc, usuario=tesorero)
    assert "15.00" in str(e.value)
    comision = CategoriaCaja.objects.get(nombre="Comisiones bancarias")
    mov, _ = cs.registrar_movimiento(tipo="EGRESO", fecha=hoy, concepto="Comisión del banco", monto=D("15"),
                                     metodo_pago="DEPOSITO_BANCARIO", cuenta_fondo=banco, referencia="EC-10",
                                     categoria=comision, usuario=tesorero)
    conc = cb.guardar_marcas(conc, numeros=_todas(conc), saldo_banco=D("3285.00"), usuario=tesorero)
    assert mov.numero in conc.conciliadas
    assert cb.cerrar(conc, usuario=tesorero).estado == "CERRADA"


def test_reglas_de_la_conciliacion(banco_con_movimientos, tesorero, supervisor, presidente, caja, hoy):
    banco = banco_con_movimientos
    with pytest.raises(ValidationError):  # solo cuentas bancarias
        cb.crear(cuenta=caja, fecha_corte=hoy, saldo_banco=D("0"), usuario=tesorero)
    with pytest.raises(ValidationError):  # fecha futura
        cb.crear(cuenta=banco, fecha_corte=hoy + timedelta(days=1), saldo_banco=D("0"), usuario=tesorero)
    with pytest.raises(ValidationError):  # el presidente solo consulta
        cb.crear(cuenta=banco, fecha_corte=hoy, saldo_banco=D("0"), usuario=presidente)
    conc = cb.crear(cuenta=banco, fecha_corte=hoy - timedelta(days=10), saldo_banco=D("3000"), usuario=tesorero)
    with pytest.raises(ValidationError):  # una sola en proceso por cuenta
        cb.crear(cuenta=banco, fecha_corte=hoy, saldo_banco=D("0"), usuario=tesorero)
    with pytest.raises(ValidationError):  # no se marcan partidas ajenas
        cb.guardar_marcas(conc, numeros=["OP-999999"], saldo_banco=D("3000"), usuario=tesorero)
    assert [l.origen for l, _ in cb.calcular(conc).partidas] == [cs.TRANSFERENCIAS]  # solo hasta la fecha de corte
    cb.guardar_marcas(conc, numeros=_todas(conc), saldo_banco=D("3000"), usuario=tesorero)
    cb.cerrar(conc, usuario=tesorero)
    segunda = cb.crear(cuenta=banco, fecha_corte=hoy, saldo_banco=D("3300"), usuario=tesorero)
    assert cs.TRANSFERENCIAS not in _numeros(segunda)  # ya conciliada en la primera
    cb.guardar_marcas(segunda, numeros=_todas(segunda), saldo_banco=D("3300"), usuario=tesorero)
    cb.cerrar(segunda, usuario=tesorero)
    with pytest.raises(ValidationError):  # solo se anula la última cerrada
        cb.anular(conc, usuario=supervisor, motivo="Se cerró con el saldo equivocado")
    cb.anular(segunda, usuario=supervisor, motivo="Se cargó el estado de otro mes")
    cb.anular(conc, usuario=supervisor, motivo="Se cerró con el saldo equivocado")
    assert ConciliacionBancaria.objects.filter(estado="ANULADA").count() == 2
    with pytest.raises(ValidationError):
        conc.delete()


def test_conciliacion_por_la_web(client, banco_con_movimientos, tesorero, presidente, hoy):
    banco = banco_con_movimientos
    client.force_login(tesorero)
    r = client.post(reverse("caja:conciliacion_crear"), {"cuenta": banco.pk, "fecha_corte": hoy.isoformat(),
                                                         "saldo_banco": "3300.00"})
    assert r.status_code == 302
    conc = ConciliacionBancaria.objects.get()
    detalle = client.get(reverse("caja:conciliacion", args=[conc.pk]))
    assert detalle.status_code == 200 and len(detalle.context["r"].partidas) == 3
    todas = [l.numero for l, _ in detalle.context["r"].partidas]
    r = client.post(reverse("caja:conciliacion", args=[conc.pk]),
                    {"saldo_banco": "3300.00", "partidas": todas, "accion": "cerrar"})
    assert r.status_code == 302
    conc.refresh_from_db()
    assert conc.estado == "CERRADA"
    assert client.get(reverse("caja:conciliacion", args=[conc.pk]) + "?formato=pdf").content.startswith(b"%PDF")
    assert "Conciliación bancaria" in client.get(reverse("caja:indice")).content.decode()
    client.force_login(presidente)
    assert client.get(reverse("caja:conciliaciones")).status_code == 200
    assert client.get(reverse("caja:conciliacion_crear")).status_code == 403


def test_estado_de_cuenta_muestra_prestamos_y_ganancias(client, sin_mora, tesorero, admin_caune, nuevo_afiliado, mov,
                                                         nuevo_prestamo, caja, hoy):
    a = nuevo_afiliado()
    mov(a, "APO", 2000, fecha=hoy - timedelta(days=90))
    p = nuevo_prestamo(a, monto="1000", plazo=2)
    ps.registrar_pago(p, usuario=tesorero, tipo="PAGO", fecha=hoy - timedelta(days=2), monto=D("507.51"),
                      metodo_pago="EFECTIVO", cuenta_fondo=caja)
    d = ds.aprobar(ds.crear_distribucion(desde=hoy - timedelta(days=9), hasta=hoy, usuario=tesorero),
                   usuario=admin_caune)
    client.force_login(tesorero)
    r = client.get(reverse("afiliados:estado_cuenta", args=[a.pk]))
    fila = r.context["prestamos_ec"][0]
    assert fila["prestamo"] == p and fila["capital_pagado"] == D("497.51") and fila["interes_pagado"] == D("10.00")
    assert fila["saldo_capital"] == ps.resumen(p).saldo_capital == D("502.49")
    assert fila["pendiente_hoy"] == ps.resumen(p).total_pendiente
    assert [g["distribucion"] for g in r.context["ganancias_ec"]] == [d]
    html = r.content.decode()
    assert p.numero in html and d.codigo in html and "Pendiente de entregar" in html
    # Un período anterior al pago no lo cuenta, y el saldo es al corte.
    r = client.get(reverse("afiliados:estado_cuenta", args=[a.pk]) + f"?hasta={(hoy - timedelta(days=5)).isoformat()}")
    fila = r.context["prestamos_ec"][0]
    assert fila["capital_pagado"] == D("0.00") and fila["saldo_capital"] == D("1000.00")
    assert fila["pendiente_hoy"] is None and r.context["ganancias_ec"] == []
    assert client.get(reverse("afiliados:estado_cuenta", args=[a.pk]) + "?formato=pdf").content.startswith(b"%PDF")


def test_editar_prestatario_externo(client, nuevo_afiliado, tesorero, presidente, caja, hoy):
    aval = nuevo_afiliado()
    p = ps.aprobar_prestamo(usuario=tesorero, tipo_prestatario="EXTERNO", monto_solicitado="500",
                            monto_aprobado="500", plazo=1, metodo_amortizacion="CUOTA_FIJA", fecha_aprobacion=hoy,
                            fecha_primer_vencimiento=hoy + timedelta(days=30), afiliado_responsable=aval,
                            externo={"nombre_completo": "Tercero Ficticio", "identidad": "8888199000001"})
    url = reverse("prestamos:editar_externo", args=[p.pk])
    client.force_login(presidente)
    assert client.get(url).status_code == 403
    client.force_login(tesorero)
    assert client.get(url).context["form"].initial["identidad"] == "8888199000001"
    datos = {"nombre_completo": "Tercero Ficticio Corregido", "identidad": "8888199000002", "telefono": "99998888",
             "direccion": "Dirección ficticia", "motivo": "Corrección del nombre según su identidad"}
    assert client.post(url, datos).status_code == 302
    externo = PrestatarioExterno.objects.get()
    assert (externo.nombre_completo, externo.identidad, externo.telefono) == (
        "Tercero Ficticio Corregido", "8888199000002", "99998888")
    assert HistorialAuditoria.objects.filter(descripcion__contains="prestatario externo").exists()
    sin_motivo = client.post(url, {**datos, "motivo": "corto"})
    assert sin_motivo.status_code == 200 and "motivo" in sin_motivo.context["form"].errors
    # La identidad de un afiliado no se puede usar.
    r = client.post(url, {**datos, "identidad": aval.identidad, "motivo": "Prueba de identidad repetida"})
    assert r.status_code == 200 and "identidad" in r.context["form"].errors
