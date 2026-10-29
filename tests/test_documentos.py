"""Recibos y comprobantes en PDF: membrete, original y copia, y datos correctos aunque el documento sea antiguo."""
import io
from datetime import timedelta
from decimal import Decimal as D

import pypdf
import pytest
from django.urls import reverse
from openpyxl import load_workbook

from apps.actividades import services as acs
from apps.caja import services as cs
from apps.caja.models import CategoriaCaja
from apps.distribucion import services as ds
from apps.prestamos import services as ps


def _texto(respuesta):
    assert respuesta.status_code == 200 and respuesta.content.startswith(b"%PDF")
    return " ".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(respuesta.content)).pages)


@pytest.fixture
def operaciones(sin_mora, tesorero, admin_caune, nuevo_afiliado, mov, nuevo_prestamo, caja, hoy):
    a = nuevo_afiliado(nombres="Ana")
    apo = mov(a, "APO", 1000, fecha=hoy - timedelta(days=60))
    p = nuevo_prestamo(a, monto="1000", plazo=2)
    pago1, _ = ps.registrar_pago(p, usuario=tesorero, tipo="PAGO", fecha=hoy - timedelta(days=20), monto=D("507.51"),
                                 metodo_pago="EFECTIVO", cuenta_fondo=caja)
    pago2, _ = ps.registrar_pago(p, usuario=tesorero, tipo="PAGO", fecha=hoy - timedelta(days=2), monto=D("200"),
                                 metodo_pago="EFECTIVO", cuenta_fondo=caja)
    egreso, _ = cs.registrar_movimiento(tipo="EGRESO", fecha=hoy, concepto="Papelería", monto=D("50"),
                                        metodo_pago="EFECTIVO", cuenta_fondo=caja, usuario=tesorero,
                                        categoria=CategoriaCaja.objects.get(nombre="Gastos administrativos"))
    act = acs.crear_actividad({"nombre": "Rifa", "fecha_inicio": hoy - timedelta(days=5)}, tesorero)
    ingreso, _ = acs.registrar_movimiento(actividad=act, tipo="INGRESO", fecha=hoy, concepto="Boletos",
                                          monto=D("300"), metodo_pago="EFECTIVO", cuenta_fondo=caja, usuario=tesorero)
    d = ds.aprobar(ds.crear_distribucion(desde=hoy - timedelta(days=9), hasta=hoy, usuario=tesorero),
                   usuario=admin_caune)
    entrega = ds.registrar_pagos(d, afiliados=[a], forma="PAGO", fecha=hoy, cuenta_fondo=caja,
                                 metodo_pago="EFECTIVO", usuario=tesorero)[0]
    return {"apo": apo, "p": p, "pago1": pago1, "pago2": pago2, "egreso": egreso, "ingreso": ingreso,
            "entrega": entrega}


def test_recibos_y_comprobantes_llevan_membrete_original_y_copia(client, tesorero, operaciones):
    o = operaciones
    client.force_login(tesorero)
    documentos = {
        "RECIBO DE APORTACIÓN": reverse("aportaciones:recibo", args=[o["apo"].pk]) + "?formato=pdf",
        "RECIBO DE PAGO DE CUOTA": reverse("prestamos:pago_detalle", args=[o["pago1"].pk]) + "?formato=pdf",
        "COMPROBANTE DE EGRESO": reverse("caja:detalle", args=[o["egreso"].pk]) + "?formato=pdf",
        "COMPROBANTE DE INGRESO DE ACTIVIDAD": reverse("actividades:comprobante", args=[o["ingreso"].pk]),
        "COMPROBANTE DE DESEMBOLSO DE PRÉSTAMO": reverse("prestamos:comprobante_desembolso", args=[o["p"].pk]),
        "COMPROBANTE DE PAGO DE GANANCIAS": reverse("distribucion:comprobante_pago", args=[o["entrega"].pk]),
    }
    for titulo, url in documentos.items():
        texto = _texto(client.get(url))
        assert titulo in texto, url
        assert texto.count("Caja de Ahorro Unión y Esfuerzo") >= 2  # membrete en el original y en la copia
        assert "ORIGINAL" in texto and "COPIA" in texto and "LEMPIRAS" in texto


def test_recibo_antiguo_muestra_el_saldo_de_ese_momento(client, tesorero, operaciones):
    o = operaciones
    # Después del primer pago quedaban 502.49; después del segundo, menos.
    assert ps.saldo_despues_de_pago(o["pago1"]) == D("502.49")
    assert ps.saldo_despues_de_pago(o["pago2"]) < D("502.49")
    client.force_login(tesorero)
    texto = _texto(client.get(reverse("prestamos:pago_detalle", args=[o["pago1"].pk]) + "?formato=pdf"))
    assert "502.49" in texto


def test_reportes_y_estados_llevan_membrete_y_firmas(client, tesorero, operaciones, hoy):
    client.force_login(tesorero)
    texto = _texto(client.get(reverse("reportes:balance") + "?formato=pdf"))
    assert "Caja de Ahorro Unión y Esfuerzo" in texto and "Tesorero" in texto and "Presidente" in texto
    texto = _texto(client.get(reverse("afiliados:estado_cuenta", args=[operaciones["apo"].afiliado.pk])
                              + "?formato=pdf"))
    assert "Estado de cuenta del afiliado" in texto and "Recibí conforme" in texto
    texto = _texto(client.get(reverse("prestamos:detalle", args=[operaciones["p"].pk]) + "?formato=pdf"))
    assert "Cuadro de amortización" in texto and "Prestatario" in texto


def test_excel_listo_para_imprimir(client, tesorero, operaciones):
    client.force_login(tesorero)
    hoja = load_workbook(io.BytesIO(client.get(reverse("reportes:libro_caja") + "?formato=xlsx").content)).active
    assert hoja.print_title_rows == "$5:$5" and hoja.page_setup.fitToWidth == 1
    assert "Caja de Ahorro Unión y Esfuerzo" in hoja.oddHeader.left.text
    assert hoja["A1"].value.startswith("Caja de Ahorro Unión y Esfuerzo (CAUNE)")


def test_pantallas_imprimibles_traen_membrete(client, tesorero, operaciones):
    client.force_login(tesorero)
    html = client.get(reverse("caja:detalle", args=[operaciones["egreso"].pk])).content.decode()
    assert "membrete-impresion" in html and "Comprobante PDF" in html
    # El recibo en pantalla ya tiene su encabezado sellado: no se duplica el membrete.
    html = client.get(reverse("aportaciones:recibo", args=[operaciones["apo"].pk])).content.decode()
    assert "membrete-impresion" not in html and "imprimir-recibo" in html


def test_comprobante_de_desembolso_exige_desembolso(client, tesorero, afiliado, nuevo_prestamo, presidente):
    p = nuevo_prestamo(afiliado, desembolsar=False)
    client.force_login(tesorero)
    assert client.get(reverse("prestamos:comprobante_desembolso", args=[p.pk])).status_code == 302
    client.force_login(presidente)
    assert client.get(reverse("prestamos:comprobante_desembolso", args=[p.pk])).status_code == 302


def test_detalle_del_prestamo_muestra_el_interes_total(client, tesorero, operaciones):
    p = operaciones["p"]
    total = sum((c.interes for c in p.cuotas.all()), D(0))
    client.force_login(tesorero)
    r = client.get(reverse("prestamos:detalle", args=[p.pk]))
    assert r.context["interes_total"] == total
    assert "Interés total del préstamo" in r.content.decode()
