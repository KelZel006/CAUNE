import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.aportaciones.models import MetodoPago
from apps.core.models import CuentaFondo


class Actividad(models.Model):
    class Estado(models.TextChoices):
        ACTIVA = "ACTIVA", "Activa"
        CERRADA = "CERRADA", "Cerrada"

    codigo = models.CharField("código", max_length=20, unique=True, editable=False)
    nombre = models.CharField(max_length=150, unique=True)
    descripcion = models.TextField("descripción", blank=True)
    fecha_inicio = models.DateField("fecha de inicio")
    estado = models.CharField(max_length=7, choices=Estado.choices, default=Estado.ACTIVA, db_index=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha_inicio", "codigo"]
        verbose_name = "actividad económica"
        verbose_name_plural = "actividades económicas"
        permissions = [("cambiar_estado_actividad", "Puede cerrar o reabrir actividades")]

    def __str__(self):
        return f"{self.codigo} · {self.nombre}"

    @property
    def activa(self):
        return self.estado == self.Estado.ACTIVA

    def delete(self, *args, **kwargs):
        raise ValidationError("Las actividades no se eliminan; se cierran.")


class Subactividad(models.Model):
    actividad = models.ForeignKey(Actividad, on_delete=models.PROTECT, related_name="subactividades")
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField("descripción", blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ["actividad", "nombre"]
        verbose_name = "subactividad"
        verbose_name_plural = "subactividades"
        constraints = [models.UniqueConstraint(fields=["actividad", "nombre"], name="subactividad_nombre_unico")]

    def __str__(self):
        return self.nombre

    def delete(self, *args, **kwargs):
        raise ValidationError("Las subactividades no se eliminan; se desactivan.")


class MovimientoQuerySet(models.QuerySet):
    def confirmados(self):
        return self.filter(estado=MovimientoActividad.Estado.CONFIRMADO)

    def delete(self):
        raise ValidationError("Los ingresos y gastos no se eliminan; se anulan con motivo.")

    def update(self, **kwargs):
        raise ValidationError("Los ingresos y gastos no se modifican de forma masiva.")


class MovimientoActividad(models.Model):
    class Tipo(models.TextChoices):
        INGRESO = "INGRESO", "Ingreso"
        GASTO = "GASTO", "Gasto"

    class Estado(models.TextChoices):
        CONFIRMADO = "CONFIRMADO", "Confirmado"
        ANULADO = "ANULADO", "Anulado"

    CAMPOS_INMUTABLES = ("numero", "actividad_id", "subactividad_id", "tipo", "fecha", "concepto", "monto",
                         "metodo_pago", "cuenta_fondo_id", "referencia", "observacion", "registrado_por_id",
                         "clave_idempotencia")

    numero = models.CharField("número", max_length=20, unique=True, editable=False)
    actividad = models.ForeignKey(Actividad, on_delete=models.PROTECT, related_name="movimientos")
    subactividad = models.ForeignKey(Subactividad, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="movimientos")
    tipo = models.CharField(max_length=7, choices=Tipo.choices)
    fecha = models.DateField()
    concepto = models.CharField(max_length=200)
    monto = models.DecimalField(max_digits=14, decimal_places=2)
    # Dónde entró o de dónde salió el dinero: en la Fase 3 genera un único movimiento de caja (sin duplicar).
    metodo_pago = models.CharField("método de pago", max_length=20, choices=MetodoPago.choices)
    cuenta_fondo = models.ForeignKey(CuentaFondo, on_delete=models.PROTECT, related_name="movimientos_actividad",
                                     verbose_name="caja o cuenta")
    referencia = models.CharField(max_length=100, blank=True)
    observacion = models.TextField("observación", blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.CONFIRMADO, db_index=True)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    registrado_en = models.DateTimeField(auto_now_add=True)
    clave_idempotencia = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    anulado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    anulado_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.TextField(blank=True)

    objects = MovimientoQuerySet.as_manager()

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "ingreso o gasto de actividad"
        verbose_name_plural = "ingresos y gastos de actividades"
        indexes = [models.Index(fields=["actividad", "fecha"]), models.Index(fields=["fecha"])]
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name="mov_actividad_monto_positivo"),
            models.CheckConstraint(
                condition=(Q(estado="CONFIRMADO", anulado_por__isnull=True, anulado_en__isnull=True)
                           | (Q(estado="ANULADO", anulado_por__isnull=False, anulado_en__isnull=False)
                              & ~Q(motivo_anulacion=""))),
                name="mov_actividad_anulacion_coherente",
            ),
        ]
        permissions = [("anular_movimientoactividad", "Puede anular ingresos y gastos de actividades")]

    def __str__(self):
        return f"{self.numero} · {self.get_tipo_display()} · {self.monto}"

    @property
    def confirmado(self):
        return self.estado == self.Estado.CONFIRMADO

    @property
    def monto_con_signo(self):
        return -self.monto if self.tipo == self.Tipo.GASTO else self.monto

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original = type(self).objects.filter(pk=self.pk).values("estado", *self.CAMPOS_INMUTABLES).first()
            if original is not None:
                if any(original[c] != getattr(self, c) for c in self.CAMPOS_INMUTABLES):
                    raise ValidationError("Un registro confirmado no puede modificarse. Anúlelo y registre uno nuevo.")
                if original["estado"] == self.Estado.ANULADO:
                    raise ValidationError("Un registro anulado no puede modificarse.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los ingresos y gastos no se eliminan; se anulan con motivo.")
