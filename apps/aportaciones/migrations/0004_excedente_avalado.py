"""Decisión de CAUNE (10/10/2026): lo que un prestatario externo paga de más es depósito del afiliado que lo avala."""
from django.db import migrations


def crear(apps, schema_editor):
    TipoMovimiento = apps.get_model("aportaciones", "TipoMovimiento")
    if not TipoMovimiento.objects.exists():  # bases nuevas: lo crea inicializar_caune
        return
    TipoMovimiento.objects.get_or_create(codigo="EXA", defaults=dict(
        nombre="Excedente de préstamo avalado", clase="DEPOSITO", naturaleza="ENTRADA", participa_distribucion=False,
        descripcion="Lo que un prestatario externo paga de más queda como depósito del afiliado que lo avala."))


class Migration(migrations.Migration):
    dependencies = [("aportaciones", "0003_ganancias_a_aportaciones")]

    operations = [migrations.RunPython(crear, migrations.RunPython.noop)]
