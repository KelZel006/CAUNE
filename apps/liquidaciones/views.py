from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import DetailView, FormView, ListView

from apps.afiliados.models import Afiliado
from apps.afiliados.views import _agregar_errores
from apps.core.exportar import respuesta_pdf
from apps.core.mixins import PermisoMixin

from . import services
from .forms import EjecutarForm, LiquidacionForm, MotivoForm
from .models import Liquidacion


class LiquidacionListView(PermisoMixin, ListView):
    permission_required = "liquidaciones.view_liquidacion"
    template_name = "liquidaciones/lista.html"
    paginate_by = 25
    queryset = Liquidacion.objects.select_related("afiliado", "calculado_por", "ejecutado_por")


class LiquidacionCreateView(PermisoMixin, FormView):
    """Calcula la liquidación del afiliado: muestra el cálculo y, al confirmar, la guarda por aprobar."""
    permission_required = "liquidaciones.add_liquidacion"
    form_class = LiquidacionForm
    template_name = "liquidaciones/form.html"

    def dispatch(self, request, *args, **kwargs):
        self.afiliado = get_object_or_404(Afiliado, pk=kwargs["pk"])
        pendiente = self.afiliado.liquidaciones.filter(estado=Liquidacion.Estado.CALCULADA).first()
        if pendiente is not None:
            messages.info(request, f"{self.afiliado.codigo} ya tiene la liquidación {pendiente.numero} por aprobar.")
            return redirect("liquidaciones:detalle", pk=pendiente.pk)
        self.calculo = services.calcular(self.afiliado)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "hay_avalados": bool(self.calculo["avalados"])}

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(afiliado=self.afiliado, c=self.calculo, **kwargs)
        if self.calculo["avalados"]:
            ctx["c_descontando"] = services.calcular(self.afiliado, descontar_avalados=True)
        return ctx

    def form_valid(self, form):
        try:
            liq = services.crear(self.afiliado, motivo=form.cleaned_data["motivo"], usuario=self.request.user,
                                 descontar_avalados=form.cleaned_data.get("descontar_avalados", False))
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"Liquidación {liq.numero} calculada. Debe aprobarla otra persona.")
        return redirect("liquidaciones:detalle", pk=liq.pk)


class LiquidacionDetailView(PermisoMixin, DetailView):
    permission_required = "liquidaciones.view_liquidacion"
    template_name = "liquidaciones/detalle.html"
    queryset = Liquidacion.objects.select_related("afiliado", "calculado_por", "ejecutado_por", "anulado_por",
                                                  "cuenta_fondo")

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if request.GET.get("formato") == "pdf":
            return respuesta_pdf("liquidaciones/comprobante_pdf.html", self.get_context_data(object=self.object),
                                 f"liquidacion-{self.object.numero}", request)
        return self.render_to_response(self.get_context_data(object=self.object))

    def get_context_data(self, **kwargs):
        liq = self.object
        ctx = super().get_context_data(l=liq, **kwargs)
        if liq.estado == Liquidacion.Estado.CALCULADA:
            c = services.calcular(liq.afiliado, liq.descontar_avalados)
            ctx["bloqueos"], ctx["avisos"], ctx["hay_avalados"] = c["bloqueos"], c["avisos"], bool(c["avalados"])
        ctx["movimientos"] = liq.movimientos.select_related("tipo").order_by("id")
        ctx["pagos_prestamo"] = liq.pagos_prestamo.select_related("prestamo").order_by("id")
        ctx["pagos_ganancia"] = liq.pagos_ganancia.select_related("distribucion").order_by("id")
        return ctx


class _AccionMixin(PermisoMixin):
    def dispatch(self, request, *args, **kwargs):
        self.liq = get_object_or_404(Liquidacion.objects.select_related("afiliado"), pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(l=self.liq, **kwargs)


class RecalcularView(_AccionMixin, View):
    permission_required = "liquidaciones.add_liquidacion"

    def post(self, request, *args, **kwargs):
        descontar = request.POST.get("descontar_avalados")
        try:
            services.recalcular(self.liq, usuario=request.user,
                                descontar_avalados=None if descontar is None else descontar == "1")
            messages.success(request, "Liquidación recalculada con los saldos de hoy.")
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        return redirect("liquidaciones:detalle", pk=self.liq.pk)


class EjecutarView(_AccionMixin, FormView):
    permission_required = "liquidaciones.ejecutar_liquidacion"
    form_class = EjecutarForm
    template_name = "liquidaciones/ejecutar.html"

    def form_valid(self, form):
        d = form.cleaned_data
        try:
            services.ejecutar(self.liq, usuario=self.request.user, cuenta_fondo=d["cuenta_fondo"],
                              metodo_pago=d["metodo_pago"], referencia=d["referencia"])
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"Liquidación {self.liq.numero} ejecutada: {self.liq.afiliado.codigo} quedó "
                                       "dado de baja.")
        return redirect("liquidaciones:detalle", pk=self.liq.pk)


class AnularView(_AccionMixin, FormView):
    permission_required = "liquidaciones.anular_liquidacion"
    form_class = MotivoForm
    template_name = "liquidaciones/anular.html"

    def form_valid(self, form):
        try:
            services.anular(self.liq, usuario=self.request.user, motivo=form.cleaned_data["motivo"])
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"Liquidación {self.liq.numero} anulada.")
        return redirect("liquidaciones:detalle", pk=self.liq.pk)
