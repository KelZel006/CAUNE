from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.actividades.models import Actividad
from apps.afiliados.models import Afiliado
from apps.aportaciones.models import MetodoPago, MovimientoAfiliado
from apps.core.models import CuentaFondo

DINERO = dict(max_digits=14, decimal_places=2)


class Distribucion(models.Model):
    """Cálculo de las ganancias de un período y su reparto entre los afiliados.

    El cálculo se guarda como una fotografía (fondos y líneas). Mientras está CALCULADA puede recalcularse;
    al aprobarla queda fija. Solo se aprueba si la fotografía coincide con un cálculo nuevo.
    """

    class Base(models.TextChoices):
        PROMEDIO_DIARIO = "PROMEDIO_DIARIO", "Saldo promedio diario de aportaciones"
        SALDO_CIERRE = "SALDO_CIERRE", "Saldo de aportaciones al cierre del período"

    class Estado(models.TextChoices):
        CALCULADA = "CALCULADA", "Calculada (borrador)"
        APROBADA = "APROBADA", "Aprobada (por pagar)"
        APLICADA = "APLICADA", "Pagada o capitalizada"
        ANULADA = "ANULADA", "Anulada"

    codigo = models.CharField("código", max_length=20, unique=True, editable=False)
    fecha_inicio = models.DateField("inicio del período")
    fecha_fin = models.DateField("fin del período")
    # Reglas congeladas al calcular: un cambio posterior en la configuración no las afecta.
    base_calculo = models.CharField("base del reparto", max_length=15, choices=Base.choices)
    porcentaje_reserva = models.DecimalField("reserva (%)", max_digits=5, decimal_places=2)
    incluye_inactivos = models.BooleanField("incluye afiliados inactivos", default=False)
    estado = models.CharField(max_length=9, choices=Estado.choices, default=Estado.CALCULADA, db_index=True)
    observaciones = models.TextField(blank=True)
    calculado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    calculado_en = models.DateTimeField()
    aprobado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    aprobado_en = models.DateTimeField(null=True, blank=True)
    anulado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    anulado_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha_fin", "-id"]
        verbose_name = "distribución de ganancias"
        verbose_name_plural = "distribuciones de ganancias"
        constraints = [
            models.CheckConstraint(condition=Q(fecha_fin__gte=F("fecha_inicio")), name="distribucion_periodo_valido"),
            models.CheckConstraint(condition=Q(porcentaje_reserva__gte=0, porcentaje_reserva__lt=100),
                                   name="distribucion_reserva_rango"),
            models.CheckConstraint(
                condition=(~Q(estado="ANULADA") & Q(anulado_por__isnull=True))
                | (Q(estado="ANULADA", anulado_por__isnull=False, anulado_en__isnull=False) & ~Q(motivo_anulacion="")),
                name="distribucion_anulacion_coherente",
            ),
            models.CheckConstraint(
                condition=Q(estado__in=["CALCULADA", "ANULADA"]) | Q(aprobado_por__isnull=False),
                name="distribucion_aprobada_con_usuario",
            ),
        ]
        permissions = [
            ("aprobar_distribucion", "Puede aprobar distribuciones de ganancias"),
            ("aplicar_distribucion", "Puede pagar o capitalizar ganancias distribuidas"),
            ("anular_distribucion", "Puede anular distribuciones de ganancias no pagadas"),
        ]

    def __str__(self):
        return f"{self.codigo} · {self.fecha_inicio:%d/%m/%Y} al {self.fecha_fin:%d/%m/%Y}"

    @property
    def editable(self):
        return self.estado == self.Estado.CALCULADA

    def delete(self, *args, **kwargs):
        raise ValidationError("Las distribuciones no se eliminan; se anulan con motivo.")


