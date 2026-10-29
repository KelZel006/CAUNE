from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import DetailView, FormView, ListView

from apps.afiliados.views import _agregar_errores
from apps.core.mixins import ListaMixin, PermisoMixin

from . import services
from .forms import ActividadForm, ExclusionForm, MotivoForm, MovimientoActividadForm, SubactividadForm
from .models import Actividad, ExclusionActividad, MovimientoActividad


class ActividadListView(PermisoMixin, ListaMixin, ListView):
    permission_required = "actividades.view_actividad"
    model = Actividad
    template_name = "actividades/lista.html"
    campos_busqueda = ("codigo", "nombre", "descripcion")
    ordenes = {"codigo": "codigo", "nombre": "nombre", "inicio": "fecha_inicio"}
    orden_defecto = "-inicio"

    def get_queryset(self):
        self.queryset = services.anotar_resultados(Actividad.objects.all())
        return super().get_queryset()

    def get_context_data(self, **kwargs):
        return super().get_context_data(general=services.resultado_general(), **kwargs)


class _FormActividadMixin(PermisoMixin):
    form_class = ActividadForm
    template_name = "core/form.html"


class ActividadCreateView(_FormActividadMixin, FormView):
    permission_required = "actividades.add_actividad"

    def get_context_data(self, **kwargs):
        return super().get_context_data(titulo="Nueva actividad económica", cancelar_url="/actividades/", **kwargs)

    def form_valid(self, form):
        try:
            actividad = services.crear_actividad(form.cleaned_data, self.request.user)
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"Actividad {actividad.codigo} creada.")
        return redirect("actividades:detalle", pk=actividad.pk)


class ActividadUpdateView(_FormActividadMixin, FormView):
    permission_required = "actividades.change_actividad"

    def dispatch(self, request, *args, **kwargs):
        self.actividad = get_object_or_404(Actividad, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        a = self.actividad
        return {"nombre": a.nombre, "descripcion": a.descripcion, "fecha_inicio": a.fecha_inicio}

    def get_context_data(self, **kwargs):
        return super().get_context_data(titulo=f"Modificar {self.actividad.codigo}",
                                        cancelar_url=f"/actividades/{self.actividad.pk}/", **kwargs)

    def form_valid(self, form):
        try:
            services.actualizar_actividad(self.actividad, form.cleaned_data, self.request.user)
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, "Actividad actualizada.")
        return redirect("actividades:detalle", pk=self.actividad.pk)


class ActividadDetailView(PermisoMixin, DetailView):
    permission_required = "actividades.view_actividad"
    model = Actividad
    template_name = "actividades/detalle.html"

    def get_context_data(self, **kwargs):
        a = self.object
        return super().get_context_data(
            resultado=services.resultado_actividad(a), por_sub=services.resultados_por_subactividad(a),
            movimientos=a.movimientos.select_related("subactividad", "cuenta_fondo").order_by("-fecha", "-id")[:50],
            exclusiones=a.exclusiones.select_related("afiliado", "registrado_por"), **kwargs)


class _AccionActividadMixin(PermisoMixin):
    def dispatch(self, request, *args, **kwargs):
        self.actividad = get_object_or_404(Actividad, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(actividad=self.actividad, **kwargs)


class SubactividadCreateView(_AccionActividadMixin, FormView):
    permission_required = "actividades.add_subactividad"
    form_class = SubactividadForm
    template_name = "core/form.html"

    def get_context_data(self, **kwargs):
        return super().get_context_data(titulo=f"Nueva subactividad · {self.actividad.nombre}",
                                        cancelar_url=f"/actividades/{self.actividad.pk}/", **kwargs)

    def form_valid(self, form):
        try:
            services.crear_subactividad(self.actividad, form.cleaned_data, self.request.user)
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, "Subactividad creada.")
        return redirect("actividades:detalle", pk=self.actividad.pk)


