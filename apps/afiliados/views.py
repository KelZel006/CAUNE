from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import DetailView, FormView, ListView

from apps.aportaciones import services as mov_services
from apps.core.dinero import formato_lempiras
from apps.core.exportar import respuesta_pdf, respuesta_xlsx
from apps.core.mixins import ListaMixin, PermisoMixin

from . import services
from .forms import AfiliadoForm, CambioEstadoForm, FiltroAfiliadosForm, RangoFechasForm
from .models import Afiliado


def _agregar_errores(form, error):
    """Traslada un ValidationError del servicio al formulario (por campo cuando existe)."""
    if hasattr(error, "error_dict"):
        for campo, errores in error.error_dict.items():
            form.add_error(campo if campo in form.fields else None, errores)
    else:
        form.add_error(None, error)


class AfiliadoListView(PermisoMixin, ListaMixin, ListView):
    permission_required = "afiliados.view_afiliado"
    model = Afiliado
    template_name = "afiliados/lista.html"
    campos_busqueda = ("codigo", "nombres", "apellidos", "identidad", "telefono")
    ordenes = {"codigo": "codigo", "nombre": "apellidos", "ingreso": "fecha_ingreso", "estado": "estado",
               "aportaciones": "saldo_aportaciones", "depositos": "saldo_depositos"}
    orden_defecto = "codigo"
    filtro_form_class = FiltroAfiliadosForm

    def get_queryset(self):
        self.ver_saldos = self.request.user.has_perm("afiliados.ver_estado_cuenta")
        qs = Afiliado.objects.all()
        if self.ver_saldos:
            qs = mov_services.anotar_saldos(qs)
        self.queryset = qs
        return super().get_queryset()

    def filtrar(self, qs, datos):
        if datos.get("estado"):
            qs = qs.filter(estado=datos["estado"])
        if datos.get("ingreso_desde"):
            qs = qs.filter(fecha_ingreso__gte=datos["ingreso_desde"])
        if datos.get("ingreso_hasta"):
            qs = qs.filter(fecha_ingreso__lte=datos["ingreso_hasta"])
        return qs

    def get_context_data(self, **kwargs):
        return super().get_context_data(ver_saldos=self.ver_saldos, **kwargs)


class AfiliadoCreateView(PermisoMixin, FormView):
    permission_required = "afiliados.add_afiliado"
    form_class = AfiliadoForm
    template_name = "afiliados/form.html"

    def get_initial(self):
        return {"fecha_ingreso": timezone.localdate()}

    def form_valid(self, form):
        try:
            afiliado = services.crear_afiliado(form.cleaned_data, self.request.user)
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"Afiliado {afiliado.codigo} registrado.")
        return redirect("afiliados:detalle", pk=afiliado.pk)


class AfiliadoUpdateView(PermisoMixin, FormView):
    permission_required = "afiliados.change_afiliado"
    form_class = AfiliadoForm
    template_name = "afiliados/form.html"

    def dispatch(self, request, *args, **kwargs):
        self.afiliado = get_object_or_404(Afiliado, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "instance": self.afiliado}

    def get_context_data(self, **kwargs):
        return super().get_context_data(afiliado=self.afiliado, **kwargs)

    def form_valid(self, form):
        try:
            services.actualizar_afiliado(self.afiliado, form.cleaned_data, self.request.user)
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, "Datos del afiliado actualizados.")
        return redirect("afiliados:detalle", pk=self.afiliado.pk)


class AfiliadoDetailView(PermisoMixin, DetailView):
    permission_required = "afiliados.view_afiliado"
    model = Afiliado
    template_name = "afiliados/detalle.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        usuario = self.request.user
        if usuario.has_perm("afiliados.ver_estado_cuenta"):
            ctx["saldos"] = mov_services.saldos_afiliado(self.object)
        if usuario.has_perm("aportaciones.view_movimientoafiliado"):
            ctx["movimientos"] = self.object.movimientos.select_related("tipo", "cuenta_fondo").order_by(
                "-fecha", "-id")[:15]
        ctx["cambios_estado"] = self.object.cambios_estado.select_related("registrado_por")
        if usuario.has_perm("prestamos.view_prestamo"):
            from apps.prestamos.services import anotar_saldos
            ctx["prestamos"] = anotar_saldos(self.object.prestamos.order_by("-fecha_aprobacion"))
            ctx["respaldados"] = (self.object.prestamos_respaldados.exclude(estado="ANULADO")
                                  .select_related("prestatario_externo").order_by("-fecha_aprobacion"))
        if usuario.has_perm("distribucion.view_distribucion"):
            from apps.distribucion.services import ganancias_afiliado
            ctx["ganancias"] = ganancias_afiliado(self.object)
        return ctx


