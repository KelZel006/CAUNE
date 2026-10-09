from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

from apps.afiliados.views import _agregar_errores
from apps.core import auditoria
from apps.core.exportar import respuesta_pdf
from apps.core.mixins import ListaMixin, PermisoMixin
from apps.core.views import FormularioGenericoMixin

from . import services
from .forms import AnulacionForm, FiltroMovimientosForm, MovimientoForm, TipoMovimientoForm, aplicar_filtro_movimientos
from .models import MovimientoAfiliado, TipoMovimiento


class MovimientoListView(PermisoMixin, ListaMixin, ListView):
    permission_required = "aportaciones.view_movimientoafiliado"
    model = MovimientoAfiliado
    template_name = "aportaciones/lista.html"
    campos_busqueda = ("numero_operacion", "afiliado__codigo", "afiliado__nombres", "afiliado__apellidos", "referencia")
    ordenes = {"numero": "numero_operacion", "fecha": "fecha", "afiliado": "afiliado__codigo", "tipo": "tipo__nombre",
               "monto": "monto"}
    orden_defecto = "-fecha"
    filtro_form_class = FiltroMovimientosForm

    def get_queryset(self):
        self.queryset = MovimientoAfiliado.objects.select_related("afiliado", "tipo", "cuenta_fondo")
        return super().get_queryset()

    def filtrar(self, qs, datos):
        return aplicar_filtro_movimientos(qs, datos)


class MovimientoCreateView(PermisoMixin, FormView):
    permission_required = "aportaciones.add_movimientoafiliado"
    form_class = MovimientoForm
    template_name = "aportaciones/form.html"

    def get_initial(self):
        inicial = super().get_initial()
        if self.request.GET.get("afiliado", "").isdigit():
            inicial["afiliado"] = int(self.request.GET["afiliado"])
        return inicial

    def form_valid(self, form):
        datos = form.cleaned_data
        try:
            movimiento, creado = services.registrar_movimiento(
                afiliado=datos["afiliado"], tipo=datos["tipo"], fecha=datos["fecha"], monto=datos["monto"],
                metodo_pago=datos["metodo_pago"], cuenta_fondo=datos["cuenta_fondo"], referencia=datos["referencia"],
                observacion=datos["observacion"], usuario=self.request.user,
                clave_idempotencia=datos["clave_idempotencia"],
            )
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        if creado:
            messages.success(self.request, f"Operación {movimiento.numero_operacion} registrada.")
        else:
            messages.warning(self.request, f"Este formulario ya se había enviado: la operación "
                                           f"{movimiento.numero_operacion} no se registró dos veces.")
        return redirect("aportaciones:detalle", pk=movimiento.pk)


class MovimientoDetailView(PermisoMixin, DetailView):
    permission_required = "aportaciones.view_movimientoafiliado"
    template_name = "aportaciones/detalle.html"
    queryset = MovimientoAfiliado.objects.select_related("afiliado", "tipo", "cuenta_fondo", "registrado_por",
                                                         "anulado_por")


class ReciboView(MovimientoDetailView):
    template_name = "aportaciones/recibo.html"

    def get(self, request, *args, **kwargs):
        if request.GET.get("formato") == "pdf":
            self.object = self.get_object()
            return respuesta_pdf("aportaciones/recibo_pdf.html", {"m": self.object},
                                 f"recibo-{self.object.numero_operacion}", request)
        return super().get(request, *args, **kwargs)


class AnularMovimientoView(PermisoMixin, FormView):
    permission_required = "aportaciones.anular_movimientoafiliado"
    form_class = AnulacionForm
    template_name = "aportaciones/anular.html"

    def dispatch(self, request, *args, **kwargs):
        self.movimiento = get_object_or_404(MovimientoAfiliado.objects.select_related("afiliado", "tipo"), pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(m=self.movimiento, **kwargs)

    def form_valid(self, form):
        try:
            services.anular_movimiento(self.movimiento, motivo=form.cleaned_data["motivo"], usuario=self.request.user)
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"Operación {self.movimiento.numero_operacion} anulada.")
        return redirect("aportaciones:detalle", pk=self.movimiento.pk)


# --------------------------------------------------------------------------- tipos de movimiento

class TipoListView(PermisoMixin, ListView):
    permission_required = "aportaciones.view_tipomovimiento"
    model = TipoMovimiento
    template_name = "aportaciones/tipos.html"


class TipoGuardarMixin:
    @transaction.atomic
    def form_valid(self, form):
        antes = auditoria.instantanea(TipoMovimiento.objects.get(pk=form.instance.pk)) if form.instance.pk else None
        respuesta = super().form_valid(form)
        despues = auditoria.instantanea(self.object)
        if antes is None:
            auditoria.registrar(auditoria.Accion.CREAR, objeto=self.object, despues=despues)
        else:
            a, d = auditoria.diferencias(antes, despues)
            if d:
                auditoria.registrar(auditoria.Accion.CONFIGURAR, objeto=self.object, antes=a, despues=d)
        messages.success(self.request, "Tipo de movimiento guardado.")
        return respuesta


class TipoCreateView(PermisoMixin, FormularioGenericoMixin, TipoGuardarMixin, CreateView):
    permission_required = "aportaciones.add_tipomovimiento"
    form_class = TipoMovimientoForm
    titulo = "Nuevo tipo de movimiento"
    cancelar_url = reverse_lazy("aportaciones:tipos")
    success_url = reverse_lazy("aportaciones:tipos")


class TipoUpdateView(PermisoMixin, FormularioGenericoMixin, TipoGuardarMixin, UpdateView):
    permission_required = "aportaciones.change_tipomovimiento"
    model = TipoMovimiento
    form_class = TipoMovimientoForm
    titulo = "Modificar tipo de movimiento"
    cancelar_url = reverse_lazy("aportaciones:tipos")
    success_url = reverse_lazy("aportaciones:tipos")
