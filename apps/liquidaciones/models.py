from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.afiliados.models import Afiliado, CambioEstadoAfiliado
from apps.aportaciones.models import MetodoPago, MovimientoAfiliado
from apps.core.models import CuentaFondo
from apps.distribucion.models import PagoGanancia
from apps.prestamos.models import PagoPrestamo

DINERO = dict(max_digits=14, decimal_places=2)


class Liquidacion(models.Model):
    """Retiro de un afiliado: se le devuelve lo suyo, se cobran sus deudas y se le da de baja.

    Al calcularla se guarda una fotografía de los haberes y las deudas. Al ejecutarla (otra persona) se registran las
    operaciones en cada módulo: pagos de sus préstamos, entrega de ganancias pendientes, devolución de depósitos y de
    aportaciones, y la baja. Nada se borra: una liquidación ejecutada se anula y sus operaciones se anulan con ella.
    """

    class Estado(models.TextChoices):
        CALCULADA = "CALCULADA", "Calculada (por aprobar)"
        EJECUTADA = "EJECUTADA", "Ejecutada (afiliado dado de baja)"
        ANULADA = "ANULADA", "Anulada"

    numero = models.CharField("número", max_length=20, unique=True, editable=False)
    afiliado = models.ForeignKey(Afiliado, on_delete=models.PROTECT, related_name="liquidaciones")
    motivo = models.TextField("motivo del retiro")
    descontar_avalados = models.BooleanField(
        "descontar los préstamos de terceros que avala", default=False,
        help_text="Si se marca, la deuda de los préstamos externos de los que es responsable se le resta y esos "
                  "préstamos quedan cancelados.")
    estado = models.CharField(max_length=9, choices=Estado.choices, default=Estado.CALCULADA, db_index=True)
    # Fotografía del cálculo (al ejecutar se comprueba que no haya cambiado).
    fecha_calculo = models.DateField("calculada al")
    aportaciones = models.DecimalField("saldo de aportaciones", **DINERO)
    depositos = models.DecimalField("saldo de depósitos", **DINERO)
    ganancias = models.DecimalField("ganancias aprobadas por entregar", **DINERO)
    deuda_prestamos = models.DecimalField("deuda de préstamos", **DINERO)
    neto = models.DecimalField("neto a entregar", **DINERO)
    detalle = models.JSONField(default=dict, blank=True)
    calculado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    calculado_en = models.DateTimeField(auto_now_add=True)
    # Ejecución
    fecha = models.DateField("fecha de liquidación", null=True, blank=True)
    cuenta_fondo = models.ForeignKey(CuentaFondo, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                                     verbose_name="caja o cuenta")
    metodo_pago = models.CharField("método de pago", max_length=20, choices=MetodoPago.choices, blank=True)
    referencia = models.CharField(max_length=100, blank=True)
    ejecutado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                      related_name="+")
    ejecutado_en = models.DateTimeField(null=True, blank=True)
    # Operaciones que generó en los demás módulos (para consultarlas y anularlas juntas).
    movimientos = models.ManyToManyField(MovimientoAfiliado, blank=True, related_name="liquidaciones")
    pagos_prestamo = models.ManyToManyField(PagoPrestamo, blank=True, related_name="liquidaciones")
    pagos_ganancia = models.ManyToManyField(PagoGanancia, blank=True, related_name="liquidaciones")
    cambio_estado = models.OneToOneField(CambioEstadoAfiliado, null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="liquidacion")
    anulado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    anulado_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.TextField(blank=True)

    class Meta:
        ordering = ["-calculado_en", "-id"]
        verbose_name = "liquidación de afiliado"
        verbose_name_plural = "liquidaciones de afiliados"
        constraints = [
            models.UniqueConstraint(fields=["afiliado"], condition=Q(estado="CALCULADA"),
                                    name="liquidacion_una_pendiente_por_afiliado"),
            models.CheckConstraint(
                condition=Q(estado="CALCULADA", ejecutado_por__isnull=True)
                | Q(estado="EJECUTADA", ejecutado_por__isnull=False, fecha__isnull=False, cuenta_fondo__isnull=False)
                | (Q(estado="ANULADA", anulado_por__isnull=False, anulado_en__isnull=False) & ~Q(motivo_anulacion="")),
                name="liquidacion_estado_coherente",
            ),
        ]
        permissions = [
            ("ejecutar_liquidacion", "Puede aprobar y ejecutar liquidaciones de afiliados"),
            ("anular_liquidacion", "Puede anular liquidaciones de afiliados"),
        ]

    def __str__(self):
        return f"{self.numero} · {self.afiliado}"

    @property
    def haberes(self):
        return self.aportaciones + self.depositos + self.ganancias

    def delete(self, *args, **kwargs):
        raise ValidationError("Las liquidaciones no se eliminan; se anulan con motivo.")
