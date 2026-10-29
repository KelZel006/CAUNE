from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView

from apps.afiliados.views import _agregar_errores
from apps.core import auditoria
from apps.core.dinero import CERO
from apps.core.mixins import PermisoMixin

from . import services
from .forms import CategoriaCajaForm, MotivoForm, MovimientoCajaForm
from .models import CategoriaCaja, MovimientoCaja


class CajaView(PermisoMixin, TemplateView):
    permission_required = "caja.view_movimientocaja"
    template_name = "caja/indice.html"

    def get_context_data(self, **kwargs):
        saldos = [s for s in services.saldos_por_cuenta() if s["cuenta"].activa or s["saldo"]]
        return super().get_context_data(
            saldos=saldos, total=sum((s["saldo"] for s in saldos), CERO),
            total_cajas=sum((s["saldo"] for s in saldos if s["cuenta"].tipo == "CAJA"), CERO),
            total_bancos=sum((s["saldo"] for s in saldos if s["cuenta"].tipo == "BANCO"), CERO),
            movimientos=MovimientoCaja.objects.select_related("categoria", "cuenta_fondo", "cuenta_destino")[:30],
            ultimas=services.lineas()[-12:][::-1], **kwargs)


class MovimientoCreateView(PermisoMixin, FormView):
    permission_required = "caja.add_movimientocaja"
    form_class = MovimientoCajaForm
    template_name = "caja/movimiento_form.html"

    def dispatch(self, request, *args, **kwargs):
        tipo = request.GET.get("tipo", "")
        self.tipo = tipo if tipo in MovimientoCaja.Tipo.values else MovimientoCaja.Tipo.INGRESO
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "tipo": self.tipo}

    def get_initial(self):
        cuenta = self.request.GET.get("cuenta", "")
        return {"cuenta_fondo": int(cuenta)} if cuenta.isdigit() else {}

    def get_context_data(self, **kwargs):
        return super().get_context_data(tipo=self.tipo, tipo_nombre=MovimientoCaja.Tipo(self.tipo).label, **kwargs)

    def form_valid(self, form):
        d = form.cleaned_data
        try:
            mov, creado = services.registrar_movimiento(
                tipo=self.tipo, fecha=d["fecha"], concepto=d["concepto"], monto=d["monto"],
                metodo_pago=d["metodo_pago"], cuenta_fondo=d["cuenta_fondo"], categoria=d.get("categoria"),
                cuenta_destino=d.get("cuenta_destino"), referencia=d["referencia"], observacion=d["observacion"],
                usuario=self.request.user, clave_idempotencia=d["clave_idempotencia"])
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        if creado:
            messages.success(self.request, f"{mov.get_tipo_display()} {mov.numero} registrado.")
        else:
            messages.warning(self.request, f"Este formulario ya se había enviado: {mov.numero} no se registró dos veces.")
        return redirect("caja:detalle", pk=mov.pk)


class MovimientoDetailView(PermisoMixin, DetailView):
    permission_required = "caja.view_movimientocaja"
    model = MovimientoCaja
    template_name = "caja/detalle.html"

    def get(self, request, *args, **kwargs):
        if request.GET.get("formato") == "pdf":
            from apps.core.exportar import respuesta_pdf
            mov = self.get_object()
            return respuesta_pdf("caja/comprobante_pdf.html", {"m": mov}, f"comprobante-{mov.numero}", request)
        return super().get(request, *args, **kwargs)


class AnularView(PermisoMixin, FormView):
    permission_required = "caja.anular_movimientocaja"
    form_class = MotivoForm
    template_name = "caja/anular.html"

    def dispatch(self, request, *args, **kwargs):
        self.mov = get_object_or_404(MovimientoCaja, pk=kwargs["pk"])
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
        return redirect("caja:detalle", pk=self.mov.pk)


# --------------------------------------------------------------------------- categorías

class CategoriaListView(PermisoMixin, ListView):
    permission_required = "caja.view_categoriacaja"
    model = CategoriaCaja
    template_name = "caja/categorias.html"


class _CategoriaMixin(PermisoMixin):
    model = CategoriaCaja
    form_class = CategoriaCajaForm
    template_name = "core/form.html"

    def get_context_data(self, **kwargs):
        return super().get_context_data(cancelar_url=reverse("caja:categorias"), **kwargs)


class CategoriaCreateView(_CategoriaMixin, CreateView):
    permission_required = "caja.add_categoriacaja"

    def get_context_data(self, **kwargs):
        return super().get_context_data(titulo="Nueva categoría de caja", **kwargs)

    @transaction.atomic
    def form_valid(self, form):
        categoria = form.save()
        auditoria.registrar(auditoria.Accion.CREAR, usuario=self.request.user, objeto=categoria,
                            despues=auditoria.instantanea(categoria))
        messages.success(self.request, "Categoría creada.")
        return redirect("caja:categorias")


