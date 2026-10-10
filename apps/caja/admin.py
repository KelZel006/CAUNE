from django.contrib import admin

from apps.core.admin import SoloLecturaAdmin

from .models import CategoriaCaja, MovimientoCaja

for modelo in (CategoriaCaja, MovimientoCaja):
    admin.site.register(modelo, SoloLecturaAdmin)
