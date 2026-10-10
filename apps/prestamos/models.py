import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import F, Q

from apps.afiliados.models import Afiliado
from apps.aportaciones.models import MetodoPago, MovimientoAfiliado
from apps.core.models import CuentaFondo

from . import amortizacion

DINERO = dict(max_digits=14, decimal_places=2)


class SinBorrarQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError("Los registros de préstamos no se eliminan; se anulan con motivo.")

    def update(self, **kwargs):
        raise ValidationError("Los registros de préstamos no se modifican de forma masiva.")


class PrestatarioExterno(models.Model):
    nombre_completo = models.CharField("nombre completo", max_length=200)
    identidad = models.CharField(
        "número de identidad", max_length=13, unique=True,
        validators=[RegexValidator(r"^\d{13}$", "La identidad debe tener 13 dígitos.")],
    )
    telefono = models.CharField("teléfono", max_length=20, blank=True)
    direccion = models.TextField("dirección", blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["nombre_completo"]
        verbose_name = "prestatario externo"
        verbose_name_plural = "prestatarios externos"

    def __str__(self):
        return f"{self.nombre_completo} (externo)"


class Prestamo(models.Model):
    class Tipo(models.TextChoices):
        INTERNO = "INTERNO", "Interno (afiliado)"
        EXTERNO = "EXTERNO", "Externo"

    class Metodo(models.TextChoices):
        CUOTA_FIJA = amortizacion.CUOTA_FIJA, "Cuota fija (sistema francés)"
        CAPITAL_FIJO = amortizacion.CAPITAL_FIJO, "Capital fijo (saldo decreciente)"

    class Periodicidad(models.TextChoices):
        MENSUAL = "MENSUAL", "Mensual"

    class Frecuencia(models.TextChoices):
        MENSUAL = "MENSUAL", "Mensual"

    class Estado(models.TextChoices):
        APROBADO = "APROBADO", "Aprobado (por desembolsar)"
        VIGENTE = "VIGENTE", "Vigente"
        PAGADO = "PAGADO", "Cancelado (pagado)"
        ANULADO = "ANULADO", "Anulado"

    numero = models.CharField("número de préstamo", max_length=20, unique=True, editable=False)
    tipo_prestatario = models.CharField("tipo de prestatario", max_length=8, choices=Tipo.choices)
    afiliado = models.ForeignKey(Afiliado, null=True, blank=True, on_delete=models.PROTECT, related_name="prestamos")
    prestatario_externo = models.ForeignKey(PrestatarioExterno, null=True, blank=True, on_delete=models.PROTECT,
                                            related_name="prestamos")
    # Préstamos externos: afiliado que responde por la deuda si el tercero no paga.
    afiliado_responsable = models.ForeignKey(Afiliado, null=True, blank=True, on_delete=models.PROTECT,
                                             related_name="prestamos_respaldados",
                                             verbose_name="afiliado responsable")
    monto_solicitado = models.DecimalField(**DINERO)
    monto_aprobado = models.DecimalField(**DINERO)
    # Condiciones congeladas al aprobar: un cambio posterior en la configuración no las afecta.
    tasa = models.DecimalField("tasa de interés (%)", max_digits=7, decimal_places=4)
    tasa_configurada = models.DecimalField("tasa vigente en la configuración al aprobar (%)", max_digits=7,
                                           decimal_places=4)
    periodicidad_tasa = models.CharField(max_length=8, choices=Periodicidad.choices, default=Periodicidad.MENSUAL)
    tasa_es_excepcion = models.BooleanField(default=False)
    motivo_excepcion = models.TextField(blank=True)
    excepcion_autorizada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                                 on_delete=models.PROTECT, related_name="+")
    # Mora congelada al aprobar: % mensual sobre el capital vencido y no pagado, por cada día de atraso.
    tasa_mora = models.DecimalField("tasa de mora (% mensual)", max_digits=7, decimal_places=4, default=0)
    dias_gracia_mora = models.PositiveSmallIntegerField("días de gracia antes de cobrar mora", default=0)
    dias_maximos_mora = models.PositiveSmallIntegerField(
        "días de atraso tras los cuales la mora se congela", default=90,
        help_text="Pasados estos días desde el vencimiento, la mora de la cuota deja de aumentar. 0 = sin límite.")
    metodo_amortizacion = models.CharField("método de amortización", max_length=12, choices=Metodo.choices)
    plazo = models.PositiveSmallIntegerField("plazo (cuotas)")
    frecuencia_pago = models.CharField(max_length=8, choices=Frecuencia.choices, default=Frecuencia.MENSUAL)
    fecha_aprobacion = models.DateField("fecha de aprobación")
    fecha_primer_vencimiento = models.DateField("fecha del primer vencimiento")
    fecha_desembolso = models.DateField("fecha de desembolso", null=True, blank=True)
    cuenta_desembolso = models.ForeignKey(CuentaFondo, null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="desembolsos", verbose_name="caja o cuenta del desembolso")
    referencia_desembolso = models.CharField(max_length=100, blank=True)
    estado = models.CharField(max_length=8, choices=Estado.choices, default=Estado.APROBADO, db_index=True)
    observaciones = models.TextField(blank=True)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    registrado_en = models.DateTimeField(auto_now_add=True)
    desembolsado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    anulado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    anulado_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.TextField(blank=True)

    objects = SinBorrarQuerySet.as_manager()

    class Meta:
        ordering = ["-fecha_aprobacion", "-id"]
        verbose_name = "préstamo"
        verbose_name_plural = "préstamos"
        indexes = [models.Index(fields=["estado", "fecha_aprobacion"])]
        constraints = [
            models.CheckConstraint(condition=Q(monto_solicitado__gt=0, monto_aprobado__gt=0), name="prestamo_montos_positivos"),
            models.CheckConstraint(condition=Q(monto_aprobado__lte=F("monto_solicitado")), name="prestamo_aprobado_no_excede"),
            models.CheckConstraint(condition=Q(tasa__gte=0, tasa_configurada__gte=0), name="prestamo_tasa_no_negativa"),
            models.CheckConstraint(condition=Q(tasa_mora__gte=0), name="prestamo_tasa_mora_no_negativa"),
            models.CheckConstraint(condition=Q(tipo_prestatario="EXTERNO") | Q(afiliado_responsable__isnull=True),
                                   name="prestamo_responsable_solo_externo"),
            models.CheckConstraint(condition=Q(plazo__gte=1), name="prestamo_plazo_positivo"),
            models.CheckConstraint(
                condition=(Q(tipo_prestatario="INTERNO", afiliado__isnull=False, prestatario_externo__isnull=True)
                           | Q(tipo_prestatario="EXTERNO", afiliado__isnull=True, prestatario_externo__isnull=False)),
                name="prestamo_prestatario_coherente",
            ),
            models.CheckConstraint(
                condition=Q(fecha_desembolso__isnull=True) | Q(cuenta_desembolso__isnull=False),
                name="prestamo_desembolso_con_cuenta",
            ),
        ]
        permissions = [
            ("desembolsar_prestamo", "Puede registrar el desembolso de préstamos"),
            ("anular_prestamo", "Puede anular préstamos no desembolsados"),
            ("autorizar_excepcion_tasa", "Puede autorizar tasas distintas a la configurada"),
        ]

    def __str__(self):
        return f"{self.numero} · {self.prestatario_nombre}"

    @property
    def prestatario_nombre(self):
        if self.tipo_prestatario == self.Tipo.INTERNO and self.afiliado_id:
            return f"{self.afiliado.codigo} · {self.afiliado.nombre_completo}"
        return self.prestatario_externo.nombre_completo if self.prestatario_externo_id else ""

    def delete(self, *args, **kwargs):
        raise ValidationError("Los préstamos no se eliminan; se anulan con motivo.")


