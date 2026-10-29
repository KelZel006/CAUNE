"""Reportes 1 a 22. Usan exactamente los mismos servicios y filtros que los módulos operativos."""
from django.core.exceptions import PermissionDenied
from django.db.models import Count, DecimalField, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from apps.afiliados.forms import FiltroAfiliadosForm
from apps.afiliados.models import Afiliado
from apps.aportaciones import services as mov_services
from apps.aportaciones.forms import FiltroMovimientosForm, aplicar_filtro_movimientos
from apps.aportaciones.models import MovimientoAfiliado, TipoMovimiento
from apps.core.dinero import CERO
from apps.core.exportar import respuesta_pdf, respuesta_xlsx
from apps.core.mixins import PermisoMixin


class IndiceView(PermisoMixin, TemplateView):
    permission_required = "core.ver_reportes"
    template_name = "reportes/indice.html"

    def get_context_data(self, **kwargs):
        from apps.prestamos.models import Prestamo as _P
        return super().get_context_data(
            afiliados=Afiliado.objects.order_by("codigo"),
            prestamos=_P.objects.exclude(estado="ANULADO").select_related("afiliado", "prestatario_externo").order_by("-id"),
            distribuciones=Distribucion.objects.order_by("-fecha_fin", "-id"),
            **kwargs)


class ReporteAfiliadosView(PermisoMixin, TemplateView):
    permission_required = ("core.ver_reportes", "afiliados.view_afiliado")
    template_name = "reportes/afiliados.html"

    def get(self, request, *args, **kwargs):
        form = FiltroAfiliadosForm(request.GET or None)
        qs = Afiliado.objects.order_by("codigo")
        ver_saldos = request.user.has_perm("afiliados.ver_estado_cuenta")
        if ver_saldos:
            qs = mov_services.anotar_saldos(qs)
        if form.is_valid():
            d = form.cleaned_data
            if d.get("estado"):
                qs = qs.filter(estado=d["estado"])
            if d.get("ingreso_desde"):
                qs = qs.filter(fecha_ingreso__gte=d["ingreso_desde"])
            if d.get("ingreso_hasta"):
                qs = qs.filter(fecha_ingreso__lte=d["ingreso_hasta"])
        afiliados = list(qs)
        totales = None
        if ver_saldos:
            for a in afiliados:
                a.saldo_total = a.saldo_aportaciones + a.saldo_depositos
            totales = {"aportaciones": sum((a.saldo_aportaciones for a in afiliados), CERO),
                       "depositos": sum((a.saldo_depositos for a in afiliados), CERO)}
            totales["total"] = totales["aportaciones"] + totales["depositos"]
        ctx = {"form": form, "afiliados": afiliados, "ver_saldos": ver_saldos, "totales": totales}
        formato = request.GET.get("formato")
        if formato == "pdf":
            return respuesta_pdf("reportes/afiliados_pdf.html", ctx, "listado-afiliados", request)
        if formato == "xlsx":
            encabezados = ["Código", "Nombres", "Apellidos", "Identidad", "Teléfono", "Fecha de ingreso", "Estado"]
            filas = [[a.codigo, a.nombres, a.apellidos, a.identidad, a.telefono, a.fecha_ingreso.strftime("%d/%m/%Y"),
                      a.get_estado_display()] + ([a.saldo_aportaciones, a.saldo_depositos] if ver_saldos else [])
                     for a in afiliados]
            if ver_saldos:
                encabezados += ["Saldo aportaciones", "Saldo depósitos"]
            return respuesta_xlsx("Listado de afiliados", encabezados, filas, "listado-afiliados",
                                  columnas_monto=(7, 8) if ver_saldos else (),
                                  totales=(["Totales", "", "", "", "", "", "", totales["aportaciones"],
                                            totales["depositos"]] if ver_saldos else None))
        return render(request, self.template_name, ctx)


class ReporteMovimientosView(PermisoMixin, TemplateView):
    permission_required = ("core.ver_reportes", "aportaciones.view_movimientoafiliado")
    template_name = "reportes/movimientos.html"

    def get(self, request, *args, **kwargs):
        form = FiltroMovimientosForm(request.GET or None)
        qs = MovimientoAfiliado.objects.select_related("afiliado", "tipo", "cuenta_fondo").order_by("fecha", "id")
        if form.is_valid():
            qs = aplicar_filtro_movimientos(qs, form.cleaned_data)
        movimientos = list(qs)
        confirmados = qs.filter(estado=MovimientoAfiliado.Estado.CONFIRMADO)
        resumen = (confirmados.values("tipo__nombre", "tipo__clase", "tipo__naturaleza")
                   .annotate(cantidad=Count("id"), total=Sum("monto")).order_by("tipo__clase", "tipo__nombre"))
        neto = {
            "aportaciones": sum((r["total"] if r["tipo__naturaleza"] == "ENTRADA" else -r["total"]
                                 for r in resumen if r["tipo__clase"] == TipoMovimiento.Clase.APORTACION), CERO),
            "depositos": sum((r["total"] if r["tipo__naturaleza"] == "ENTRADA" else -r["total"]
                              for r in resumen if r["tipo__clase"] == TipoMovimiento.Clase.DEPOSITO), CERO),
        }
        anulados = qs.filter(estado=MovimientoAfiliado.Estado.ANULADO).aggregate(n=Count("id"), total=Sum("monto"))
        ctx = {"form": form, "movimientos": movimientos, "resumen": resumen, "neto": neto, "anulados": anulados}
        formato = request.GET.get("formato")
        if formato == "pdf":
            return respuesta_pdf("reportes/movimientos_pdf.html", ctx, "aportaciones-depositos", request)
        if formato == "xlsx":
            filas = [[m.numero_operacion, m.fecha.strftime("%d/%m/%Y"), m.afiliado.codigo, m.afiliado.nombre_completo,
                      m.tipo.nombre, m.get_metodo_pago_display(), m.cuenta_fondo.nombre, m.referencia,
                      m.get_estado_display(), m.monto_con_signo] for m in movimientos]
            return respuesta_xlsx("Aportaciones y depósitos",
                                  ["Operación", "Fecha", "Código", "Afiliado", "Tipo", "Método", "Caja/cuenta",
                                   "Referencia", "Estado", "Monto (+/−)"],
                                  filas, "aportaciones-depositos", columnas_monto=(9,),
                                  subtitulo=f"Neto confirmado: aportaciones L {neto['aportaciones']:,.2f} · "
                                            f"depósitos L {neto['depositos']:,.2f} (los anulados no suman)")
        return render(request, self.template_name, ctx)


