from django.contrib import admin

from apps.core.admin import SoloLecturaAdmin

from .models import Actividad, ExclusionActividad, MovimientoActividad, Subactividad

for modelo in (Actividad, Subactividad, MovimientoActividad, ExclusionActividad):
    admin.site.register(modelo, SoloLecturaAdmin)
