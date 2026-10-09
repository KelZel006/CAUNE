from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import DetailView, FormView, ListView

from apps.afiliados.views import _agregar_errores
from apps.core.exportar import respuesta_pdf, respuesta_xlsx
from apps.core.mixins import ListaMixin, PermisoMixin

from . import services
from .forms import DesembolsoForm, FiltroPrestamosForm, MotivoForm, PagoForm, PrestamoForm
from .models import PagoPrestamo, Prestamo


def aplicar_filtro_prestamos(qs, datos):
    if datos.get("estado"):
        qs = qs.filter(estado=datos["estado"])
    if datos.get("tipo"):
        qs = qs.filter(tipo_prestatario=datos["tipo"])
    if datos.get("desde"):
        qs = qs.filter(fecha_aprobacion__gte=datos["desde"])
    if datos.get("hasta"):
        qs = qs.filter(fecha_aprobacion__lte=datos["hasta"])
    return qs


class PrestamoListView(PermisoMixin, ListaMixin, ListView):
    permission_required = "prestamos.view_prestamo"
    model = Prestamo
    template_name = "prestamos/lista.html"
    campos_busqueda = ("numero", "afiliado__codigo", "afiliado__nombres", "afiliado__apellidos",
                       "prestatario_externo__nombre_completo", "prestatario_externo__identidad")
    ordenes = {"numero": "numero", "fecha": "fecha_aprobacion", "monto": "monto_aprobado", "estado": "estado"}
    orden_defecto = "-fecha"
    filtro_form_class = FiltroPrestamosForm

    def get_queryset(self):
        self.queryset = services.anotar_saldos(Prestamo.objects.select_related("afiliado", "prestatario_externo"))
        return super().get_queryset()

    def filtrar(self, qs, datos):
        return aplicar_filtro_prestamos(qs, datos)


class PrestamoCreateView(PermisoMixin, FormView):
    permission_required = "prestamos.add_prestamo"
    form_class = PrestamoForm
    template_name = "prestamos/form.html"

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "metodos": services.metodos_permitidos()}

    def get_initial(self):
        inicial = super().get_initial()
        if self.request.GET.get("afiliado", "").isdigit():
            inicial["afiliado"] = int(self.request.GET["afiliado"])
        return inicial

    def get_context_data(self, **kwargs):
        return super().get_context_data(tasa_interna=services.tasa_configurada(Prestamo.Tipo.INTERNO),
                                        tasa_externa=services.tasa_configurada(Prestamo.Tipo.EXTERNO), **kwargs)

    def form_valid(self, form):
        d = form.cleaned_data
        if self.request.POST.get("accion") == "simular":
            tasa = d["tasa"] if d["tasa"] is not None else services.tasa_configurada(d["tipo_prestatario"])
            try:
                filas, totales = services.simular(d["monto_aprobado"], tasa, d["plazo"], d["metodo_amortizacion"],
                                                  d["fecha_primer_vencimiento"])
            except ValueError as error:
                form.add_error(None, str(error))
                return self.form_invalid(form)
            return self.render_to_response(self.get_context_data(form=form, simulacion=filas, totales=totales,
                                                                 tasa_simulada=tasa))
        try:
            prestamo = services.aprobar_prestamo(
                usuario=self.request.user, tipo_prestatario=d["tipo_prestatario"], afiliado=d["afiliado"],
                externo={"nombre_completo": d["externo_nombre"], "identidad": d["externo_identidad"],
                         "telefono": d["externo_telefono"], "direccion": d["externo_direccion"]},
                monto_solicitado=d["monto_solicitado"], monto_aprobado=d["monto_aprobado"], plazo=d["plazo"],
                metodo_amortizacion=d["metodo_amortizacion"], tasa=d["tasa"], motivo_excepcion=d["motivo_excepcion"],
                fecha_aprobacion=d["fecha_aprobacion"], fecha_primer_vencimiento=d["fecha_primer_vencimiento"],
                observaciones=d["observaciones"],
            )
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"Préstamo {prestamo.numero} aprobado con su cuadro de amortización. "
                                       "Registre el desembolso cuando se entregue el dinero.")
        return redirect("prestamos:detalle", pk=prestamo.pk)


class PrestamoDetailView(PermisoMixin, DetailView):
    permission_required = "prestamos.view_prestamo"
    template_name = "prestamos/detalle.html"
    queryset = Prestamo.objects.select_related("afiliado", "prestatario_externo", "registrado_por",
                                               "excepcion_autorizada_por", "cuenta_desembolso")

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.resumen = services.resumen(self.object)
        formato = request.GET.get("formato")
        if formato == "pdf":
            return respuesta_pdf("prestamos/cuadro_pdf.html", {"p": self.object, "r": self.resumen},
                                 f"cuadro-{self.object.numero}", request)
        if formato == "xlsx":
            filas = [[c.cuota.numero, c.cuota.fecha_vencimiento.strftime("%d/%m/%Y"), c.cuota.saldo_inicial,
                      c.cuota.capital, c.cuota.interes, c.cuota.cuota, c.cuota.saldo_final, c.capital_pagado,
                      c.interes_pagado, c.pendiente, c.estado.title()] for c in self.resumen.cuotas]
            p = self.object
            return respuesta_xlsx(
                f"Cuadro {p.numero}",
                ["N.º", "Vencimiento", "Saldo inicial", "Capital", "Interés", "Cuota", "Saldo final",
                 "Capital pagado", "Interés pagado", "Pendiente", "Estado"],
                filas, f"cuadro-{p.numero}", columnas_monto=(2, 3, 4, 5, 6, 7, 8, 9),
                subtitulo=f"{p.prestatario_nombre} · L {p.monto_aprobado:,.2f} al {p.tasa:g} % mensual · "
                          f"{p.plazo} cuotas · {p.get_metodo_amortizacion_display()}")
        return self.render_to_response(self.get_context_data(object=self.object))

    def get_context_data(self, **kwargs):
        return super().get_context_data(r=self.resumen, pagos=self.object.pagos.select_related("registrado_por"),
                                        **kwargs)


