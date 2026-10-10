"""Decisión de CAUNE (10/10/2026): el número del préstamo es 1 (interno) o 2 (externo) + año + correlativo de 3
dígitos que se reinicia cada año. Los préstamos ya registrados se renumeran en orden de registro y el cambio queda
en el historial de auditoría."""
from django.db import migrations
from django.utils import timezone


def renumerar(apps, schema_editor):
    Prestamo = apps.get_model("prestamos", "Prestamo")
    Secuencia = apps.get_model("core", "Secuencia")
    HistorialAuditoria = apps.get_model("core", "HistorialAuditoria")
    contadores = {}
    for p in Prestamo.objects.order_by("registrado_en", "id"):
        if p.numero[:1] in "12" and p.numero.isdigit():
            continue  # ya tiene el formato nuevo
        anio = timezone.localtime(p.registrado_en).year
        contadores[anio] = contadores.get(anio, 0) + 1
        anterior = p.numero
        p.numero = f"{1 if p.tipo_prestatario == 'INTERNO' else 2}{anio}{contadores[anio]:03d}"
        p.save(update_fields=["numero"])
        HistorialAuditoria.objects.create(
            usuario_nombre="sistema", accion="MODIFICAR", entidad="prestamos.Prestamo", entidad_id=str(p.pk),
            descripcion=f"Nueva numeración de préstamos: {anterior} → {p.numero}",
            datos_antes={"numero": anterior}, datos_despues={"numero": p.numero})
    for anio, ultimo in contadores.items():
        s, _ = Secuencia.objects.get_or_create(prefijo=f"PR{anio}",
                                               defaults={"descripcion": f"Préstamos {anio}", "relleno": 3})
        if s.siguiente <= ultimo:
            s.siguiente = ultimo + 1
            s.save(update_fields=["siguiente"])


class Migration(migrations.Migration):
    dependencies = [
        ("prestamos", "0004_mora_congelada"),
        ("core", "0004_alter_parametro_grupo"),
    ]

    operations = [migrations.RunPython(renumerar, migrations.RunPython.noop)]
