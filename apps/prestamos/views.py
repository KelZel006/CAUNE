from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import DetailView, FormView, ListView

from apps.afiliados.views import _agregar_errores
from apps.core.exportar import respuesta_pdf, respuesta_xlsx
from apps.core.mixins import ListaMixin, PermisoMixin

from . import services
from .forms import (DesembolsoForm, FiltroPrestamosForm, MotivoForm, PagoForm, PrestamoForm, PrestatarioExternoForm,
                    ResponsableForm)
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
                                        tasa_externa=services.tasa_configurada(Prestamo.Tipo.EXTERNO),
                                        mora_interna=services.tasa_mora_configurada(Prestamo.Tipo.INTERNO),
                                        mora_externa=services.tasa_mora_configurada(Prestamo.Tipo.EXTERNO), **kwargs)

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
                afiliado_responsable=d["afiliado_responsable"],
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
                                               "excepcion_autorizada_por", "cuenta_desembolso", "afiliado_responsable")

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.resumen = services.resumen(self.object)
        formato = request.GET.get("formato")
        if formato == "pdf":
            r = self.resumen
            cuotas = [c.cuota for c in r.cuotas]
            return respuesta_pdf("prestamos/cuadro_pdf.html", {
                "p": self.object, "r": r,
                "total_intereses": sum((c.interes for c in cuotas), 0),
                "total_cuotas": sum((c.cuota for c in cuotas), 0),
                "resumen_pdf": [("Saldo de capital", r.saldo_capital), ("Intereses cobrados", r.intereses_cobrados),
                                ("Intereses pendientes", r.intereses_pendientes), ("Mora pendiente", r.mora_pendiente),
                                ("Total pendiente", r.total_pendiente),
                                ("Cuotas pagadas", f"{r.cuotas_pagadas} de {self.object.plazo}")],
            }, f"cuadro-{self.object.numero}", request)
        if formato == "xlsx":
            filas = [[c.cuota.numero, c.cuota.fecha_vencimiento.strftime("%d/%m/%Y"), c.cuota.saldo_inicial,
                      c.cuota.capital, c.cuota.interes, c.cuota.cuota, c.cuota.saldo_final, c.capital_pagado,
                      c.interes_pagado, c.pendiente, c.dias_atraso, c.mora, c.estado.title()]
                     for c in self.resumen.cuotas]
            p = self.object
            return respuesta_xlsx(
                f"Cuadro {p.numero}",
                ["N.º", "Vencimiento", "Saldo inicial", "Capital", "Interés", "Cuota", "Saldo final",
                 "Capital pagado", "Interés pagado", "Pendiente", "Días de atraso", "Mora generada", "Estado"],
                filas, f"cuadro-{p.numero}", columnas_monto=(2, 3, 4, 5, 6, 7, 8, 9, 11),
                subtitulo=f"{p.prestatario_nombre} · L {p.monto_aprobado:,.2f} al {p.tasa:g} % mensual · "
                          f"{p.plazo} cuotas · {p.get_metodo_amortizacion_display()}")
        return self.render_to_response(self.get_context_data(object=self.object))

    def get_context_data(self, **kwargs):
        return super().get_context_data(r=self.resumen, pagos=self.object.pagos.select_related("registrado_por"),
                                        interes_total=sum((c.cuota.interes for c in self.resumen.cuotas), 0),
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
            inicial["monto"] = r.proxima.pendiente + r.mora_pendiente
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
                                  "saldo_despues": services.saldo_despues_de_pago(self.object)},
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


class ResponsableView(_AccionPrestamoMixin, FormView):
    permission_required = "prestamos.change_prestamo"
    form_class = ResponsableForm
    template_name = "prestamos/responsable.html"

    def get_initial(self):
        return {"afiliado": self.prestamo.afiliado_responsable_id}

    def form_valid(self, form):
        try:
            services.cambiar_responsable(self.prestamo, afiliado=form.cleaned_data["afiliado"],
                                         usuario=self.request.user, motivo=form.cleaned_data["motivo"])
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, "Afiliado responsable actualizado.")
        return redirect("prestamos:detalle", pk=self.prestamo.pk)


class PrestatarioExternoView(_AccionPrestamoMixin, FormView):
    """Corrige los datos del prestatario externo de un préstamo."""
    permission_required = "prestamos.change_prestamo"
    form_class = PrestatarioExternoForm
    template_name = "prestamos/externo.html"

    def get(self, request, *args, **kwargs):
        if self.prestamo.prestatario_externo_id is None:
            messages.error(request, "Este préstamo no es de un prestatario externo.")
            return redirect("prestamos:detalle", pk=self.prestamo.pk)
        return super().get(request, *args, **kwargs)

    def get_initial(self):
        e = self.prestamo.prestatario_externo
        return {"nombre_completo": e.nombre_completo, "identidad": e.identidad, "telefono": e.telefono,
                "direccion": e.direccion} if e else {}

    def get_context_data(self, **kwargs):
        otros = []
        if self.prestamo.prestatario_externo_id:
            otros = (Prestamo.objects.filter(prestatario_externo_id=self.prestamo.prestatario_externo_id)
                     .exclude(pk=self.prestamo.pk).order_by("numero"))
        return super().get_context_data(otros=otros, **kwargs)

    def form_valid(self, form):
        if self.prestamo.prestatario_externo_id is None:
            form.add_error(None, "Este préstamo no es de un prestatario externo.")
            return self.form_invalid(form)
        datos = dict(form.cleaned_data)
        motivo = datos.pop("motivo")
        try:
            services.actualizar_externo(self.prestamo.prestatario_externo, datos, usuario=self.request.user,
                                        motivo=motivo)
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, "Datos del prestatario externo actualizados.")
        return redirect("prestamos:detalle", pk=self.prestamo.pk)


class ComprobanteDesembolsoView(PermisoMixin, DetailView):
    """Comprobante de desembolso del préstamo (PDF con original y copia)."""
    permission_required = "prestamos.view_prestamo"
    queryset = Prestamo.objects.select_related("afiliado", "prestatario_externo", "afiliado_responsable",
                                               "cuenta_desembolso", "desembolsado_por")

    def get(self, request, *args, **kwargs):
        p = self.get_object()
        if p.fecha_desembolso is None:
            messages.error(request, "El préstamo todavía no se ha desembolsado.")
            return redirect("prestamos:detalle", pk=p.pk)
        intereses = sum((c.interes for c in p.cuotas.all()), 0)
        return respuesta_pdf("prestamos/desembolso_pdf.html",
                             {"p": p, "intereses_cuadro": intereses, "total_cuadro": p.monto_aprobado + intereses},
                             f"desembolso-{p.numero}", request)
