from django.contrib import admin

from apps.core.admin import SoloLecturaAdmin

from .models import Liquidacion

admin.site.register(Liquidacion, SoloLecturaAdmin)
