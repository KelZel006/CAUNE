from django.contrib import admin

from apps.core.admin import SoloLecturaAdmin

from .models import MovimientoAfiliado, TipoMovimiento


@admin.register(MovimientoAfiliado)
class MovimientoAfiliadoAdmin(SoloLecturaAdmin):
    list_display = ("numero_operacion", "fecha", "afiliado", "tipo", "monto", "estado")
    list_filter = ("estado", "tipo")
    search_fields = ("numero_operacion", "afiliado__codigo", "afiliado__apellidos")


admin.site.register(TipoMovimiento, SoloLecturaAdmin)
