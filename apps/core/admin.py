from django.contrib import admin

from .models import CuentaFondo, HistorialAuditoria, HistorialParametro, Parametro, Secuencia


class SoloLecturaAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(HistorialAuditoria)
class HistorialAuditoriaAdmin(SoloLecturaAdmin):
    list_display = ("fecha", "usuario_nombre", "accion", "entidad", "entidad_id", "ip")
    list_filter = ("accion", "entidad")
    search_fields = ("usuario_nombre", "descripcion", "entidad_id")


@admin.register(HistorialParametro)
class HistorialParametroAdmin(SoloLecturaAdmin):
    list_display = ("cambiado_en", "parametro", "valor_anterior", "valor_nuevo", "cambiado_por")


# Los parámetros, cajas y numeración se administran desde la aplicación (con auditoría);
# en el admin técnico solo se consultan.
for modelo in (Parametro, CuentaFondo, Secuencia):
    admin.site.register(modelo, SoloLecturaAdmin)
