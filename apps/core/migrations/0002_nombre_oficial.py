from django.db import migrations

ANTERIOR = "Cooperativa Familiar CAUNE"
OFICIAL = "Caja de Ahorro Unión y Esfuerzo"


def aplicar_nombre_oficial(apps, schema_editor):
    """Solo reemplaza el valor por defecto anterior; respeta un nombre que alguien ya haya cambiado."""
    Parametro = apps.get_model("core", "Parametro")
    Parametro.objects.filter(clave="coop.nombre", valor=ANTERIOR).update(valor=OFICIAL)


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(aplicar_nombre_oficial, migrations.RunPython.noop)]
