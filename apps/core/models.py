from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class PermisosCaune(models.Model):
    """Modelo sin tabla: solo define permisos generales del sistema."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ("ver_dashboard_financiero", "Puede ver indicadores financieros del panel"),
            ("ver_reportes", "Puede consultar y exportar reportes"),
            ("ver_auditoria", "Puede consultar el historial de auditoría"),
            ("gestionar_usuarios", "Puede crear y modificar usuarios"),
            ("gestionar_roles", "Puede crear y modificar roles y sus permisos"),
        ]


class Parametro(models.Model):
    class Tipo(models.TextChoices):
        TEXTO = "TEXTO", "Texto"
        BOOLEANO = "BOOLEANO", "Sí / No"
        DECIMAL = "DECIMAL", "Decimal"
        ENTERO = "ENTERO", "Entero"

    class Grupo(models.TextChoices):
        GENERAL = "GENERAL", "Datos generales de CAUNE"
        OPERACION = "OPERACION", "Reglas de operación"
        PRESTAMOS = "PRESTAMOS", "Préstamos"
        CAJA = "CAJA", "Caja y bancos"
        GANANCIAS = "GANANCIAS", "Distribución de ganancias"

    clave = models.CharField(max_length=80, unique=True)
    nombre = models.CharField(max_length=150)
    valor = models.TextField(blank=True)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.TEXTO)
    grupo = models.CharField(max_length=10, choices=Grupo.choices, default=Grupo.GENERAL)
    descripcion = models.TextField(blank=True)
    afecta_calculos = models.BooleanField(
        default=False, help_text="Si afecta saldos o cálculos, el cambio exige un motivo."
    )
    actualizado_en = models.DateTimeField(auto_now=True)
    actualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["grupo", "nombre"]
        verbose_name = "parámetro"
        verbose_name_plural = "parámetros"

    def __str__(self):
        return self.nombre

    @staticmethod
    def convertir(tipo, valor):
        """Convierte el texto almacenado al tipo declarado. Lanza ValueError si no es válido."""
        valor = "" if valor is None else str(valor).strip()
        if tipo == Parametro.Tipo.BOOLEANO:
            if valor.lower() in {"true", "1", "si", "sí"}:
                return True
            if valor.lower() in {"false", "0", "no", ""}:
                return False
            raise ValueError("Valor booleano inválido.")
        if tipo == Parametro.Tipo.DECIMAL:
            if valor == "":
                return None
            try:
                return Decimal(valor)
            except InvalidOperation as exc:
                raise ValueError("Valor decimal inválido.") from exc
        if tipo == Parametro.Tipo.ENTERO:
            if valor == "":
                return None
            return int(valor)
        return valor

    def valor_tipado(self):
        return self.convertir(self.tipo, self.valor)

    def valor_legible(self):
        v = self.valor_tipado()
        if self.tipo == self.Tipo.BOOLEANO:
            return "Sí" if v else "No"
        return "" if v is None else str(v)


class HistorialParametro(models.Model):
    parametro = models.ForeignKey(Parametro, on_delete=models.PROTECT, related_name="historial")
    valor_anterior = models.TextField(blank=True)
    valor_nuevo = models.TextField(blank=True)
    motivo = models.TextField(blank=True)
    cambiado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    cambiado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-cambiado_en", "-id"]
        verbose_name = "historial de parámetro"
        verbose_name_plural = "historial de parámetros"


class Secuencia(models.Model):
    """Numeración correlativa de operaciones (AF-0001, OP-000001, ...)."""

    prefijo = models.CharField(max_length=10, unique=True)
    descripcion = models.CharField(max_length=120)
    siguiente = models.PositiveIntegerField(default=1)
    relleno = models.PositiveSmallIntegerField(default=6)

    class Meta:
        ordering = ["prefijo"]
        verbose_name = "secuencia de numeración"
        verbose_name_plural = "secuencias de numeración"
        constraints = [
            models.CheckConstraint(condition=models.Q(siguiente__gte=1), name="secuencia_siguiente_positivo"),
            models.CheckConstraint(
                condition=models.Q(relleno__gte=1, relleno__lte=10), name="secuencia_relleno_rango"
            ),
        ]

    def __str__(self):
        return f"{self.prefijo} ({self.descripcion})"

    def formatear(self, numero):
        return f"{self.prefijo}-{numero:0{self.relleno}d}"

    def ejemplo(self):
        """Cómo se verá el próximo número (los préstamos usan 1 o 2 + año + correlativo)."""
        if self.prefijo.startswith("PR") and self.prefijo[2:].isdigit():
            n = f"{self.siguiente:0{self.relleno}d}"
            return f"1{self.prefijo[2:]}{n} (interno) · 2{self.prefijo[2:]}{n} (externo)"
        return self.formatear(self.siguiente)


class CuentaFondo(models.Model):
    """Caja o cuenta bancaria donde entra o sale el dinero."""

    class Tipo(models.TextChoices):
        CAJA = "CAJA", "Caja"
        BANCO = "BANCO", "Cuenta bancaria"

    tipo = models.CharField(max_length=5, choices=Tipo.choices)
    nombre = models.CharField(max_length=100, unique=True)
    banco = models.CharField(max_length=100, blank=True)
    numero_cuenta = models.CharField("número de cuenta", max_length=40, blank=True)
    titular = models.CharField(max_length=150, blank=True)
    activa = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["tipo", "nombre"]
        verbose_name = "caja o cuenta bancaria"
        verbose_name_plural = "cajas y cuentas bancarias"
        constraints = [
            models.UniqueConstraint(
                fields=["banco", "numero_cuenta"],
                condition=models.Q(tipo="BANCO"),
                name="cuenta_bancaria_unica",
            ),
        ]

    def __str__(self):
        if self.tipo == self.Tipo.BANCO:
            return f"{self.nombre} ({self.banco} · {self.numero_cuenta})"
        return self.nombre

    def clean(self):
        if self.tipo == self.Tipo.BANCO and (not self.banco or not self.numero_cuenta):
            raise ValidationError("Una cuenta bancaria requiere banco y número de cuenta.")


class AuditoriaQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("El historial de auditoría no puede modificarse.")

    def delete(self):
        raise ValidationError("El historial de auditoría no puede eliminarse.")


class HistorialAuditoria(models.Model):
    class Accion(models.TextChoices):
        CREAR = "CREAR", "Creación"
        MODIFICAR = "MODIFICAR", "Modificación"
        CAMBIO_ESTADO = "CAMBIO_ESTADO", "Cambio de estado"
        ANULAR = "ANULAR", "Anulación"
        CONFIGURAR = "CONFIGURAR", "Cambio de configuración"
        INGRESO = "INGRESO", "Ingreso al sistema"
        INGRESO_FALLIDO = "INGRESO_FALLIDO", "Ingreso fallido"
        SALIDA = "SALIDA", "Salida del sistema"

    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    usuario_nombre = models.CharField(max_length=150, blank=True)
    accion = models.CharField(max_length=20, choices=Accion.choices, db_index=True)
    entidad = models.CharField(max_length=80, blank=True, db_index=True)
    entidad_id = models.CharField(max_length=40, blank=True)
    descripcion = models.TextField(blank=True)
    datos_antes = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    datos_despues = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    ip = models.GenericIPAddressField(null=True, blank=True)

    objects = AuditoriaQuerySet.as_manager()

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "registro de auditoría"
        verbose_name_plural = "historial de auditoría"
        indexes = [models.Index(fields=["entidad", "entidad_id"])]

    def __str__(self):
        return f"{self.fecha:%d/%m/%Y %H:%M} · {self.usuario_nombre} · {self.get_accion_display()}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("El historial de auditoría no puede modificarse.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("El historial de auditoría no puede eliminarse.")
