"""Decisión de CAUNE (10/10/2026): las ganancias capitalizadas y lo pagado de más en préstamos van a aportaciones."""
from django.db import migrations


def reclasificar(apps, schema_editor):
    TipoMovimiento = apps.get_model("aportaciones", "TipoMovimiento")
    MovimientoAfiliado = apps.get_model("aportaciones", "MovimientoAfiliado")
    gan = TipoMovimiento.objects.filter(codigo="GAN").first()
    if gan is not None and not MovimientoAfiliado.objects.filter(tipo=gan).exists():
        gan.clase = "APORTACION"
        gan.participa_distribucion = True
        gan.descripcion = "Ganancias de una distribución que se suman a las aportaciones del afiliado."
        gan.save(update_fields=["clase", "participa_distribucion", "descripcion"])
    if TipoMovimiento.objects.filter(codigo="EXP").exists() or TipoMovimiento.objects.filter(
            nombre="Excedente de pago de préstamo").exists():
        return
    if TipoMovimiento.objects.exists():  # solo en bases ya inicializadas; las nuevas lo crea inicializar_caune
        TipoMovimiento.objects.create(
            codigo="EXP", nombre="Excedente de pago de préstamo", clase="APORTACION", naturaleza="ENTRADA",
            participa_distribucion=True,
            descripcion="Lo que el afiliado paga de más en su préstamo se suma a sus aportaciones.")


class Migration(migrations.Migration):
    dependencies = [("aportaciones", "0002_alter_tipomovimiento_participa_distribucion")]

    operations = [migrations.RunPython(reclasificar, migrations.RunPython.noop)]