class FondoDistribucion(models.Model):
    """Una bolsa de utilidad: la general (intereses y otros ingresos menos gastos) o la de una actividad."""

    class Tipo(models.TextChoices):
        GENERAL = "GENERAL", "Utilidad general"
        ACTIVIDAD = "ACTIVIDAD", "Actividad económica"

    distribucion = models.ForeignKey(Distribucion, on_delete=models.CASCADE, related_name="fondos")
    tipo = models.CharField(max_length=9, choices=Tipo.choices)
    actividad = models.ForeignKey(Actividad, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    orden = models.PositiveSmallIntegerField(default=0)
    ingresos = models.DecimalField(**DINERO)
    gastos = models.DecimalField(**DINERO)
    resultado = models.DecimalField(**DINERO)
    reserva = models.DecimalField(**DINERO)
    a_distribuir = models.DecimalField(**DINERO)
    participantes = models.PositiveIntegerField(default=0)
    excluidos = models.PositiveIntegerField("afiliados excluidos", default=0)
    detalle = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["distribucion", "orden"]
        verbose_name = "fondo de distribución"
        verbose_name_plural = "fondos de distribución"
        constraints = [
            models.CheckConstraint(
                condition=Q(tipo="GENERAL", actividad__isnull=True) | Q(tipo="ACTIVIDAD", actividad__isnull=False),
                name="fondo_tipo_coherente",
            ),
            models.UniqueConstraint(fields=["distribucion", "actividad"], name="fondo_actividad_unico"),
        ]

    def __str__(self):
        return self.nombre

    @property
    def nombre(self):
        return self.actividad.nombre if self.actividad_id else "Utilidad general"

    @property
    def sin_asignar(self):
        """Lo que no pudo repartirse porque nadie participa en este fondo (queda en CAUNE)."""
        return self.a_distribuir if self.participantes == 0 else 0


class LineaDistribucion(models.Model):
    """Parte de un afiliado en un fondo: monto = a_distribuir × base del afiliado / base total del fondo."""

    fondo = models.ForeignKey(FondoDistribucion, on_delete=models.CASCADE, related_name="lineas")
    afiliado = models.ForeignKey(Afiliado, on_delete=models.PROTECT, related_name="lineas_distribucion")
    base = models.DecimalField("base (saldo de aportaciones)", **DINERO)
    porcentaje = models.DecimalField(max_digits=9, decimal_places=6)
    monto = models.DecimalField(**DINERO)

    class Meta:
        ordering = ["fondo", "afiliado__codigo"]
        verbose_name = "línea de distribución"
        verbose_name_plural = "líneas de distribución"
        constraints = [models.UniqueConstraint(fields=["fondo", "afiliado"], name="linea_afiliado_unica")]


class PagoQuerySet(models.QuerySet):
    def confirmados(self):
        return self.filter(estado=PagoGanancia.Estado.CONFIRMADO)

    def delete(self):
        raise ValidationError("Los pagos de ganancias no se eliminan; se anulan con motivo.")

    def update(self, **kwargs):
        raise ValidationError("Los pagos de ganancias no se modifican de forma masiva.")


class PagoGanancia(models.Model):
    """Entrega de la ganancia de un afiliado: en dinero (sale de caja) o capitalizada (se acredita a su cuenta)."""

    class Forma(models.TextChoices):
        PAGO = "PAGO", "Pago al afiliado"
        CAPITALIZACION = "CAPITALIZACION", "Capitalización (queda en su cuenta)"

    class Estado(models.TextChoices):
        CONFIRMADO = "CONFIRMADO", "Confirmado"
        ANULADO = "ANULADO", "Anulado"

    numero = models.CharField("número", max_length=20, unique=True, editable=False)
    distribucion = models.ForeignKey(Distribucion, on_delete=models.PROTECT, related_name="pagos")
    afiliado = models.ForeignKey(Afiliado, on_delete=models.PROTECT, related_name="pagos_ganancia")
    forma = models.CharField(max_length=14, choices=Forma.choices)
    fecha = models.DateField()
    monto = models.DecimalField(**DINERO)
    metodo_pago = models.CharField("método de pago", max_length=20, choices=MetodoPago.choices)
    cuenta_fondo = models.ForeignKey(CuentaFondo, on_delete=models.PROTECT, related_name="pagos_ganancia",
                                     verbose_name="caja o cuenta")
    referencia = models.CharField(max_length=100, blank=True)
    movimiento_afiliado = models.OneToOneField(MovimientoAfiliado, null=True, blank=True, on_delete=models.PROTECT,
                                               related_name="pago_ganancia")
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.CONFIRMADO, db_index=True)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    registrado_en = models.DateTimeField(auto_now_add=True)
    anulado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    anulado_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.TextField(blank=True)

    objects = PagoQuerySet.as_manager()

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "pago de ganancias"
        verbose_name_plural = "pagos de ganancias"
        indexes = [models.Index(fields=["cuenta_fondo", "fecha"])]
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name="pago_ganancia_monto_positivo"),
            # Una ganancia no se entrega dos veces.
            models.UniqueConstraint(fields=["distribucion", "afiliado"], condition=Q(estado="CONFIRMADO"),
                                    name="pago_ganancia_unico_confirmado"),
            models.CheckConstraint(
                condition=Q(forma="PAGO", movimiento_afiliado__isnull=True)
                | Q(forma="CAPITALIZACION", movimiento_afiliado__isnull=False),
                name="pago_ganancia_forma_coherente",
            ),
            models.CheckConstraint(
                condition=(Q(estado="CONFIRMADO", anulado_por__isnull=True, anulado_en__isnull=True)
                           | (Q(estado="ANULADO", anulado_por__isnull=False, anulado_en__isnull=False)
                              & ~Q(motivo_anulacion=""))),
                name="pago_ganancia_anulacion_coherente",
            ),
        ]
        permissions = [("anular_pagoganancia", "Puede anular pagos o capitalizaciones de ganancias")]

    def __str__(self):
        return f"{self.numero} · {self.afiliado.codigo} · {self.monto}"

    @property
    def confirmado(self):
        return self.estado == self.Estado.CONFIRMADO

    def delete(self, *args, **kwargs):
        raise ValidationError("Los pagos de ganancias no se eliminan; se anulan con motivo.")
