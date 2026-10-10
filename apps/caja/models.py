import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.aportaciones.models import MetodoPago
from apps.core.models import CuentaFondo


class CategoriaCaja(models.Model):
    """Clasifica los ingresos y egresos de caja que no vienen de afiliados, préstamos ni actividades."""

    class Tipo(models.TextChoices):
        INGRESO = "INGRESO", "Ingreso"
        EGRESO = "EGRESO", "Egreso"

    nombre = models.CharField(max_length=100, unique=True)
    tipo = models.CharField(max_length=7, choices=Tipo.choices)
    afecta_utilidades = models.BooleanField(
        "cuenta como utilidad o gasto a repartir", default=True,
        help_text="Sí: suma (ingreso) o resta (egreso) a la utilidad general que se reparte entre los afiliados. "
                  "No: solo mueve dinero (por ejemplo, el saldo inicial de la caja).",
    )
    descripcion = models.TextField("descripción", blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ["tipo", "nombre"]
        verbose_name = "categoría de caja"
        verbose_name_plural = "categorías de caja"

    def __str__(self):
        return self.nombre

    def delete(self, *args, **kwargs):
        raise ValidationError("Las categorías no se eliminan; se desactivan.")


class MovimientoQuerySet(models.QuerySet):
    def confirmados(self):
        return self.filter(estado=MovimientoCaja.Estado.CONFIRMADO)

    def delete(self):
        raise ValidationError("Los movimientos de caja no se eliminan; se anulan con motivo.")

    def update(self, **kwargs):
        raise ValidationError("Los movimientos de caja no se modifican de forma masiva.")


class MovimientoCaja(models.Model):
    """Ingresos y egresos varios de caja, y transferencias entre cajas y cuentas bancarias.

    Las operaciones de afiliados, préstamos, actividades y ganancias NO se registran aquí:
    el libro de caja las toma de su propio registro, así ninguna se cuenta dos veces.
    """

    class Tipo(models.TextChoices):
        INGRESO = "INGRESO", "Ingreso"
        EGRESO = "EGRESO", "Egreso"
        TRANSFERENCIA = "TRANSFERENCIA", "Transferencia entre cajas y cuentas"

    class Estado(models.TextChoices):
        CONFIRMADO = "CONFIRMADO", "Confirmado"
        ANULADO = "ANULADO", "Anulado"

    CAMPOS_INMUTABLES = ("numero", "tipo", "categoria_id", "fecha", "concepto", "monto", "metodo_pago",
                         "cuenta_fondo_id", "cuenta_destino_id", "referencia", "observacion", "registrado_por_id",
                         "clave_idempotencia")

    numero = models.CharField("número", max_length=20, unique=True, editable=False)
    tipo = models.CharField(max_length=13, choices=Tipo.choices)
    categoria = models.ForeignKey(CategoriaCaja, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="movimientos", verbose_name="categoría")
    fecha = models.DateField()
    concepto = models.CharField(max_length=200)
    monto = models.DecimalField(max_digits=14, decimal_places=2)
    metodo_pago = models.CharField("método de pago", max_length=20, choices=MetodoPago.choices)
    # Ingreso: dónde entra. Egreso y transferencia: de dónde sale.
    cuenta_fondo = models.ForeignKey(CuentaFondo, on_delete=models.PROTECT, related_name="movimientos_caja",
                                     verbose_name="caja o cuenta")
    cuenta_destino = models.ForeignKey(CuentaFondo, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="transferencias_recibidas", verbose_name="caja o cuenta destino")
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
        verbose_name = "movimiento de caja"
        verbose_name_plural = "movimientos de caja"
        indexes = [models.Index(fields=["cuenta_fondo", "fecha"]), models.Index(fields=["fecha"])]
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name="mov_caja_monto_positivo"),
            models.CheckConstraint(
                condition=(Q(tipo__in=["INGRESO", "EGRESO"], categoria__isnull=False, cuenta_destino__isnull=True)
                           | (Q(tipo="TRANSFERENCIA", categoria__isnull=True, cuenta_destino__isnull=False)
                              & ~Q(cuenta_destino=F("cuenta_fondo")))),
                name="mov_caja_tipo_coherente",
            ),
            models.CheckConstraint(
                condition=(Q(estado="CONFIRMADO", anulado_por__isnull=True, anulado_en__isnull=True)
                           | (Q(estado="ANULADO", anulado_por__isnull=False, anulado_en__isnull=False)
                              & ~Q(motivo_anulacion=""))),
                name="mov_caja_anulacion_coherente",
            ),
        ]
        permissions = [("anular_movimientocaja", "Puede anular movimientos de caja y transferencias")]

    def __str__(self):
        return f"{self.numero} · {self.get_tipo_display()} · {self.monto}"

    @property
    def confirmado(self):
        return self.estado == self.Estado.CONFIRMADO

    @property
    def es_transferencia(self):
        return self.tipo == self.Tipo.TRANSFERENCIA

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original = type(self).objects.filter(pk=self.pk).values("estado", *self.CAMPOS_INMUTABLES).first()
            if original is not None:
                if any(original[c] != getattr(self, c) for c in self.CAMPOS_INMUTABLES):
                    raise ValidationError("Un movimiento confirmado no puede modificarse. Anúlelo y registre uno nuevo.")
                if original["estado"] == self.Estado.ANULADO:
                    raise ValidationError("Un movimiento anulado no puede modificarse.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los movimientos de caja no se eliminan; se anulan con motivo.")