class MovimientoCreateView(_AccionActividadMixin, FormView):
    permission_required = "actividades.add_movimientoactividad"
    form_class = MovimientoActividadForm
    template_name = "actividades/movimiento_form.html"

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "actividad": self.actividad}

    def get_initial(self):
        return {"tipo": self.request.GET.get("tipo", "INGRESO")}

    def form_valid(self, form):
        d = form.cleaned_data
        try:
            mov, creado = services.registrar_movimiento(
                actividad=self.actividad, subactividad=d["subactividad"], tipo=d["tipo"], fecha=d["fecha"],
                concepto=d["concepto"], monto=d["monto"], metodo_pago=d["metodo_pago"], cuenta_fondo=d["cuenta_fondo"],
                referencia=d["referencia"], observacion=d["observacion"], usuario=self.request.user,
                clave_idempotencia=d["clave_idempotencia"])
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        if creado:
            messages.success(self.request, f"{mov.get_tipo_display()} {mov.numero} registrado.")
        else:
            messages.warning(self.request, f"Este formulario ya se había enviado: {mov.numero} no se registró dos veces.")
        return redirect("actividades:detalle", pk=self.actividad.pk)


class CambiarEstadoView(_AccionActividadMixin, FormView):
    permission_required = "actividades.cambiar_estado_actividad"
    form_class = MotivoForm
    template_name = "actividades/cambiar_estado.html"

    def form_valid(self, form):
        try:
            a = services.cambiar_estado_actividad(self.actividad, self.request.user, form.cleaned_data["motivo"])
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"Actividad {a.get_estado_display().lower()}.")
        return redirect("actividades:detalle", pk=a.pk)


class AnularMovimientoView(PermisoMixin, FormView):
    permission_required = "actividades.anular_movimientoactividad"
    form_class = MotivoForm
    template_name = "actividades/anular.html"

    def dispatch(self, request, *args, **kwargs):
        self.mov = get_object_or_404(MovimientoActividad.objects.select_related("actividad"), pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(m=self.mov, **kwargs)

    def form_valid(self, form):
        try:
            services.anular_movimiento(self.mov, usuario=self.request.user, motivo=form.cleaned_data["motivo"])
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"{self.mov.numero} anulado.")
        return redirect("actividades:detalle", pk=self.mov.actividad_id)


class ExcluirAfiliadoView(_AccionActividadMixin, FormView):
    permission_required = "actividades.gestionar_participacion"
    form_class = ExclusionForm
    template_name = "actividades/participacion.html"

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "actividad": self.actividad}

    def get_context_data(self, **kwargs):
        return super().get_context_data(titulo="Marcar afiliado que no participa", **kwargs)

    def form_valid(self, form):
        try:
            services.excluir_afiliado(self.actividad, form.cleaned_data["afiliado"], usuario=self.request.user,
                                      motivo=form.cleaned_data["motivo"])
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"{form.cleaned_data['afiliado'].codigo} no participará en las ganancias de "
                                       "esta actividad.")
        return redirect("actividades:detalle", pk=self.actividad.pk)


class IncluirAfiliadoView(PermisoMixin, FormView):
    permission_required = "actividades.gestionar_participacion"
    form_class = MotivoForm
    template_name = "actividades/participacion.html"

    def dispatch(self, request, *args, **kwargs):
        self.exclusion = get_object_or_404(ExclusionActividad.objects.select_related("actividad", "afiliado"),
                                           pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(actividad=self.exclusion.actividad, exclusion=self.exclusion,
                                        titulo=f"Volver a incluir a {self.exclusion.afiliado.codigo}", **kwargs)

    def form_valid(self, form):
        try:
            services.incluir_afiliado(self.exclusion, usuario=self.request.user, motivo=form.cleaned_data["motivo"])
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"{self.exclusion.afiliado.codigo} vuelve a participar en las ganancias.")
        return redirect("actividades:detalle", pk=self.exclusion.actividad_id)


class ComprobanteMovimientoView(PermisoMixin, DetailView):
    """Comprobante de ingreso o gasto de una actividad (PDF con original y copia)."""
    permission_required = "actividades.view_movimientoactividad"
    queryset = MovimientoActividad.objects.select_related("actividad", "subactividad", "cuenta_fondo",
                                                          "registrado_por", "anulado_por")

    def get(self, request, *args, **kwargs):
        from apps.core.exportar import respuesta_pdf
        mov = self.get_object()
        return respuesta_pdf("actividades/comprobante_pdf.html", {"m": mov}, f"comprobante-{mov.numero}", request)
