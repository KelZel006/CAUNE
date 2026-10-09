from django.contrib import admin

from apps.core.admin import SoloLecturaAdmin

from .models import Actividad, MovimientoActividad, Subactividad

for modelo in (Actividad, Subactividad, MovimientoActividad):
    admin.site.register(modelo, SoloLecturaAdmin)
