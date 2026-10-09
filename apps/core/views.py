from datetime import date

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView

from apps.afiliados.models import Afiliado
from apps.aportaciones.models import MovimientoAfiliado
from apps.aportaciones.services import totales_generales

from . import auditoria, parametros
from .forms import (CuentaFondoForm, FiltroAuditoriaForm, ParametroForm, RolForm, SecuenciaForm,
                    UsuarioCrearForm, UsuarioEditarForm)
from .mixins import ListaMixin, PermisoMixin
from .models import CuentaFondo, HistorialAuditoria, HistorialParametro, Parametro, Secuencia

User = get_user_model()


class FormularioGenericoMixin:
    template_name = "core/form.html"
    titulo = ""
    cancelar_url = None

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.setdefault("titulo", self.titulo)
        ctx.setdefault("cancelar_url", self.cancelar_url)
        return ctx


# --------------------------------------------------------------------------- panel

class DashboardView(TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        usuario = self.request.user
        if usuario.has_perm("core.ver_dashboard_financiero"):
            hoy = timezone.localdate()
            inicio_mes = hoy.replace(day=1)
            movs_mes = MovimientoAfiliado.objects.confirmados().filter(fecha__gte=inicio_mes, fecha__lte=hoy)
            ctx.update(
                financiero=True,
                totales=totales_generales(),
                totales_mes_anterior=totales_generales(hasta=inicio_mes.replace(day=1) - date.resolution),
                afiliados_activos=Afiliado.objects.filter(estado=Afiliado.Estado.ACTIVO).count(),
                afiliados_inactivos=Afiliado.objects.filter(estado=Afiliado.Estado.INACTIVO).count(),
                movimientos_mes=movs_mes.count(),
                ultimos=MovimientoAfiliado.objects.select_related("afiliado", "tipo").order_by("-registrado_en")[:8],
                inicio_mes=inicio_mes,
            )
            if usuario.has_perm("prestamos.view_prestamo"):
                from apps.prestamos import services as ps
                from apps.prestamos.models import Prestamo
                ctx.update(ver_prestamos=True, cartera=ps.cartera_vigente(), intereses_mes=ps.intereses_cobrados(desde=inicio_mes, hasta=hoy),
                           prestamos_vigentes=Prestamo.objects.filter(estado=Prestamo.Estado.VIGENTE).count(),
                           por_desembolsar=Prestamo.objects.filter(estado=Prestamo.Estado.APROBADO).count())
            if usuario.has_perm("actividades.view_actividad"):
                from apps.actividades import services as acs
                ctx["actividades_anio"] = acs.resultado_general(desde=hoy.replace(month=1, day=1), hasta=hoy)
                ctx["anio"] = hoy.year
        return ctx


# --------------------------------------------------------------------------- configuración

class ConfiguracionView(TemplateView):
    template_name = "core/configuracion.html"


class ParametroListView(PermisoMixin, ListView):
    permission_required = "core.view_parametro"
    model = Parametro
    template_name = "core/parametros.html"
    paginate_by = None

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["historial"] = HistorialParametro.objects.select_related("parametro", "cambiado_por")[:20]
        return ctx


class ParametroUpdateView(PermisoMixin, FormularioGenericoMixin, FormView):
    permission_required = "core.change_parametro"
    form_class = ParametroForm
    cancelar_url = reverse_lazy("core:parametros")

    def dispatch(self, request, *args, **kwargs):
        self.parametro = get_object_or_404(Parametro, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "parametro": self.parametro}

    def get_context_data(self, **kwargs):
        return super().get_context_data(titulo=f"Modificar parámetro: {self.parametro.nombre}", **kwargs)

    def form_valid(self, form):
        valor = form.cleaned_data["valor"]
        if self.parametro.tipo == Parametro.Tipo.BOOLEANO:
            valor = "true" if valor else "false"
        try:
            _, cambio = parametros.actualizar(self.parametro, "" if valor is None else str(valor), self.request.user,
                                              form.cleaned_data.get("motivo", ""))
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, "Parámetro actualizado." if cambio else "Sin cambios.")
        return redirect("core:parametros")


class CuentaFondoListView(PermisoMixin, ListView):
    permission_required = "core.view_cuentafondo"
    model = CuentaFondo
    template_name = "core/cuentas.html"


