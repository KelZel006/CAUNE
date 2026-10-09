"""Reportes de la Fase 1. Usan exactamente los mismos servicios y filtros que los módulos operativos."""
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
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
        return super().get_context_data(afiliados=Afiliado.objects.order_by("codigo"), **kwargs)


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