class _AccionPrestamoMixin(PermisoMixin):
    def dispatch(self, request, *args, **kwargs):
        self.prestamo = get_object_or_404(Prestamo.objects.select_related("afiliado", "prestatario_externo"),
                                          pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(p=self.prestamo, **kwargs)


class DesembolsoView(_AccionPrestamoMixin, FormView):
    permission_required = "prestamos.desembolsar_prestamo"
    form_class = DesembolsoForm
    template_name = "prestamos/desembolso.html"

    def form_valid(self, form):
        try:
            services.desembolsar(self.prestamo, usuario=self.request.user, **form.cleaned_data)
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"Desembolso de {self.prestamo.numero} registrado. El préstamo está vigente.")
        return redirect("prestamos:detalle", pk=self.prestamo.pk)


class AnularPrestamoView(_AccionPrestamoMixin, FormView):
    permission_required = "prestamos.anular_prestamo"
    form_class = MotivoForm
    template_name = "prestamos/anular.html"

    def form_valid(self, form):
        try:
            services.anular_prestamo(self.prestamo, usuario=self.request.user, motivo=form.cleaned_data["motivo"])
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"Préstamo {self.prestamo.numero} anulado.")
        return redirect("prestamos:detalle", pk=self.prestamo.pk)


class PagoCreateView(_AccionPrestamoMixin, FormView):
    permission_required = "prestamos.add_pagoprestamo"
    form_class = PagoForm
    template_name = "prestamos/pago_form.html"

    def get_initial(self):
        inicial = super().get_initial()
        r = services.resumen(self.prestamo)
        if r.proxima:
            inicial["monto"] = r.proxima.pendiente
        return inicial

    def get_context_data(self, **kwargs):
        return super().get_context_data(r=services.resumen(self.prestamo), **kwargs)

    def form_valid(self, form):
        d = form.cleaned_data
        try:
            pago, creado = services.registrar_pago(
                self.prestamo, usuario=self.request.user, tipo=d["tipo"], fecha=d["fecha"], monto=d["monto"],
                metodo_pago=d["metodo_pago"], cuenta_fondo=d["cuenta_fondo"], referencia=d["referencia"],
                observacion=d["observacion"], clave_idempotencia=d["clave_idempotencia"])
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        if creado:
            messages.success(self.request, f"{pago.get_tipo_display()} {pago.numero_recibo} registrado.")
        else:
            messages.warning(self.request, f"Este formulario ya se había enviado: el pago {pago.numero_recibo} "
                                           "no se registró dos veces.")
        return redirect("prestamos:pago_detalle", pk=pago.pk)


class PagoDetailView(PermisoMixin, DetailView):
    permission_required = "prestamos.view_pagoprestamo"
    template_name = "prestamos/pago_detalle.html"
    queryset = PagoPrestamo.objects.select_related("prestamo__afiliado", "prestamo__prestatario_externo",
                                                   "cuenta_fondo", "registrado_por", "anulado_por")

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if request.GET.get("formato") == "pdf":
            return respuesta_pdf("prestamos/recibo_pago_pdf.html",
                                 {"pago": self.object, "aplicaciones": self.object.aplicaciones.select_related("cuota"),
                                  "r": services.resumen(self.object.prestamo)},
                                 f"recibo-{self.object.numero_recibo}", request)
        return self.render_to_response(self.get_context_data(object=self.object))

    def get_context_data(self, **kwargs):
        return super().get_context_data(aplicaciones=self.object.aplicaciones.select_related("cuota"),
                                        r=services.resumen(self.object.prestamo), **kwargs)


class AnularPagoView(PermisoMixin, FormView):
    permission_required = "prestamos.anular_pagoprestamo"
    form_class = MotivoForm
    template_name = "prestamos/anular_pago.html"

    def dispatch(self, request, *args, **kwargs):
        self.pago = get_object_or_404(PagoPrestamo.objects.select_related("prestamo"), pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(pago=self.pago, **kwargs)

    def form_valid(self, form):
        try:
            services.anular_pago(self.pago, usuario=self.request.user, motivo=form.cleaned_data["motivo"])
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"Pago {self.pago.numero_recibo} anulado.")
        return redirect("prestamos:pago_detalle", pk=self.pago.pk)
