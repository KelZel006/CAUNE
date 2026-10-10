"""Asigna la tasa de mora vigente a los préstamos registrados antes de que existiera la mora."""
from decimal import Decimal

from django.db import migrations

POR_DEFECTO = {"INTERNO": ("prestamos.tasa_mora_interna", Decimal("1.00")),
               "EXTERNO": ("prestamos.tasa_mora_externa", Decimal("5.00"))}


def asignar(apps, schema_editor):
    Prestamo = apps.get_model("prestamos", "Prestamo")
    Parametro = apps.get_model("core", "Parametro")
    gracia = Parametro.objects.filter(clave="prestamos.dias_gracia_mora").values_list("valor", flat=True).first()
    for tipo, (clave, defecto) in POR_DEFECTO.items():
        valor = Parametro.objects.filter(clave=clave).values_list("valor", flat=True).first()
        for p in Prestamo.objects.filter(tipo_prestatario=tipo):
            p.tasa_mora = Decimal(valor) if valor else defecto
            p.dias_gracia_mora = int(gracia) if gracia else 0
            p.save(update_fields=["tasa_mora", "dias_gracia_mora"])


class Migration(migrations.Migration):
    dependencies = [
        ("prestamos", "0002_mora_responsable_excedente"),
        ("core", "0004_alter_parametro_grupo"),
    ]

    operations = [migrations.RunPython(asignar, migrations.RunPython.noop)]
