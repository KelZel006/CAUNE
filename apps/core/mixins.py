from functools import reduce
from operator import or_

from django.contrib.auth.mixins import PermissionRequiredMixin
from django.db.models import Q


class PermisoMixin(PermissionRequiredMixin):
    """Valida permisos en el servidor; sin permiso responde 403 (no redirige)."""

    raise_exception = True


class ListaMixin:
    """Búsqueda (?q=), ordenamiento (?orden=) y paginación para ListView."""

    paginate_by = 25
    campos_busqueda = ()
    ordenes = {}
    orden_defecto = ""
    filtro_form_class = None

    def get_filtro_form(self):
        if not hasattr(self, "_filtro_form"):
            self._filtro_form = self.filtro_form_class(self.request.GET or None) if self.filtro_form_class else None
        return self._filtro_form

    def filtrar(self, qs, datos):
        return qs

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.GET.get("q", "").strip()
        if q and self.campos_busqueda:
            condiciones = []
            for palabra in q.split():
                condiciones.append(reduce(or_, (Q(**{f"{c}__icontains": palabra}) for c in self.campos_busqueda)))
            for condicion in condiciones:
                qs = qs.filter(condicion)
        form = self.get_filtro_form()
        if form is not None and form.is_valid():
            qs = self.filtrar(qs, form.cleaned_data)
        orden = self.request.GET.get("orden", self.orden_defecto)
        clave = orden.lstrip("-")
        if clave in self.ordenes:
            prefijo = "-" if orden.startswith("-") else ""
            qs = qs.order_by(f"{prefijo}{self.ordenes[clave]}", "pk")
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filtro_form"] = self.get_filtro_form()
        ctx["q"] = self.request.GET.get("q", "")
        ctx["orden_actual"] = self.request.GET.get("orden", self.orden_defecto)
        params = self.request.GET.copy()
        params.pop("page", None)
        ctx["params_sin_pagina"] = params.urlencode()
        return ctx
