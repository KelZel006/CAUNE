from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import DetailView, FormView, ListView

from apps.afiliados.views import _agregar_errores
from apps.core import parametros
from apps.core.exportar import respuesta_pdf, respuesta_xlsx
from apps.core.mixins import PermisoMixin

from . import services
from .forms import DistribucionForm, EntregaForm, FiltroGananciasForm, MotivoForm
from .models import Distribucion, PagoGanancia


def _config_vigente():
    return {
        "base": Distribucion.Base(parametros.obtener("distribucion.base_calculo")).label,
        "reserva": parametros.obtener("distribucion.porcentaje_reserva"),
        "inactivos": parametros.obtener("distribucion.incluir_inactivos"),
        "doble_persona": parametros.obtener("distribucion.aprobacion_requiere_otro_usuario"),
    }


class DistribucionListView(PermisoMixin, ListView):
    permission_required = "distribucion.view_distribucion"
    model = Distribucion
    template_name = "distribucion/lista.html"
    paginate_by = 25

    def get(self, request, *args, **kwargs):
        self.filtro = FiltroGananciasForm(request.GET or None)
        datos = self.filtro.cleaned_data if self.filtro.is_valid() else {}
        self.ganancias = services.ganancias_actividades_por_afiliado(
            datos.get("desde"), datos.get("hasta"), incluir_borradores=bool(datos.get("borradores")))
        if request.GET.get("formato") in ("pdf", "xlsx"):
            return self._exportar_ganancias(datos)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(config=_config_vigente(), filtro=self.filtro, ganancias=self.ganancias,
                                       **kwargs)
        for d in ctx["object_list"]:
            d.r = services.resumen(d)
        return ctx

    def _exportar_ganancias(self, datos):
        from apps.reportes.views import _reporte

        g = self.ganancias
        desde, hasta = datos.get("desde"), datos.get("hasta")
        periodo = (f"Del {desde:%d/%m/%Y} " if desde else "Desde siempre ") + (f"al {hasta:%d/%m/%Y}" if hasta
                                                                                else "hasta hoy")
        filas = [{"url": "", "valores": [f["afiliado"].codigo, f["afiliado"].nombre_completo, f["ganancia"],
                                         f["aportaciones"]]} for f in g["filas"]]
        return _reporte(self.request, titulo="Ganancia de actividades y aportaciones por afiliado",
                        nombre="ganancias-actividades-afiliados", form=self.filtro,
                        encabezados=["Código", "Afiliado", "Ganancia de actividades", "Total de aportaciones"],
                        filas=filas, columnas_monto=(2, 3),
                        subtitulo=periodo + (" · incluye distribuciones en borrador" if datos.get("borradores")
                                             else " · distribuciones aprobadas"),
                        totales=["Totales", f"{len(filas)} afiliados", g["ganancia"], g["aportaciones"]],
                        resumen=[("Ganancia de actividades", g["ganancia"]), ("Total de aportaciones",
                                                                              g["aportaciones"])],
                        nota="Ganancia de actividades: lo que le tocó a cada afiliado de los fondos de actividades "
                             "económicas en las distribuciones cuyo período termina en el rango. No incluye la "
                             "utilidad general (intereses). Ordenado de mayor a menor ganancia.")


class DistribucionCreateView(PermisoMixin, FormView):
    permission_required = "distribucion.add_distribucion"
    form_class = DistribucionForm
    template_name = "distribucion/form.html"

    def get_context_data(self, **kwargs):
        return super().get_context_data(config=_config_vigente(), **kwargs)

    def form_valid(self, form):
        d = form.cleaned_data
        try:
            dist = services.crear_distribucion(desde=d["fecha_inicio"], hasta=d["fecha_fin"],
                                               observaciones=d["observaciones"], usuario=self.request.user)
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"Distribución {dist.codigo} calculada. Revísela antes de aprobarla.")
        return redirect("distribucion:detalle", pk=dist.pk)


class DistribucionDetailView(PermisoMixin, DetailView):
    permission_required = "distribucion.view_distribucion"
    model = Distribucion
    template_name = "distribucion/detalle.html"

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        r = services.resumen(self.object)
        formato = request.GET.get("formato")
        if formato in ("pdf", "xlsx"):
            return exportar(request, self.object, r, formato)
        return self.render_to_response(self.get_context_data(r=r, pagos=self.object.pagos.select_related(
            "afiliado", "cuenta_fondo").order_by("-fecha", "-id")))