def ir_a_estado_cuenta(request):
    if not request.user.has_perm("afiliados.ver_estado_cuenta"):
        raise PermissionDenied
    pk = request.GET.get("afiliado", "")
    afiliado = get_object_or_404(Afiliado, pk=int(pk) if pk.isdigit() else 0)
    params = request.GET.copy()
    params.pop("afiliado", None)
    destino = reverse("afiliados:estado_cuenta", args=[afiliado.pk])
    return redirect(f"{destino}?{params.urlencode()}" if params else destino)


# =========================================================================== Fase 2: reportes 4 a 9
from datetime import date as _date  # noqa: E402

from django.db.models import Value  # noqa: E402
from django.db.models.functions import Coalesce  # noqa: E402

from apps.actividades import services as act_services  # noqa: E402
from apps.actividades.forms import FiltroPeriodoForm  # noqa: E402
from apps.actividades.models import Actividad, MovimientoActividad  # noqa: E402
from apps.prestamos import services as pre_services  # noqa: E402
from apps.prestamos.forms import FiltroPagosForm, FiltroPrestamosForm  # noqa: E402
from apps.prestamos.models import PagoPrestamo, Prestamo  # noqa: E402
from apps.prestamos.views import aplicar_filtro_prestamos  # noqa: E402


def _reporte(request, *, titulo, nombre, form, encabezados, filas, columnas_monto=(), totales=None, subtitulo="",
             resumen=None, nota=""):
    """Renderiza un reporte tabular en HTML, PDF o Excel con los mismos datos."""
    ctx = dict(titulo=titulo, form=form, encabezados=encabezados, filas=filas, columnas_monto=columnas_monto,
               totales=totales, subtitulo=subtitulo, resumen=resumen, nota=nota)
    formato = request.GET.get("formato")
    if formato == "pdf":
        ctx["columnas_pdf"] = list(zip(encabezados, _anchos_pdf(encabezados, filas, columnas_monto)))
        return respuesta_pdf("reportes/tabla_pdf.html", ctx, nombre, request)
    if formato == "xlsx":
        def plano(v):
            return v.strftime("%d/%m/%Y") if isinstance(v, _date) else v
        return respuesta_xlsx(titulo, encabezados, [[plano(v) for v in f["valores"]] for f in filas], nombre,
                              columnas_monto=columnas_monto, subtitulo=subtitulo,
                              totales=[plano(v) for v in totales] if totales else None)
    return render(request, "reportes/tabla.html", ctx)


def _anchos_pdf(encabezados, filas, columnas_monto):
    """Porcentaje de ancho de cada columna del PDF: montos fijos y el resto según el largo de su texto."""
    fijos = {i: 10.5 for i in columnas_monto}
    largos = {}
    for i, encabezado in enumerate(encabezados):
        if i in fijos:
            continue
        textos = [len(str(f["valores"][i])) for f in filas[:300] if i < len(f["valores"]) and f["valores"][i]]
        promedio = sum(textos) / len(textos) if textos else 0
        largos[i] = min(max(promedio, len(encabezado) * .8, 6), 45) + 3  # holgura para el relleno de la celda
    libre = max(100 - sum(fijos.values()), 20)
    total = sum(largos.values()) or 1
    return [round(fijos[i] if i in fijos else libre * largos[i] / total, 1) for i in range(len(encabezados))]


def _periodo(form):
    if form.is_valid():
        d, h = form.cleaned_data.get("desde"), form.cleaned_data.get("hasta")
        texto = (f"Del {d:%d/%m/%Y} " if d else "Desde el inicio ") + (f"al {h:%d/%m/%Y}" if h else "a la fecha")
        return d, h, texto
    return None, None, "Todo el período"


