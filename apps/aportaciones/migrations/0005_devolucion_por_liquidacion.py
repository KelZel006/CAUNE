"""Tipo de movimiento con el que la liquidación de un afiliado le devuelve sus aportaciones."""
from django.db import migrations


def crear(apps, schema_editor):
    TipoMovimiento = apps.get_model("aportaciones", "TipoMovimiento")
    if not TipoMovimiento.objects.exists():  # bases nuevas: lo crea inicializar_caune
        return
    TipoMovimiento.objects.get_or_create(codigo="RAPO", defaults=dict(
        nombre="Devolución de aportaciones por liquidación", clase="APORTACION", naturaleza="SALIDA",
        participa_distribucion=True,
        descripcion="Solo la usa la liquidación de un afiliado que se retira. No se registra a mano."))


class Migration(migrations.Migration):
    dependencies = [("aportaciones", "0004_excedente_avalado")]

    operations = [migrations.RunPython(crear, migrations.RunPython.noop)]