def exportar(request, dist, r, formato):
    """Reporte 10: ganancias por afiliado de una distribución."""
    nombres_fondos = [f.nombre for f in r["fondos"]]
    titulo = f"Ganancias por afiliado · {dist.codigo}"
    subtitulo = (f"Período del {dist.fecha_inicio:%d/%m/%Y} al {dist.fecha_fin:%d/%m/%Y} · "
                 f"{dist.get_base_calculo_display()} · {dist.get_estado_display()}")
    encabezados = ["Código", "Afiliado", "Base", "% general", *nombres_fondos, "Total", "Entrega"]
    filas = []
    for x in r["filas"]:
        entrega = (f"{x['pago'].get_forma_display()} {x['pago'].numero}" if x["pago"] else
                   ("Pendiente" if x["total"] > 0 else "—"))
        filas.append([x["afiliado"].codigo, x["afiliado"].nombre_completo, x["base"],
                      f"{x['porcentaje']:.4f} %" if x["porcentaje"] is not None else "—",
                      *[v if v is not None else "" for v in x["por_fondo"]], x["total"], entrega])
    n = len(nombres_fondos)
    totales = ["Totales", "", "", "", *[f.a_distribuir if f.participantes else 0 for f in r["fondos"]], r["total"], ""]
    columnas = (2, *range(4, 5 + n))
    if formato == "xlsx":
        return respuesta_xlsx(titulo, encabezados, filas, f"ganancias-{dist.codigo}", columnas_monto=columnas,
                              subtitulo=subtitulo, totales=totales)
    ctx = dict(titulo=titulo, subtitulo=subtitulo, encabezados=encabezados,
               filas=[{"valores": f, "url": ""} for f in filas], columnas_monto=columnas, totales=totales,
               resumen=[("Resultado del período", r["resultado"]), ("Reserva", r["reserva"]),
                        ("Repartido", r["total"])],
               nota="Cada fondo se reparte en proporción a la base (saldo de aportaciones). Los afiliados marcados "
                    "como no participantes de una actividad no reciben parte de ese fondo.")
    return respuesta_pdf("reportes/tabla_pdf.html", ctx, f"ganancias-{dist.codigo}", request)


class _AccionMixin(PermisoMixin):
    def dispatch(self, request, *args, **kwargs):
        self.dist = get_object_or_404(Distribucion, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(dist=self.dist, **kwargs)


class RecalcularView(_AccionMixin, View):
    permission_required = "distribucion.add_distribucion"

    def post(self, request, *args, **kwargs):
        try:
            services.recalcular(self.dist, usuario=request.user)
            messages.success(request, f"{self.dist.codigo} recalculada con los datos actuales.")
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        return redirect("distribucion:detalle", pk=self.dist.pk)


class AprobarView(_AccionMixin, View):
    permission_required = "distribucion.aprobar_distribucion"

    def post(self, request, *args, **kwargs):
        try:
            services.aprobar(self.dist, usuario=request.user)
            messages.success(request, f"{self.dist.codigo} aprobada. Ya puede pagar o capitalizar las ganancias.")
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        return redirect("distribucion:detalle", pk=self.dist.pk)


class AnularView(_AccionMixin, FormView):
    permission_required = "distribucion.anular_distribucion"
    form_class = MotivoForm
    template_name = "distribucion/anular.html"

    def form_valid(self, form):
        try:
            services.anular(self.dist, usuario=self.request.user, motivo=form.cleaned_data["motivo"])
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"{self.dist.codigo} anulada.")
        return redirect("distribucion:detalle", pk=self.dist.pk)


class EntregarView(_AccionMixin, FormView):
    permission_required = "distribucion.aplicar_distribucion"
    form_class = EntregaForm
    template_name = "distribucion/entregar.html"

    def pendientes(self):
        if not hasattr(self, "_pendientes"):
            r = services.resumen(self.dist)
            self._pendientes = [x for x in r["filas"] if x["pago"] is None and x["total"] > 0]
        return self._pendientes

    def get(self, request, *args, **kwargs):
        if self.dist.estado != Distribucion.Estado.APROBADA:
            messages.error(request, "Solo se pagan o capitalizan ganancias de una distribución aprobada.")
            return redirect("distribucion:detalle", pk=self.dist.pk)
        return super().get(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "pendientes": self.pendientes()}

    def get_context_data(self, **kwargs):
        return super().get_context_data(pendientes=self.pendientes(), **kwargs)

    def form_valid(self, form):
        d = form.cleaned_data
        try:
            pagos = services.registrar_pagos(
                self.dist, afiliados=list(d["afiliados"].order_by("codigo")), forma=d["forma"], fecha=d["fecha"],
                cuenta_fondo=d["cuenta_fondo"], metodo_pago=d["metodo_pago"], referencia=d["referencia"],
                usuario=self.request.user)
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        total = sum(p.monto for p in pagos)
        messages.success(self.request, f"{len(pagos)} entrega{'s' if len(pagos) != 1 else ''} registrada"
                                       f"{'s' if len(pagos) != 1 else ''} por L {total:,.2f}.")
        return redirect("distribucion:detalle", pk=self.dist.pk)


class AnularPagoView(PermisoMixin, FormView):
    permission_required = "distribucion.anular_pagoganancia"
    form_class = MotivoForm
    template_name = "distribucion/anular_pago.html"

    def dispatch(self, request, *args, **kwargs):
        self.pago = get_object_or_404(PagoGanancia.objects.select_related("distribucion", "afiliado"), pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(pago=self.pago, **kwargs)

    def form_valid(self, form):
        try:
            services.anular_pago(self.pago, usuario=self.request.user, motivo=form.cleaned_data["motivo"])
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"{self.pago.numero} anulado.")
        return redirect("distribucion:detalle", pk=self.pago.distribucion_id)


class ComprobantePagoView(PermisoMixin, DetailView):
    """Comprobante de pago o capitalización de ganancias de un afiliado (PDF con original y copia)."""
    permission_required = "distribucion.view_distribucion"
    queryset = PagoGanancia.objects.select_related("distribucion", "afiliado", "cuenta_fondo", "movimiento_afiliado",
                                                   "registrado_por", "anulado_por")

    def get(self, request, *args, **kwargs):
        pago = self.get_object()
        return respuesta_pdf("distribucion/comprobante_pdf.html", {"p": pago}, f"comprobante-{pago.numero}", request)