class ReportePrestamosView(PermisoMixin, TemplateView):
    """4. Préstamos otorgados."""
    permission_required = ("core.ver_reportes", "prestamos.view_prestamo")

    def get(self, request, *args, **kwargs):
        form = FiltroPrestamosForm(request.GET or None)
        qs = pre_services.anotar_saldos(Prestamo.objects.select_related("afiliado", "prestatario_externo",
                                                                        "afiliado_responsable")
                                        .order_by("fecha_aprobacion", "id"))
        if form.is_valid():
            qs = aplicar_filtro_prestamos(qs, form.cleaned_data)
        filas, total_monto, total_saldo = [], CERO, CERO
        for p in qs:
            saldo = p.monto_aprobado - p.capital_pagado if p.estado in ("VIGENTE", "PAGADO") else CERO
            if p.estado != "ANULADO":
                total_monto += p.monto_aprobado
                total_saldo += saldo
            filas.append({"url": reverse("prestamos:detalle", args=[p.pk]), "valores": [
                p.numero, p.fecha_aprobacion, p.prestatario_nombre, p.get_tipo_prestatario_display(),
                p.afiliado_responsable.codigo if p.afiliado_responsable_id else "", p.monto_aprobado,
                f"{p.tasa:.2f} %", p.plazo, p.get_metodo_amortizacion_display(), p.intereses_cobrados, saldo,
                p.get_estado_display()]})
        return _reporte(request, titulo="Préstamos otorgados", nombre="prestamos-otorgados", form=form,
                        encabezados=["Préstamo", "Aprobado", "Prestatario", "Tipo", "Responsable", "Monto",
                                     "Tasa mensual", "Cuotas", "Método", "Intereses cobrados", "Saldo capital", "Estado"],
                        filas=filas, columnas_monto=(5, 9, 10),
                        totales=["Totales (sin anulados)", "", "", "", "", total_monto, "", "", "", "", total_saldo,
                                 ""],
                        resumen=[("Monto otorgado", total_monto), ("Saldo de capital", total_saldo),
                                 ("Préstamos", len(filas))])


class ReporteSaldosPrestamosView(PermisoMixin, TemplateView):
    """7. Saldos pendientes de préstamos vigentes."""
    permission_required = ("core.ver_reportes", "prestamos.view_prestamo")

    def get(self, request, *args, **kwargs):
        form = FiltroPrestamosForm(request.GET or None)
        form.fields.pop("estado")
        qs = Prestamo.objects.filter(estado=Prestamo.Estado.VIGENTE).select_related("afiliado", "prestatario_externo")
        if form.is_valid():
            qs = aplicar_filtro_prestamos(qs, form.cleaned_data)
        filas, t_capital, t_interes, t_mora, en_mora = [], CERO, CERO, CERO, 0
        for p in qs.order_by("numero"):
            r = pre_services.resumen(p)
            t_capital += r.saldo_capital
            t_interes += r.intereses_pendientes
            t_mora += r.mora_pendiente
            atraso = max((c.dias_atraso for c in r.cuotas), default=0)
            en_mora += 1 if atraso else 0
            prox = r.proxima
            filas.append({"url": reverse("prestamos:detalle", args=[p.pk]), "valores": [
                p.numero, p.prestatario_nombre, p.monto_aprobado, r.saldo_capital, r.intereses_pendientes,
                r.mora_pendiente, r.total_pendiente, f"{r.cuotas_pagadas}/{p.plazo}", atraso or "",
                prox.cuota.fecha_vencimiento if prox else None, prox.pendiente if prox else CERO]})
        return _reporte(request, titulo="Saldos pendientes de préstamos", nombre="saldos-prestamos", form=form,
                        encabezados=["Préstamo", "Prestatario", "Monto", "Saldo capital", "Intereses pendientes",
                                     "Mora pendiente", "Total pendiente", "Cuotas pagadas", "Días de atraso",
                                     "Próximo vencimiento", "Próxima cuota"],
                        filas=filas, columnas_monto=(2, 3, 4, 5, 6, 10),
                        totales=["Totales", "", "", t_capital, t_interes, t_mora, t_capital + t_interes + t_mora, "",
                                 "", "", ""],
                        resumen=[("Saldo de capital", t_capital), ("Intereses pendientes", t_interes),
                                 ("Mora pendiente", t_mora), ("Préstamos en mora", en_mora)],
                        nota="Intereses pendientes = intereses del cuadro aprobado aún no cobrados. Mora = capital "
                             "vencido × tasa de mora mensual ÷ 30 por día de atraso, calculada a hoy.")


class ReportePagosView(PermisoMixin, TemplateView):
    """6. Pagos recibidos por préstamo."""
    permission_required = ("core.ver_reportes", "prestamos.view_pagoprestamo")

    def get(self, request, *args, **kwargs):
        form = FiltroPagosForm(request.GET or None)
        dec = DecimalField(max_digits=16, decimal_places=2)
        qs = (PagoPrestamo.objects.select_related("prestamo__afiliado", "prestamo__prestatario_externo")
              .annotate(capital=Coalesce(Sum("aplicaciones__capital"), Value(CERO), output_field=dec),
                        interes=Coalesce(Sum("aplicaciones__interes"), Value(CERO), output_field=dec))
              .order_by("fecha", "id"))
        desde, hasta, texto = _periodo(form)
        if form.is_valid():
            d = form.cleaned_data
            for campo, filtro in (("desde", "fecha__gte"), ("hasta", "fecha__lte"), ("tipo", "tipo"),
                                  ("estado", "estado"), ("prestamo", "prestamo")):
                if d.get(campo):
                    qs = qs.filter(**{filtro: d[campo]})
        filas, t = [], {"monto": CERO, "capital": CERO, "interes": CERO, "mora": CERO, "excedente": CERO}
        for pago in qs:
            if pago.estado == PagoPrestamo.Estado.CONFIRMADO:
                t["monto"] += pago.monto
                t["capital"] += pago.capital
                t["interes"] += pago.interes
                t["mora"] += pago.mora
                t["excedente"] += pago.excedente
            filas.append({"url": reverse("prestamos:pago_detalle", args=[pago.pk]), "valores": [
                pago.numero_recibo, pago.fecha, pago.prestamo.numero, pago.prestamo.prestatario_nombre,
                pago.get_tipo_display(), pago.monto, pago.capital, pago.interes, pago.mora, pago.excedente,
                pago.get_estado_display()]})
        return _reporte(request, titulo="Pagos recibidos por préstamo", nombre="pagos-prestamos", form=form,
                        encabezados=["Recibo", "Fecha", "Préstamo", "Prestatario", "Tipo", "Aplicado", "A capital",
                                     "A intereses", "A mora", "A aportaciones", "Estado"],
                        filas=filas, columnas_monto=(5, 6, 7, 8, 9), subtitulo=texto,
                        totales=["Totales confirmados", "", "", "", "", t["monto"], t["capital"], t["interes"],
                                 t["mora"], t["excedente"], ""],
                        resumen=[("Total cobrado", t["monto"]), ("Capital recuperado", t["capital"]),
                                 ("Intereses cobrados", t["interes"]), ("Mora cobrada", t["mora"])],
                        nota="El capital recuperado no es ganancia; los intereses y la mora cobrados sí son ingreso. "
                             "Lo pagado de más por un afiliado se acredita a sus aportaciones.")