class CuentaFondoCreateView(PermisoMixin, FormularioGenericoMixin, CreateView):
    permission_required = "core.add_cuentafondo"
    form_class = CuentaFondoForm
    titulo = "Nueva caja o cuenta bancaria"
    cancelar_url = reverse_lazy("core:cuentas")
    success_url = reverse_lazy("core:cuentas")

    def form_valid(self, form):
        with transaction.atomic():
            form.instance.creado_por = self.request.user
            respuesta = super().form_valid(form)
            auditoria.registrar(auditoria.Accion.CREAR, objeto=self.object,
                                despues=auditoria.instantanea(self.object))
        messages.success(self.request, "Caja o cuenta registrada.")
        return respuesta


class CuentaFondoUpdateView(PermisoMixin, FormularioGenericoMixin, UpdateView):
    permission_required = "core.change_cuentafondo"
    model = CuentaFondo
    form_class = CuentaFondoForm
    titulo = "Modificar caja o cuenta"
    cancelar_url = reverse_lazy("core:cuentas")
    success_url = reverse_lazy("core:cuentas")

    def form_valid(self, form):
        with transaction.atomic():
            antes = auditoria.instantanea(CuentaFondo.objects.get(pk=self.object.pk))
            respuesta = super().form_valid(form)
            a, d = auditoria.diferencias(antes, auditoria.instantanea(self.object))
            if d:
                auditoria.registrar(auditoria.Accion.MODIFICAR, objeto=self.object, antes=a, despues=d)
        messages.success(self.request, "Caja o cuenta actualizada.")
        return respuesta


class SecuenciaListView(PermisoMixin, ListView):
    permission_required = "core.view_secuencia"
    model = Secuencia
    template_name = "core/secuencias.html"


class SecuenciaUpdateView(PermisoMixin, FormularioGenericoMixin, UpdateView):
    permission_required = "core.change_secuencia"
    model = Secuencia
    form_class = SecuenciaForm
    titulo = "Modificar numeración"
    cancelar_url = reverse_lazy("core:secuencias")
    success_url = reverse_lazy("core:secuencias")

    @transaction.atomic
    def form_valid(self, form):
        antes = auditoria.instantanea(Secuencia.objects.select_for_update().get(pk=self.object.pk))
        respuesta = super().form_valid(form)
        a, d = auditoria.diferencias(antes, auditoria.instantanea(self.object))
        if d:
            auditoria.registrar(auditoria.Accion.CONFIGURAR, objeto=self.object, antes=a, despues=d)
        messages.success(self.request, "Numeración actualizada.")
        return respuesta


# --------------------------------------------------------------------------- usuarios y roles

def _datos_usuario(usuario):
    return {"username": usuario.username, "nombre": usuario.get_full_name(), "email": usuario.email,
            "activo": usuario.is_active, "roles": sorted(usuario.groups.values_list("name", flat=True))}


class UsuarioListView(PermisoMixin, ListaMixin, ListView):
    permission_required = "core.gestionar_usuarios"
    model = User
    template_name = "core/usuarios.html"
    campos_busqueda = ("username", "first_name", "last_name", "email")
    ordenes = {"usuario": "username", "nombre": "first_name", "ultimo": "last_login"}
    orden_defecto = "usuario"

    def get_queryset(self):
        return super().get_queryset().prefetch_related("groups")


class UsuarioCreateView(PermisoMixin, FormularioGenericoMixin, CreateView):
    permission_required = "core.gestionar_usuarios"
    form_class = UsuarioCrearForm
    titulo = "Nuevo usuario"
    cancelar_url = reverse_lazy("core:usuarios")
    success_url = reverse_lazy("core:usuarios")

    @transaction.atomic
    def form_valid(self, form):
        usuario = form.save(commit=False)
        usuario.set_password(form.cleaned_data["password1"])
        usuario.save()
        usuario.groups.set(form.cleaned_data["roles"])
        self.object = usuario
        auditoria.registrar(auditoria.Accion.CREAR, objeto=usuario, despues=_datos_usuario(usuario))
        messages.success(self.request, f"Usuario {usuario.username} creado.")
        return redirect(self.success_url)