class CuotaAmortizacion(models.Model):
    """Fila del cuadro aprobado. Se genera una sola vez y no cambia."""

    prestamo = models.ForeignKey(Prestamo, on_delete=models.PROTECT, related_name="cuotas")
    numero = models.PositiveSmallIntegerField()
    fecha_vencimiento = models.DateField()
    saldo_inicial = models.DecimalField(**DINERO)
    capital = models.DecimalField(**DINERO)
    interes = models.DecimalField(**DINERO)
    cuota = models.DecimalField(**DINERO)
    saldo_final = models.DecimalField(**DINERO)

    objects = SinBorrarQuerySet.as_manager()

    class Meta:
        ordering = ["prestamo", "numero"]
        verbose_name = "cuota de amortización"
        verbose_name_plural = "cuotas de amortización"
        constraints = [
            models.UniqueConstraint(fields=["prestamo", "numero"], name="cuota_numero_unico"),
            models.CheckConstraint(condition=Q(capital__gte=0, interes__gte=0, saldo_final__gte=0), name="cuota_importes_no_negativos"),
            # Tolerancia de medio centavo: SQLite (solo desarrollo) compara decimales como flotantes.
            models.CheckConstraint(
                condition=Q(cuota__gte=F("capital") + F("interes") - Decimal("0.005"),
                            cuota__lte=F("capital") + F("interes") + Decimal("0.005")),
                name="cuota_suma_coherente",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("El cuadro de amortización aprobado no puede modificarse.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("El cuadro de amortización aprobado no puede eliminarse.")


class PagoPrestamo(models.Model):
    class Tipo(models.TextChoices):
        PAGO = "PAGO", "Pago de cuota"
        ABONO_CAPITAL = "ABONO", "Abono extraordinario a capital"

    class Estado(models.TextChoices):
        CONFIRMADO = "CONFIRMADO", "Confirmado"
        ANULADO = "ANULADO", "Anulado"

    CAMPOS_INMUTABLES = ("numero_recibo", "prestamo_id", "tipo", "fecha", "monto", "mora", "excedente", "metodo_pago",
                         "cuenta_fondo_id", "referencia", "observacion", "registrado_por_id", "clave_idempotencia")

    numero_recibo = models.CharField("número de recibo", max_length=20, unique=True, editable=False)
    prestamo = models.ForeignKey(Prestamo, on_delete=models.PROTECT, related_name="pagos")
    tipo = models.CharField(max_length=5, choices=Tipo.choices, default=Tipo.PAGO)
    fecha = models.DateField()
    # monto = lo aplicado al préstamo (mora + intereses + capital). El excedente se acredita como aportación.
    monto = models.DecimalField(**DINERO)
    mora = models.DecimalField("aplicado a mora", **DINERO, default=0)
    excedente = models.DecimalField("pagado de más (a aportaciones)", **DINERO, default=0)
    movimiento_excedente = models.OneToOneField(MovimientoAfiliado, null=True, blank=True, on_delete=models.PROTECT,
                                                related_name="pago_prestamo_origen")
    metodo_pago = models.CharField("método de pago", max_length=20, choices=MetodoPago.choices)
    cuenta_fondo = models.ForeignKey(CuentaFondo, on_delete=models.PROTECT, related_name="pagos_prestamo",
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

    objects = SinBorrarQuerySet.as_manager()

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "pago de préstamo"
        verbose_name_plural = "pagos de préstamos"
        indexes = [models.Index(fields=["prestamo", "estado"]), models.Index(fields=["fecha"])]
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name="pago_prestamo_monto_positivo"),
            models.CheckConstraint(condition=Q(mora__gte=0, excedente__gte=0, mora__lte=F("monto")),
                                   name="pago_prestamo_mora_excedente_validos"),
            models.CheckConstraint(condition=Q(excedente=0, movimiento_excedente__isnull=True)
                                   | Q(excedente__gt=0, movimiento_excedente__isnull=False),
                                   name="pago_prestamo_excedente_coherente"),
            models.CheckConstraint(
                condition=(Q(estado="CONFIRMADO", anulado_por__isnull=True, anulado_en__isnull=True)
                           | (Q(estado="ANULADO", anulado_por__isnull=False, anulado_en__isnull=False)
                              & ~Q(motivo_anulacion=""))),
                name="pago_prestamo_anulacion_coherente",
            ),
        ]
        permissions = [("anular_pagoprestamo", "Puede anular pagos de préstamos")]

    def __str__(self):
        return f"{self.numero_recibo} · {self.prestamo.numero} · {self.monto}"

    @property
    def confirmado(self):
        return self.estado == self.Estado.CONFIRMADO

    @property
    def total_recibido(self):
        return self.monto + self.excedente

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original = type(self).objects.filter(pk=self.pk).values("estado", *self.CAMPOS_INMUTABLES).first()
            if original is not None:
                if any(original[c] != getattr(self, c) for c in self.CAMPOS_INMUTABLES):
                    raise ValidationError("Un pago confirmado no puede modificarse. Anúlelo y registre uno nuevo.")
                if original["estado"] == self.Estado.ANULADO:
                    raise ValidationError("Un pago anulado no puede modificarse.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los pagos no se eliminan; se anulan con motivo.")


class AplicacionPago(models.Model):
    """Cómo se distribuyó cada pago entre interés y capital de cada cuota."""

    pago = models.ForeignKey(PagoPrestamo, on_delete=models.PROTECT, related_name="aplicaciones")
    cuota = models.ForeignKey(CuotaAmortizacion, on_delete=models.PROTECT, related_name="aplicaciones")
    interes = models.DecimalField(**DINERO, default=0)
    capital = models.DecimalField(**DINERO, default=0)

    objects = SinBorrarQuerySet.as_manager()

    class Meta:
        ordering = ["cuota__numero"]
        verbose_name = "aplicación de pago"
        verbose_name_plural = "aplicaciones de pagos"
        constraints = [
            models.CheckConstraint(condition=Q(interes__gte=0, capital__gte=0), name="aplicacion_no_negativa"),
            models.CheckConstraint(condition=Q(interes__gt=0) | Q(capital__gt=0), name="aplicacion_no_vacia"),
            models.UniqueConstraint(fields=["pago", "cuota"], name="aplicacion_unica_por_cuota"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("La aplicación de un pago no puede modificarse.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("La aplicación de un pago no puede eliminarse.")