class ReporteMovimientosActividadView(PermisoMixin, TemplateView):
    """8. Ingresos y gastos por actividad económica."""
    permission_required = ("core.ver_reportes", "actividades.view_movimientoactividad")

    def get(self, request, *args, **kwargs):
        form = FiltroPeriodoForm(request.GET or None)
        desde, hasta, texto = _periodo(form)
        qs = MovimientoActividad.objects.select_related("actividad", "subactividad").order_by("actividad__codigo",
                                                                                               "fecha", "id")
        if form.is_valid() and form.cleaned_data.get("actividad"):
            qs = qs.filter(actividad=form.cleaned_data["actividad"])
        if desde:
            qs = qs.filter(fecha__gte=desde)
        if hasta:
            qs = qs.filter(fecha__lte=hasta)
        filas, ingresos, gastos = [], CERO, CERO
        for m in qs:
            if m.confirmado:
                if m.tipo == "INGRESO":
                    ingresos += m.monto
                else:
                    gastos += m.monto
            filas.append({"url": reverse("actividades:detalle", args=[m.actividad_id]), "valores": [
                m.actividad.codigo, m.actividad.nombre, m.subactividad.nombre if m.subactividad else "General",
                m.numero, m.fecha, m.get_tipo_display(), m.concepto, m.monto_con_signo, m.get_estado_display()]})
        return _reporte(request, titulo="Ingresos y gastos por actividad", nombre="ingresos-gastos-actividades",
                        form=form, encabezados=["Código", "Actividad", "Subactividad", "Número", "Fecha", "Tipo",
                                                "Concepto", "Monto (+/−)", "Estado"],
                        filas=filas, columnas_monto=(7,), subtitulo=texto,
                        totales=["Resultado neto (confirmados)", "", "", "", "", "", "", ingresos - gastos, ""],
                        resumen=[("Resultado neto", ingresos - gastos), ("Ingresos", ingresos), ("Gastos", gastos)],
                        nota="Los registros anulados se muestran pero no suman.")


class ReporteResultadosActividadView(PermisoMixin, TemplateView):
    """9. Ganancias y pérdidas por actividad."""
    permission_required = ("core.ver_reportes", "actividades.view_actividad")

    def get(self, request, *args, **kwargs):
        form = FiltroPeriodoForm(request.GET or None)
        desde, hasta, texto = _periodo(form)
        qs = Actividad.objects.order_by("codigo")
        if form.is_valid() and form.cleaned_data.get("actividad"):
            qs = qs.filter(pk=form.cleaned_data["actividad"].pk)
        filas, ti, tg = [], CERO, CERO
        for a in act_services.anotar_resultados(qs, desde, hasta):
            neto = a.ingresos - a.gastos
            ti += a.ingresos
            tg += a.gastos
            filas.append({"url": reverse("actividades:detalle", args=[a.pk]), "valores": [
                a.codigo, a.nombre, a.get_estado_display(), a.ingresos, a.gastos, neto,
                "Ganancia" if neto > 0 else ("Pérdida" if neto < 0 else "Sin resultado")]})
            for f in act_services.resultados_por_subactividad(a, desde, hasta):
                nombre_sub = f["subactividad"].nombre if f["subactividad"] else "General"
                filas.append({"url": "", "valores": ["", f"    · {nombre_sub}", "", f["ingresos"], f["gastos"],
                                                     f["neto"], ""]})
        resultado = "Ganancia" if ti > tg else ("Pérdida" if ti < tg else "")
        return _reporte(request, titulo="Ganancias y pérdidas por actividad", nombre="resultados-actividades",
                        form=form, encabezados=["Código", "Actividad / subactividad", "Estado", "Ingresos", "Gastos",
                                                "Resultado neto", "Resultado"],
                        filas=filas, columnas_monto=(3, 4, 5), subtitulo=texto,
                        totales=["Totales", "", "", ti, tg, ti - tg, resultado],
                        resumen=[("Resultado neto", ti - tg), ("Ingresos", ti), ("Gastos", tg)])


def ir_a_cuadro(request):
    """5. Cuadros de amortización: abre el cuadro del préstamo elegido."""
    if not (request.user.has_perm("core.ver_reportes") and request.user.has_perm("prestamos.view_prestamo")):
        raise PermissionDenied
    pk = request.GET.get("prestamo", "")
    prestamo = get_object_or_404(Prestamo, pk=int(pk) if pk.isdigit() else 0)
    formato = request.GET.get("formato", "")
    destino = reverse("prestamos:detalle", args=[prestamo.pk])
    return redirect(f"{destino}?formato={formato}" if formato in ("pdf", "xlsx") else destino)


