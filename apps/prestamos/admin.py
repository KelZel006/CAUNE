from django.contrib import admin

from apps.core.admin import SoloLecturaAdmin

from .models import AplicacionPago, CuotaAmortizacion, PagoPrestamo, Prestamo, PrestatarioExterno

for modelo in (Prestamo, CuotaAmortizacion, PagoPrestamo, AplicacionPago, PrestatarioExterno):
    admin.site.register(modelo, SoloLecturaAdmin)
