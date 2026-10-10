from django.contrib import admin

from apps.core.admin import SoloLecturaAdmin

from .models import Distribucion, FondoDistribucion, LineaDistribucion, PagoGanancia

for modelo in (Distribucion, FondoDistribucion, LineaDistribucion, PagoGanancia):
    admin.site.register(modelo, SoloLecturaAdmin)