# =========================================================================== Fase 3: reportes 10 a 14
from apps.aportaciones.services import totales_generales  # noqa: E402
from apps.caja import services as caja_services  # noqa: E402
from apps.caja.forms import FiltroLibroForm  # noqa: E402
from apps.caja.models import MovimientoCaja  # noqa: E402
from apps.distribucion import services as dist_services  # noqa: E402
from apps.distribucion.models import Distribucion, PagoGanancia  # noqa: E402
from apps.prestamos.models import AplicacionPago  # noqa: E402


def ir_a_ganancias(request):
    """10. Ganancias por afiliado: abre la distribución elegida (en pantalla, PDF o Excel)."""
    if not (request.user.has_perm("core.ver_reportes") and request.user.has_perm("distribucion.view_distribucion")):
        raise PermissionDenied
    pk = request.GET.get("distribucion", "")
    dist = get_object_or_404(Distribucion, pk=int(pk) if pk.isdigit() else 0)
    formato = request.GET.get("formato", "")
    destino = reverse("distribucion:detalle", args=[dist.pk])
    return redirect(f"{destino}?formato={formato}" if formato in ("pdf", "xlsx") else destino)


class ReporteDistribucionesView(PermisoMixin, TemplateView):
    """11. Distribuciones de ganancias."""
    permission_required = ("core.ver_reportes", "distribucion.view_distribucion")

    def get(self, request, *args, **kwargs):
        form = FiltroPeriodoForm(request.GET or None)
        form.fields.pop("actividad")
        desde, hasta, texto = _periodo(form)
        qs = Distribucion.objects.order_by("fecha_inicio", "id")
        if desde:
            qs = qs.filter(fecha_fin__gte=desde)
        if hasta:
            qs = qs.filter(fecha_inicio__lte=hasta)
        filas, t = [], {"resultado": CERO, "reserva": CERO, "total": CERO, "entregado": CERO}
        for d in qs:
            r = dist_services.resumen(d)
            if d.estado in (Distribucion.Estado.APROBADA, Distribucion.Estado.APLICADA):
                for k in t:
                    t[k] += r[k]
            filas.append({"url": reverse("distribucion:detalle", args=[d.pk]), "valores": [
                d.codigo, d.fecha_inicio, d.fecha_fin, d.get_base_calculo_display(), len(r["filas"]), r["resultado"],
                r["reserva"], r["total"], r["entregado"], d.get_estado_display()]})
        return _reporte(request, titulo="Distribuciones de ganancias", nombre="distribuciones", form=form,
                        encabezados=["Código", "Desde", "Hasta", "Base", "Afiliados", "Resultado", "Reserva",
                                     "Repartido", "Entregado", "Estado"],
                        filas=filas, columnas_monto=(5, 6, 7, 8), subtitulo=texto,
                        totales=["Totales aprobadas", "", "", "", "", t["resultado"], t["reserva"], t["total"],
                                 t["entregado"], ""],
                        resumen=[("Repartido", t["total"]), ("Entregado", t["entregado"]),
                                 ("Por entregar", t["total"] - t["entregado"])],
                        nota="Los totales solo suman distribuciones aprobadas o entregadas; los borradores y las "
                             "anuladas se muestran pero no suman.")


class ReporteLibroCajaView(PermisoMixin, TemplateView):
    """12. Libro de caja y bancos."""
    permission_required = ("core.ver_reportes", "caja.view_movimientocaja")

    def get(self, request, *args, **kwargs):
        form = FiltroLibroForm(request.GET or None)
        cuenta = desde = hasta = None
        if form.is_valid():
            cuenta, desde, hasta = (form.cleaned_data.get(k) for k in ("cuenta", "desde", "hasta"))
        libro = caja_services.libro(cuenta, desde, hasta)
        filas = [{"url": "", "valores": [desde, "", "Saldo inicial", "", "", None, None, libro.saldo_inicial]}]
        for f in libro.lineas:
            filas.append({"url": f.url, "valores": [f.fecha, f.numero, f.origen, f.descripcion, f.cuenta.nombre,
                                                     f.entrada or None, f.salida or None, f.saldo]})
        texto = (f"{cuenta.nombre if cuenta else 'Todas las cajas y cuentas'} · "
                 + (f"del {desde:%d/%m/%Y} " if desde else "desde el inicio ") + f"al {libro.hasta:%d/%m/%Y}")
        return _reporte(request, titulo="Libro de caja y bancos", nombre="libro-caja", form=form,
                        encabezados=["Fecha", "Número", "Origen", "Detalle", "Caja o cuenta", "Entrada", "Salida",
                                     "Saldo"],
                        filas=filas, columnas_monto=(5, 6, 7), subtitulo=texto,
                        totales=["Totales", "", "", "", "", libro.entradas, libro.salidas, libro.saldo_final],
                        resumen=[("Saldo final", libro.saldo_final), ("Saldo inicial", libro.saldo_inicial),
                                 ("Entradas", libro.entradas), ("Salidas", libro.salidas)],
                        nota="Reúne aportaciones, depósitos y retiros, desembolsos y pagos de préstamos, actividades, "
                             "ganancias pagadas y movimientos de caja. Cada operación aparece una sola vez. Las "
                             "ganancias capitalizadas no mueven dinero y no aparecen.")


