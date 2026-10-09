from django.contrib import admin

from apps.core.admin import SoloLecturaAdmin

from .models import Afiliado, CambioEstadoAfiliado


@admin.register(Afiliado)
class AfiliadoAdmin(SoloLecturaAdmin):
    list_display = ("codigo", "nombres", "apellidos", "identidad", "estado", "fecha_ingreso")
    search_fields = ("codigo", "nombres", "apellidos", "identidad")
    list_filter = ("estado",)


admin.site.register(CambioEstadoAfiliado, SoloLecturaAdmin)