class CambiarEstadoView(PermisoMixin, FormView):
    permission_required = "afiliados.cambiar_estado_afiliado"
    form_class = CambioEstadoForm
    template_name = "afiliados/cambiar_estado.html"

    def dispatch(self, request, *args, **kwargs):
        self.afiliado = get_object_or_404(Afiliado, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        nuevo = Afiliado.Estado.INACTIVO if self.afiliado.activo else Afiliado.Estado.ACTIVO
        return super().get_context_data(afiliado=self.afiliado, estado_nuevo=nuevo,
                                        estado_nuevo_label=Afiliado.Estado(nuevo).label, **kwargs)

    def form_valid(self, form):
        nuevo = Afiliado.Estado.INACTIVO if self.afiliado.activo else Afiliado.Estado.ACTIVO
        try:
            services.cambiar_estado(self.afiliado, estado_nuevo=nuevo, usuario=self.request.user, **form.cleaned_data)
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"Afiliado {Afiliado.Estado(nuevo).label.lower()}.")
        return redirect("afiliados:detalle", pk=self.afiliado.pk)


def complementos_estado_cuenta(afiliado, desde, hasta, usuario):
    """Préstamos y ganancias del afiliado en el período, según lo que el usuario puede consultar."""
    datos = {}
    if usuario.has_perm("prestamos.view_prestamo"):
        from apps.prestamos.services import prestamos_de_afiliado
        datos["prestamos_ec"] = prestamos_de_afiliado(afiliado, desde, hasta)
    if usuario.has_perm("distribucion.view_distribucion"):
        from apps.distribucion.services import ganancias_afiliado
        datos["ganancias_ec"] = [g for g in ganancias_afiliado(afiliado) if g["distribucion"].fecha_fin <= hasta
                                 and (desde is None or g["distribucion"].fecha_fin >= desde)]
    return datos


class EstadoCuentaView(PermisoMixin, DetailView):
    permission_required = "afiliados.ver_estado_cuenta"
    model = Afiliado
    template_name = "afiliados/estado_cuenta.html"

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.form = RangoFechasForm(request.GET or None)
        desde = hasta = None
        if self.form.is_valid():
            desde, hasta = self.form.cleaned_data.get("desde"), self.form.cleaned_data.get("hasta")
        self.estado = mov_services.estado_cuenta(self.object, desde, hasta)
        self.complementos = complementos_estado_cuenta(self.object, self.estado.desde, self.estado.hasta, request.user)
        formato = request.GET.get("formato")
        if formato == "pdf":
            return respuesta_pdf("afiliados/estado_cuenta_pdf.html", {"ec": self.estado, **self.complementos},
                                 f"estado-cuenta-{self.object.codigo}", request)
        if formato == "xlsx":
            return self._xlsx()
        return self.render_to_response(self.get_context_data(object=self.object))

    def get_context_data(self, **kwargs):
        return super().get_context_data(ec=self.estado, form=self.form, **self.complementos, **kwargs)

    def _xlsx(self):
        ec = self.estado
        filas = [["", "Saldo inicial", "", "", "", "", ec.saldo_inicial["aportaciones"], ec.saldo_inicial["depositos"],
                  ec.saldo_inicial["total"]]]
        for l in ec.lineas:
            m = l["movimiento"]
            filas.append([m.fecha.strftime("%d/%m/%Y"), m.numero_operacion, m.tipo.nombre, m.get_metodo_pago_display(),
                          l["entrada"], l["salida"], l["saldo_aportaciones"], l["saldo_depositos"], l["saldo_total"]])
        periodo = (f"Del {ec.desde:%d/%m/%Y} al {ec.hasta:%d/%m/%Y}" if ec.desde else f"Hasta el {ec.hasta:%d/%m/%Y}")
        return respuesta_xlsx(
            f"Estado de cuenta {ec.afiliado.codigo}",
            ["Fecha", "Operación", "Tipo", "Método", "Entrada", "Salida", "Saldo aportaciones", "Saldo depósitos",
             "Saldo total"],
            filas, f"estado-cuenta-{ec.afiliado.codigo}", columnas_monto=(4, 5, 6, 7, 8),
            subtitulo=f"{ec.afiliado.nombre_completo} · {periodo} · Saldo final {formato_lempiras(ec.saldo_final['total'])}",
        )