class ReporteFlujoView(PermisoMixin, TemplateView):
    """13. Flujo de efectivo."""
    permission_required = ("core.ver_reportes", "caja.view_movimientocaja")

    def get(self, request, *args, **kwargs):
        form = FiltroPeriodoForm(request.GET or None)
        form.fields.pop("actividad")
        desde, hasta, texto = _periodo(form)
        flujo = caja_services.flujo_efectivo(desde, hasta)
        filas = [{"url": "", "valores": [f["origen"], f["entradas"], f["salidas"], f["neto"]]} for f in flujo["filas"]]
        final = flujo["saldo_inicial"] + flujo["neto"]
        return _reporte(request, titulo="Flujo de efectivo", nombre="flujo-efectivo", form=form,
                        encabezados=["Origen", "Entradas", "Salidas", "Neto"], filas=filas, columnas_monto=(1, 2, 3),
                        subtitulo=texto, totales=["Totales", flujo["entradas"], flujo["salidas"], flujo["neto"]],
                        resumen=[("Saldo final", final), ("Saldo inicial", flujo["saldo_inicial"]),
                                 ("Entradas", flujo["entradas"]), ("Salidas", flujo["salidas"])],
                        nota="Las transferencias entre cajas y cuentas de CAUNE no cambian el total y no se muestran.")


def resumen_financiero(hasta):
    """Recursos de CAUNE frente a lo que pertenece a los afiliados, a una fecha de corte.

    Cuadre: dinero + cartera = aportaciones + depósitos + utilidades no repartidas + fondos que no son utilidad.
    """
    dinero = caja_services.saldo(hasta=hasta)
    desembolsado = sum((p.monto_aprobado for p in Prestamo.objects.filter(fecha_desembolso__lte=hasta)
                        .exclude(estado=Prestamo.Estado.ANULADO)), CERO)
    capital_cobrado = sum((a.capital for a in AplicacionPago.objects.filter(
        pago__estado=PagoPrestamo.Estado.CONFIRMADO, pago__fecha__lte=hasta)), CERO)
    cartera = desembolsado - capital_cobrado
    saldos = totales_generales(hasta=hasta)
    intereses = pre_services.intereses_cobrados(hasta=hasta) + pre_services.mora_cobrada(hasta=hasta)
    actividades = act_services.resultado_general(hasta=hasta)["neto"]
    otros = caja_services.otros_resultados(hasta=hasta)["neto"]
    no_utilidad = CERO
    for m in MovimientoCaja.objects.confirmados().filter(fecha__lte=hasta, categoria__afecta_utilidades=False):
        no_utilidad += m.monto if m.tipo == MovimientoCaja.Tipo.INGRESO else -m.monto
    entregas = PagoGanancia.objects.confirmados().filter(fecha__lte=hasta)
    pagadas = sum((p.monto for p in entregas if p.forma == PagoGanancia.Forma.PAGO), CERO)
    capitalizadas = sum((p.monto for p in entregas if p.forma == PagoGanancia.Forma.CAPITALIZACION), CERO)
    utilidades = intereses + actividades + otros - pagadas - capitalizadas
    recursos = dinero + cartera
    obligaciones = saldos["aportaciones"] + saldos["depositos"] + utilidades + no_utilidad
    return {"dinero": dinero, "cartera": cartera, "recursos": recursos, "aportaciones": saldos["aportaciones"],
            "depositos": saldos["depositos"], "intereses": intereses, "actividades": actividades, "otros": otros,
            "pagadas": pagadas, "capitalizadas": capitalizadas, "utilidades": utilidades, "no_utilidad": no_utilidad,
            "obligaciones": obligaciones, "diferencia": recursos - obligaciones,
            "por_pagar": dist_services.ganancias_por_pagar()}


class ReporteResumenFinancieroView(PermisoMixin, TemplateView):
    """14. Resumen financiero."""
    permission_required = ("core.ver_reportes", "core.ver_dashboard_financiero")

    def get(self, request, *args, **kwargs):
        form = FiltroPeriodoForm(request.GET or None)
        form.fields.pop("actividad")
        form.fields.pop("desde")
        form.fields["hasta"].label = "Fecha de corte"
        hasta = (form.cleaned_data.get("hasta") if form.is_valid() else None) or timezone.localdate()
        r = resumen_financiero(hasta)

        def fila(*valores):
            return {"url": "", "valores": list(valores)}

        filas = [
            fila("RECURSOS DE CAUNE", ""),
            fila("Dinero en cajas y bancos", r["dinero"]),
            fila("Préstamos por cobrar (capital)", r["cartera"]),
            fila("Total de recursos", r["recursos"]),
            fila("A QUIÉN PERTENECEN", ""),
            fila("Aportaciones de afiliados (incluye ganancias capitalizadas)", r["aportaciones"]),
            fila("Depósitos reembolsables de afiliados", r["depositos"]),
            fila("Utilidades acumuladas no repartidas", r["utilidades"]),
            fila("    Intereses y mora cobrados", r["intereses"]),
            fila("    Resultado de actividades", r["actividades"]),
            fila("    Otros ingresos menos gastos de caja", r["otros"]),
            fila("    Menos ganancias pagadas", -r["pagadas"]),
            fila("    Menos ganancias capitalizadas", -r["capitalizadas"]),
            fila("Fondos de caja que no son utilidad (saldo inicial y similares)", r["no_utilidad"]),
            fila("Total", r["obligaciones"]),
        ]
        if r["por_pagar"]:
            filas.append(fila("Ganancias aprobadas pendientes de entregar (incluidas en utilidades)", r["por_pagar"]))
        cuadra = r["diferencia"] == 0
        return _reporte(request, titulo="Resumen financiero", nombre="resumen-financiero", form=form,
                        encabezados=["Concepto", "Monto"], filas=filas, columnas_monto=(1,),
                        subtitulo=f"Al {hasta:%d/%m/%Y}",
                        totales=["Diferencia (debe ser cero)", r["diferencia"]],
                        resumen=[("Total de recursos", r["recursos"]), ("Utilidades no repartidas", r["utilidades"]),
                                 ("Cuadre", "Cuadra" if cuadra else f"Diferencia L {r['diferencia']:,.2f}")],
                        nota="El cuadre compara el dinero y la cartera con lo que pertenece a los afiliados y a CAUNE. "
                             "Si no es cero, hay operaciones que no se registraron por su módulo.")


