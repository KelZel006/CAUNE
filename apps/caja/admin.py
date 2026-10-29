from django.contrib import admin

from apps.core.admin import SoloLecturaAdmin

from .models import CategoriaCaja, ConciliacionBancaria, MovimientoCaja

for modelo in (CategoriaCaja, MovimientoCaja, ConciliacionBancaria):
    admin.site.register(modelo, SoloLecturaAdmin)