class UsuarioUpdateView(PermisoMixin, FormularioGenericoMixin, UpdateView):
    permission_required = "core.gestionar_usuarios"
    model = User
    form_class = UsuarioEditarForm
    cancelar_url = reverse_lazy("core:usuarios")
    success_url = reverse_lazy("core:usuarios")

    def get_context_data(self, **kwargs):
        return super().get_context_data(titulo=f"Modificar usuario {self.object.username}", **kwargs)

    def get_object(self, queryset=None):
        usuario = super().get_object(queryset)
        if usuario.is_superuser and not self.request.user.is_superuser:
            raise PermissionDenied
        return usuario

    @transaction.atomic
    def form_valid(self, form):
        usuario = self.object
        antes = _datos_usuario(User.objects.get(pk=usuario.pk))
        if usuario.pk == self.request.user.pk and not form.cleaned_data["is_active"]:
            form.add_error("is_active", "No puede desactivar su propio usuario.")
            return self.form_invalid(form)
        usuario = form.save()
        usuario.groups.set(form.cleaned_data["roles"])
        a, d = auditoria.diferencias(antes, _datos_usuario(usuario))
        if d:
            auditoria.registrar(auditoria.Accion.MODIFICAR, objeto=usuario, antes=a, despues=d)
        messages.success(self.request, "Usuario actualizado.")
        return redirect(self.success_url)


class UsuarioPasswordView(PermisoMixin, FormularioGenericoMixin, FormView):
    permission_required = "core.gestionar_usuarios"
    form_class = SetPasswordForm
    cancelar_url = reverse_lazy("core:usuarios")

    def dispatch(self, request, *args, **kwargs):
        self.usuario = get_object_or_404(User, pk=kwargs["pk"])
        if self.usuario.is_superuser and not request.user.is_superuser:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.usuario}

    def get_context_data(self, **kwargs):
        return super().get_context_data(titulo=f"Restablecer contraseña de {self.usuario.username}", **kwargs)

    def form_valid(self, form):
        form.save()
        auditoria.registrar(auditoria.Accion.MODIFICAR, objeto=self.usuario, descripcion="Contraseña restablecida")
        messages.success(self.request, "Contraseña restablecida.")
        return redirect("core:usuarios")


class RolListView(PermisoMixin, ListView):
    permission_required = "core.gestionar_roles"
    model = Group
    template_name = "core/roles.html"
    ordering = ["name"]

    def get_queryset(self):
        return super().get_queryset().prefetch_related("permissions")


class RolGuardarMixin:
    @transaction.atomic
    def form_valid(self, form):
        antes = None
        if form.instance.pk:
            g = Group.objects.get(pk=form.instance.pk)
            antes = {"nombre": g.name, "permisos": sorted(g.permissions.values_list("codename", flat=True))}
        respuesta = super().form_valid(form)
        despues = {"nombre": self.object.name,
                   "permisos": sorted(self.object.permissions.values_list("codename", flat=True))}
        auditoria.registrar(auditoria.Accion.MODIFICAR if antes else auditoria.Accion.CREAR, objeto=self.object,
                            antes=antes, despues=despues)
        messages.success(self.request, "Rol guardado.")
        return respuesta


class RolCreateView(PermisoMixin, FormularioGenericoMixin, RolGuardarMixin, CreateView):
    permission_required = "core.gestionar_roles"
    form_class = RolForm
    titulo = "Nuevo rol"
    template_name = "core/rol_form.html"
    cancelar_url = reverse_lazy("core:roles")
    success_url = reverse_lazy("core:roles")


class RolUpdateView(PermisoMixin, FormularioGenericoMixin, RolGuardarMixin, UpdateView):
    permission_required = "core.gestionar_roles"
    model = Group
    form_class = RolForm
    titulo = "Modificar rol"
    template_name = "core/rol_form.html"
    cancelar_url = reverse_lazy("core:roles")
    success_url = reverse_lazy("core:roles")


# --------------------------------------------------------------------------- auditoría

class AuditoriaListView(PermisoMixin, ListaMixin, ListView):
    permission_required = "core.ver_auditoria"
    model = HistorialAuditoria
    template_name = "core/auditoria.html"
    paginate_by = 50
    campos_busqueda = ("usuario_nombre", "entidad", "entidad_id", "descripcion")
    filtro_form_class = FiltroAuditoriaForm

    def filtrar(self, qs, datos):
        if datos.get("desde"):
            qs = qs.filter(fecha__date__gte=datos["desde"])
        if datos.get("hasta"):
            qs = qs.filter(fecha__date__lte=datos["hasta"])
        if datos.get("accion"):
            qs = qs.filter(accion=datos["accion"])
        if datos.get("usuario"):
            qs = qs.filter(usuario=datos["usuario"])
        return qs


def inicio(request):
    return redirect(reverse("core:dashboard"))
