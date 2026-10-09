"""Reportes de la Fase 1. Usan exactamente los mismos servicios y filtros que los módulos operativos."""
from django.core.exceptions import PermissionDenied
from django.db.models import Count, DecimalField, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
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
        return respuesta_pdf("reportes/tabla_pdf.html", ctx, nombre, request)
    if formato == "xlsx":
        def plano(v):
            return v.strftime("%d/%m/%Y") if isinstance(v, _date) else v
        return respuesta_xlsx(titulo, encabezados, [[plano(v) for v in f["valores"]] for f in filas], nombre,
                              columnas_monto=columnas_monto, subtitulo=subtitulo,
                              totales=[plano(v) for v in totales] if totales else None)
    return render(request, "reportes/tabla.html", ctx)


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
        qs = pre_services.anotar_saldos(Prestamo.objects.select_related("afiliado", "prestatario_externo")
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
                p.numero, p.fecha_aprobacion, p.prestatario_nombre, p.get_tipo_prestatario_display(), p.monto_aprobado,
                f"{p.tasa:.2f} %", p.plazo, p.get_metodo_amortizacion_display(), p.intereses_cobrados, saldo,
                p.get_estado_display()]})
        return _reporte(request, titulo="Préstamos otorgados", nombre="prestamos-otorgados", form=form,
                        encabezados=["Préstamo", "Aprobado", "Prestatario", "Tipo", "Monto", "Tasa mensual", "Cuotas",
                                     "Método", "Intereses cobrados", "Saldo capital", "Estado"],
                        filas=filas, columnas_monto=(4, 8, 9),
                        totales=["Totales (sin anulados)", "", "", "", total_monto, "", "", "", "", total_saldo, ""],
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
        filas, t_capital, t_interes = [], CERO, CERO
        for p in qs.order_by("numero"):
            r = pre_services.resumen(p)
            t_capital += r.saldo_capital
            t_interes += r.intereses_pendientes
            prox = r.proxima
            filas.append({"url": reverse("prestamos:detalle", args=[p.pk]), "valores": [
                p.numero, p.prestatario_nombre, p.monto_aprobado, r.saldo_capital, r.intereses_pendientes,
                r.total_pendiente, f"{r.cuotas_pagadas}/{p.plazo}", prox.cuota.fecha_vencimiento if prox else None,
                prox.pendiente if prox else CERO]})
        return _reporte(request, titulo="Saldos pendientes de préstamos", nombre="saldos-prestamos", form=form,
                        encabezados=["Préstamo", "Prestatario", "Monto", "Saldo capital", "Intereses pendientes",
                                     "Total pendiente", "Cuotas pagadas", "Próximo vencimiento", "Próxima cuota"],
                        filas=filas, columnas_monto=(2, 3, 4, 5, 8),
                        totales=["Totales", "", "", t_capital, t_interes, t_capital + t_interes, "", "", ""],
                        resumen=[("Saldo de capital", t_capital), ("Intereses pendientes", t_interes),
                                 ("Préstamos vigentes", len(filas))],
                        nota="Intereses pendientes = intereses del cuadro aprobado aún no cobrados.")


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
        filas, t = [], {"monto": CERO, "capital": CERO, "interes": CERO}
        for pago in qs:
            if pago.estado == PagoPrestamo.Estado.CONFIRMADO:
                t["monto"] += pago.monto
                t["capital"] += pago.capital
                t["interes"] += pago.interes
            filas.append({"url": reverse("prestamos:pago_detalle", args=[pago.pk]), "valores": [
                pago.numero_recibo, pago.fecha, pago.prestamo.numero, pago.prestamo.prestatario_nombre,
                pago.get_tipo_display(), pago.monto, pago.capital, pago.interes, pago.get_estado_display()]})
        return _reporte(request, titulo="Pagos recibidos por préstamo", nombre="pagos-prestamos", form=form,
                        encabezados=["Recibo", "Fecha", "Préstamo", "Prestatario", "Tipo", "Monto", "A capital",
                                     "A intereses", "Estado"],
                        filas=filas, columnas_monto=(5, 6, 7), subtitulo=texto,
                        totales=["Totales confirmados", "", "", "", "", t["monto"], t["capital"], t["interes"], ""],
                        resumen=[("Total cobrado", t["monto"]), ("Capital recuperado", t["capital"]),
                                 ("Intereses cobrados", t["interes"])],
                        nota="El capital recuperado no es ganancia; solo los intereses cobrados son ingreso.")


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