class CategoriaUpdateView(_CategoriaMixin, UpdateView):
    permission_required = "caja.change_categoriacaja"

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "bloquear_tipo": services.categoria_tiene_movimientos(self.object)}

    def get_context_data(self, **kwargs):
        return super().get_context_data(titulo=f"Modificar categoría · {self.object.nombre}", **kwargs)

    @transaction.atomic
    def form_valid(self, form):
        antes = auditoria.instantanea(CategoriaCaja.objects.get(pk=self.object.pk))
        categoria = form.save()
        a, d = auditoria.diferencias(antes, auditoria.instantanea(categoria))
        if d:
            auditoria.registrar(auditoria.Accion.MODIFICAR, usuario=self.request.user, objeto=categoria, antes=a,
                                despues=d)
        messages.success(self.request, "Categoría actualizada.")
        return redirect("caja:categorias")


# --------------------------------------------------------------------------- conciliación bancaria

from decimal import Decimal, InvalidOperation  # noqa: E402

from apps.core.exportar import respuesta_pdf  # noqa: E402

from . import conciliacion  # noqa: E402
from .forms import ConciliacionForm  # noqa: E402
from .models import ConciliacionBancaria  # noqa: E402


class ConciliacionListView(PermisoMixin, ListView):
    permission_required = "caja.view_conciliacionbancaria"
    model = ConciliacionBancaria
    template_name = "caja/conciliaciones.html"
    paginate_by = 30

    def get_queryset(self):
        return ConciliacionBancaria.objects.select_related("cuenta", "registrado_por", "cerrado_por")


class ConciliacionCreateView(PermisoMixin, FormView):
    permission_required = "caja.add_conciliacionbancaria"
    form_class = ConciliacionForm
    template_name = "core/form.html"

    def get_context_data(self, **kwargs):
        return super().get_context_data(titulo="Nueva conciliación bancaria",
                                        cancelar_url=reverse("caja:conciliaciones"), **kwargs)

    def form_valid(self, form):
        try:
            conc = conciliacion.crear(usuario=self.request.user, **form.cleaned_data)
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"Conciliación {conc.numero} creada. Marque las partidas que refleja el banco.")
        return redirect("caja:conciliacion", pk=conc.pk)


class ConciliacionDetailView(PermisoMixin, DetailView):
    permission_required = "caja.view_conciliacionbancaria"
    model = ConciliacionBancaria
    template_name = "caja/conciliacion.html"

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if request.GET.get("formato") == "pdf":
            return respuesta_pdf("caja/conciliacion_pdf.html", self.get_context_data(object=self.object),
                                 f"conciliacion-{self.object.numero}", request)
        return self.render_to_response(self.get_context_data(object=self.object))

    def get_context_data(self, **kwargs):
        r = conciliacion.calcular(self.object)
        return super().get_context_data(c=self.object, r=r,
                                        en_transito=[l for l, marcada in r.partidas if not marcada], **kwargs)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        usuario = request.user
        try:
            saldo = Decimal(request.POST.get("saldo_banco", "").replace(",", ""))
        except InvalidOperation:
            messages.error(request, "El saldo del banco no es un número válido.")
            return redirect("caja:conciliacion", pk=self.object.pk)
        try:
            if usuario.has_perm("caja.change_conciliacionbancaria"):
                conciliacion.guardar_marcas(self.object, numeros=request.POST.getlist("partidas"),
                                            saldo_banco=saldo.quantize(Decimal("0.01")), usuario=usuario)
            if request.POST.get("accion") == "cerrar":
                conciliacion.cerrar(self.object, usuario=usuario)
                messages.success(request, f"Conciliación {self.object.numero} cerrada: cuadra con el banco.")
            else:
                messages.success(request, "Partidas guardadas.")
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        return redirect("caja:conciliacion", pk=self.object.pk)


class ConciliacionAnularView(PermisoMixin, FormView):
    permission_required = "caja.anular_conciliacionbancaria"
    form_class = MotivoForm
    template_name = "caja/conciliacion_anular.html"

    def dispatch(self, request, *args, **kwargs):
        self.conc = get_object_or_404(ConciliacionBancaria, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(c=self.conc, **kwargs)

    def form_valid(self, form):
        try:
            conciliacion.anular(self.conc, usuario=self.request.user, motivo=form.cleaned_data["motivo"])
        except ValidationError as error:
            _agregar_errores(form, error)
            return self.form_invalid(form)
        messages.success(self.request, f"Conciliación {self.conc.numero} anulada.")
        return redirect("caja:conciliacion", pk=self.conc.pk)