# =========================================================================== Fase 4: estados financieros, 15 a 22
from apps.core import parametros  # noqa: E402
from apps.core.exportar import respuesta_xlsx_estados  # noqa: E402

from . import financieros as fin  # noqa: E402
from .forms import (FiltroCajaDiariaForm, FiltroCarteraForm, FiltroCorteForm, FiltroEjercicioForm,  # noqa: E402
                    FiltroResultadosForm)

PERMISO_ESTADOS = ("core.ver_reportes", "core.ver_dashboard_financiero")


def _firmas():
    return {k: parametros.obtener(f"coop.firma_{k}") for k in ("presidente", "tesorero", "revisor")}


def _estados(request, *, titulo, nombre, form, estados, orientacion="portrait"):
    """Renderiza uno o varios estados financieros en pantalla, PDF (con firmas) o Excel (una hoja por estado)."""
    ctx = {"titulo": titulo, "form": form, "estados": estados, "resumen": estados[0].resumen if estados else None,
           "firmas": _firmas(), "orientacion": orientacion}
    formato = request.GET.get("formato")
    if formato == "pdf":
        return respuesta_pdf("reportes/estado_pdf.html", ctx, nombre, request)
    if formato == "xlsx":
        return respuesta_xlsx_estados(estados, nombre)
    return render(request, "reportes/estado.html", ctx)


def _corte(form):
    datos = form.cleaned_data if form.is_valid() else {}
    return datos.get("hasta") or timezone.localdate(), datos.get("comparar")


class ReporteBalanceView(PermisoMixin, TemplateView):
    """15. Balance general (estado de situación financiera)."""
    permission_required = PERMISO_ESTADOS

    def get(self, request, *args, **kwargs):
        form = FiltroCorteForm(request.GET or None)
        hasta, comparar = _corte(form)
        return _estados(request, titulo="Balance general", nombre="balance-general", form=form,
                        estados=[fin.balance_general(hasta, comparar)])


class ReporteEstadoResultadosView(PermisoMixin, TemplateView):
    """16. Estado de resultados."""
    permission_required = PERMISO_ESTADOS

    def get(self, request, *args, **kwargs):
        form = FiltroResultadosForm(request.GET or None)
        desde, hasta = form.periodo()
        comparar = form.is_valid() and form.cleaned_data.get("comparar")
        return _estados(request, titulo="Estado de resultados", nombre="estado-resultados", form=form,
                        estados=[fin.estado_resultados(desde, hasta, comparar)])


class ReportePatrimonioView(PermisoMixin, TemplateView):
    """17. Estado de cambios en el patrimonio."""
    permission_required = PERMISO_ESTADOS

    def get(self, request, *args, **kwargs):
        form = FiltroEjercicioForm(request.GET or None)
        desde, hasta = form.periodo()
        return _estados(request, titulo="Estado de cambios en el patrimonio", nombre="cambios-patrimonio", form=form,
                        estados=[fin.cambios_patrimonio(desde, hasta)], orientacion="landscape")


class ReporteFlujoClasificadoView(PermisoMixin, TemplateView):
    """18. Estado de flujo de efectivo."""
    permission_required = PERMISO_ESTADOS

    def get(self, request, *args, **kwargs):
        form = FiltroEjercicioForm(request.GET or None)
        desde, hasta = form.periodo()
        return _estados(request, titulo="Estado de flujo de efectivo", nombre="estado-flujo-efectivo", form=form,
                        estados=[fin.flujo_clasificado(desde, hasta)])


def _estado_indicadores(hasta):
    datos = fin.indicadores(hasta)
    filas = [fin.Fila("linea", f"{nombre} · {calculo}", [valor], 0) for nombre, calculo, valor, _ in
             (f["valores"] for f in datos["filas"])]
    return fin.Estado(titulo="Indicadores financieros", subtitulo=f"Al {hasta:%d/%m/%Y}", columnas=["Resultado"],
                      filas=filas, firmas=False,
                      nota=f"La utilidad es la del ejercicio {hasta.year} (1 de enero a la fecha de corte).")


class EstadosFinancierosView(PermisoMixin, TemplateView):
    """Estados financieros completos del período: 15 a 19 en un solo documento firmado."""
    permission_required = PERMISO_ESTADOS

    def get(self, request, *args, **kwargs):
        form = FiltroEjercicioForm(request.GET or None)
        desde, hasta = form.periodo()
        estados = [fin.balance_general(hasta), fin.estado_resultados(desde, hasta),
                   fin.cambios_patrimonio(desde, hasta), fin.flujo_clasificado(desde, hasta),
                   _estado_indicadores(hasta)]
        return _estados(request, titulo=f"Estados financieros al {hasta:%d/%m/%Y}", nombre="estados-financieros",
                        form=form, estados=estados)


