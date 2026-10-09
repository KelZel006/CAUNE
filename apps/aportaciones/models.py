import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.afiliados.models import Afiliado
from apps.core.models import CuentaFondo


class TipoMovimiento(models.Model):
    """Tipos configurables. `clase` + `naturaleza` definen la clasificación contable del movimiento."""

    class Clase(models.TextChoices):
        APORTACION = "APORTACION", "Aportación (capital del afiliado)"
        DEPOSITO = "DEPOSITO", "Depósito reembolsable"

    class Naturaleza(models.TextChoices):
        ENTRADA = "ENTRADA", "Entrada (aumenta el saldo)"
        SALIDA = "SALIDA", "Retiro (disminuye el saldo)"

    codigo = models.CharField("código", max_length=10, unique=True)
    nombre = models.CharField(max_length=80, unique=True)
    clase = models.CharField(max_length=10, choices=Clase.choices)
    naturaleza = models.CharField(max_length=7, choices=Naturaleza.choices)
    participa_distribucion = models.BooleanField(
        "cuenta para la distribución de ganancias",
        default=False,
        help_text="Pendiente de aprobación por CAUNE (decisión A3). Se usará en la Fase 3.",
    )
    descripcion = models.TextField("descripción", blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["clase", "naturaleza", "nombre"]
        verbose_name = "tipo de movimiento"
        verbose_name_plural = "tipos de movimiento"

    def __str__(self):
        return self.nombre

    @property
    def es_retiro(self):
        return self.naturaleza == self.Naturaleza.SALIDA

    def delete(self, *args, **kwargs):
        raise ValidationError("Los tipos de movimiento no se eliminan; se desactivan.")


class MetodoPago(models.TextChoices):
    EFECTIVO = "EFECTIVO", "Efectivo"
    TRANSFERENCIA = "TRANSFERENCIA", "Transferencia bancaria"
    DEPOSITO_BANCARIO = "DEPOSITO_BANCARIO", "Depósito en banco"
    CHEQUE = "CHEQUE", "Cheque"


class MovimientoQuerySet(models.QuerySet):
    def confirmados(self):
        return self.filter(estado=MovimientoAfiliado.Estado.CONFIRMADO)

    def delete(self):
        raise ValidationError("Los movimientos financieros no se eliminan; se anulan con motivo.")

    def update(self, **kwargs):
        raise ValidationError("Los movimientos financieros no se modifican de forma masiva.")


class MovimientoAfiliado(models.Model):
    """Aportaciones, depósitos y retiros de afiliados (equivale a «Deposito Afiliado» en Airtable)."""

    class Estado(models.TextChoices):
        CONFIRMADO = "CONFIRMADO", "Confirmado"
        ANULADO = "ANULADO", "Anulado"

    CAMPOS_INMUTABLES = (
        "numero_operacion", "afiliado_id", "tipo_id", "fecha", "monto", "metodo_pago", "cuenta_fondo_id",
        "referencia", "observacion", "registrado_por_id", "clave_idempotencia",
    )

    numero_operacion = models.CharField("número de operación", max_length=20, unique=True, editable=False)
    afiliado = models.ForeignKey(Afiliado, on_delete=models.PROTECT, related_name="movimientos")
    tipo = models.ForeignKey(TipoMovimiento, on_delete=models.PROTECT, related_name="movimientos",
                             verbose_name="tipo de movimiento")
    fecha = models.DateField()
    monto = models.DecimalField(max_digits=14, decimal_places=2)
    metodo_pago = models.CharField("método de pago", max_length=20, choices=MetodoPago.choices)
    cuenta_fondo = models.ForeignKey(CuentaFondo, on_delete=models.PROTECT, related_name="movimientos_afiliado",
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
    motivo_anulacion = models.TextField("motivo de anulación", blank=True)

    objects = MovimientoQuerySet.as_manager()

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "movimiento de afiliado"
        verbose_name_plural = "movimientos de afiliados"
        indexes = [
            models.Index(fields=["afiliado", "fecha"]),
            models.Index(fields=["fecha"]),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(monto__gt=0), name="mov_afiliado_monto_positivo"),
            models.CheckConstraint(
                condition=(
                    models.Q(estado="CONFIRMADO", anulado_por__isnull=True, anulado_en__isnull=True)
                    | (models.Q(estado="ANULADO", anulado_por__isnull=False, anulado_en__isnull=False)
                       & ~models.Q(motivo_anulacion=""))
                ),
                name="mov_afiliado_anulacion_coherente",
            ),
        ]
        permissions = [("anular_movimientoafiliado", "Puede anular movimientos de afiliados")]

    def __str__(self):
        return f"{self.numero_operacion} · {self.tipo} · {self.monto}"

    @property
    def confirmado(self):
        return self.estado == self.Estado.CONFIRMADO

    @property
    def monto_con_signo(self):
        return -self.monto if self.tipo.es_retiro else self.monto

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original = (type(self).objects.filter(pk=self.pk)
                        .values("estado", *self.CAMPOS_INMUTABLES).first())
            if original is not None:
                cambiados = [c for c in self.CAMPOS_INMUTABLES if original[c] != getattr(self, c)]
                if cambiados:
                    raise ValidationError(
                        "Un movimiento confirmado no puede modificarse. Anúlelo y registre uno nuevo."
                    )
                if original["estado"] == self.Estado.ANULADO:
                    raise ValidationError("Un movimiento anulado no puede modificarse.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los movimientos financieros no se eliminan; se anulan con motivo.")
