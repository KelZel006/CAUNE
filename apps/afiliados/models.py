from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models


class Afiliado(models.Model):
    class Estado(models.TextChoices):
        ACTIVO = "ACTIVO", "Activo"
        INACTIVO = "INACTIVO", "Inactivo"

    codigo = models.CharField("código", max_length=20, unique=True, editable=False)
    nombres = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)
    identidad = models.CharField(
        "número de identidad",
        max_length=13,
        unique=True,
        validators=[RegexValidator(r"^\d{13}$", "La identidad debe tener 13 dígitos.")],
        error_messages={"unique": "Ya existe un afiliado con este número de identidad."},
    )
    telefono = models.CharField("teléfono", max_length=20, blank=True)
    direccion = models.TextField("dirección", blank=True)
    fecha_ingreso = models.DateField("fecha de ingreso")
    estado = models.CharField(max_length=8, choices=Estado.choices, default=Estado.ACTIVO, db_index=True)
    creado_en = models.DateTimeField("fecha de creación", auto_now_add=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["codigo"]
        verbose_name = "afiliado"
        verbose_name_plural = "afiliados"
        indexes = [models.Index(fields=["apellidos", "nombres"])]
        constraints = [
            models.CheckConstraint(condition=models.Q(estado__in=["ACTIVO", "INACTIVO"]), name="afiliado_estado_valido"),
        ]
        permissions = [
            ("cambiar_estado_afiliado", "Puede activar o inactivar afiliados"),
            ("ver_estado_cuenta", "Puede consultar estados de cuenta de afiliados"),
        ]

    def __str__(self):
        return f"{self.codigo} · {self.nombre_completo}"

    @property
    def nombre_completo(self):
        return f"{self.nombres} {self.apellidos}"

    @property
    def activo(self):
        return self.estado == self.Estado.ACTIVO

    def delete(self, *args, **kwargs):
        from django.core.exceptions import ValidationError

        raise ValidationError("Los afiliados no se eliminan; se inactivan para conservar su historial.")


class CambioEstadoAfiliado(models.Model):
    """Historial de activaciones e inactivaciones (necesario para la distribución por período)."""

    afiliado = models.ForeignKey(Afiliado, on_delete=models.PROTECT, related_name="cambios_estado")
    estado_anterior = models.CharField(max_length=8, choices=Afiliado.Estado.choices)
    estado_nuevo = models.CharField(max_length=8, choices=Afiliado.Estado.choices)
    fecha_efectiva = models.DateField()
    motivo = models.TextField()
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    registrado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha_efectiva", "-id"]
        verbose_name = "cambio de estado de afiliado"
        verbose_name_plural = "cambios de estado de afiliados"