class ReporteIndicadoresView(PermisoMixin, TemplateView):
    """19. Indicadores financieros."""
    permission_required = PERMISO_ESTADOS

    def get(self, request, *args, **kwargs):
        form = FiltroCorteForm(request.GET or None)
        form.fields.pop("comparar")
        hasta, _ = _corte(form)
        datos = fin.indicadores(hasta)
        s, u = datos["situacion"], datos["utilidad"]
        return _reporte(request, titulo="Indicadores financieros", nombre="indicadores-financieros", form=form,
                        encabezados=["Indicador", "Cálculo", "Resultado", "Qué indica"], filas=datos["filas"],
                        subtitulo=f"Al {hasta:%d/%m/%Y} · utilidad del ejercicio {hasta.year}",
                        resumen=[("Utilidad del ejercicio", u["neto"]), ("Total activo", s["activo"]),
                                 ("Cartera", s["cartera"]), ("Efectivo", s["efectivo"])],
                        nota="La morosidad solo se calcula con fecha de corte de hoy.")


class ReporteCajaCuentasView(PermisoMixin, TemplateView):
    """20. Saldos y movimiento por caja y cuenta bancaria."""
    permission_required = ("core.ver_reportes", "caja.view_movimientocaja")

    def get(self, request, *args, **kwargs):
        form = FiltroEjercicioForm(request.GET or None)
        desde, hasta = form.periodo()
        filas, t = [], {"inicial": CERO, "entradas": CERO, "salidas": CERO, "final": CERO}
        for f in fin.movimiento_por_cuenta(desde, hasta):
            c = f["cuenta"]
            for k in t:
                t[k] += f[k]
            filas.append({"url": reverse("reportes:libro_caja") + f"?cuenta={c.pk}&desde={desde}&hasta={hasta}",
                          "valores": [c.nombre, c.get_tipo_display(),
                                      " ".join(x for x in (c.banco, c.numero_cuenta) if x),
                                      "Activa" if c.activa else "Inactiva", f["inicial"], f["entradas"],
                                      f["salidas"], f["final"]]})
        return _reporte(request, titulo="Saldos por caja y cuenta", nombre="saldos-caja-cuentas", form=form,
                        encabezados=["Caja o cuenta", "Tipo", "Banco y número", "Estado", "Saldo inicial", "Entradas",
                                     "Salidas", "Saldo final"],
                        filas=filas, columnas_monto=(4, 5, 6, 7),
                        subtitulo=f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}",
                        totales=["Totales", "", "", "", t["inicial"], t["entradas"], t["salidas"], t["final"]],
                        resumen=[("Saldo final", t["final"]), ("Saldo inicial", t["inicial"]),
                                 ("Entradas", t["entradas"]), ("Salidas", t["salidas"])],
                        nota="Las entradas y salidas incluyen las transferencias entre cajas y cuentas, que en el total "
                             "se compensan. Cada fila abre el libro de caja de esa cuenta.")


class ReporteCajaDiariaView(PermisoMixin, TemplateView):
    """21. Resumen diario de caja y bancos."""
    permission_required = ("core.ver_reportes", "caja.view_movimientocaja")

    def get(self, request, *args, **kwargs):
        form = FiltroCajaDiariaForm(request.GET or None)
        desde, hasta = form.periodo()
        cuenta = form.cleaned_data.get("cuenta") if form.is_valid() else None
        r = fin.caja_diaria(cuenta, desde, hasta)
        filas = [{"url": "", "valores": [desde, "Saldo inicial", "", None, None, None, r["inicial"]]}]
        for d in r["filas"]:
            filas.append({"url": "", "valores": [d["fecha"], "", d["operaciones"], d["entradas"], d["salidas"],
                                                 d["neto"], d["saldo"]]})
        return _reporte(request, titulo="Resumen diario de caja", nombre="caja-diaria", form=form,
                        encabezados=["Fecha", "Detalle", "Operaciones", "Entradas", "Salidas", "Neto del día",
                                     "Saldo al cierre"],
                        filas=filas, columnas_monto=(3, 4, 5, 6),
                        subtitulo=f"{cuenta.nombre if cuenta else 'Todas las cajas y cuentas'} · "
                                  f"del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}",
                        totales=["Totales", "", sum(d["operaciones"] for d in r["filas"]), r["entradas"], r["salidas"],
                                 r["entradas"] - r["salidas"], r["final"]],
                        resumen=[("Saldo final", r["final"]), ("Saldo inicial", r["inicial"]),
                                 ("Entradas", r["entradas"]), ("Salidas", r["salidas"])],
                        nota="Solo aparecen los días con operaciones. En el consolidado no se cuentan las "
                             "transferencias entre cajas y cuentas de CAUNE. No hay cierre de caja: el saldo de "
                             "cada día se recalcula siempre desde las operaciones confirmadas.")


class ReporteCarteraView(PermisoMixin, TemplateView):
    """22. Antigüedad de la cartera (morosidad)."""
    permission_required = ("core.ver_reportes", "prestamos.view_prestamo")

    def get(self, request, *args, **kwargs):
        form = FiltroCarteraForm(request.GET or None)
        tipo = form.cleaned_data.get("tipo") if form.is_valid() else None
        return _estados(request, titulo="Antigüedad de la cartera", nombre="antiguedad-cartera", form=form,
                        estados=[fin.estado_antiguedad(tipo or None)], orientacion="landscape")
