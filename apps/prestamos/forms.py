import uuid

from django import forms
from django.utils import timezone

from apps.afiliados.models import Afiliado
from apps.aportaciones.forms import AfiliadoChoiceField
from apps.aportaciones.models import MetodoPago
from apps.core.models import CuentaFondo

from .models import PagoPrestamo, Prestamo

FECHA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
DINERO = dict(max_digits=14, decimal_places=2, min_value=0.01,
              widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}))


class PrestamoForm(forms.Form):
    tipo_prestatario = forms.ChoiceField(label="Tipo de prestatario", choices=Prestamo.Tipo.choices,
                                         widget=forms.RadioSelect, initial=Prestamo.Tipo.INTERNO)
    afiliado = AfiliadoChoiceField(required=False, queryset=Afiliado.objects.filter(estado="ACTIVO").order_by("codigo"),
                                   help_text="Solo para préstamos internos.")
    externo_nombre = forms.CharField(label="Nombre completo del prestatario externo", required=False, max_length=200)
    externo_identidad = forms.CharField(label="Identidad del prestatario externo", required=False, max_length=17)
    externo_telefono = forms.CharField(label="Teléfono del prestatario externo", required=False, max_length=20)
    externo_direccion = forms.CharField(label="Dirección del prestatario externo", required=False, max_length=300)
    afiliado_responsable = AfiliadoChoiceField(
        label="Afiliado responsable", required=False,
        queryset=Afiliado.objects.filter(estado="ACTIVO").order_by("codigo"),
        help_text="Afiliado que responde por la deuda si el prestatario externo no paga.")
    monto_solicitado = forms.DecimalField(label="Monto solicitado", **DINERO)
    monto_aprobado = forms.DecimalField(label="Monto aprobado", **DINERO)
    metodo_amortizacion = forms.ChoiceField(label="Método de amortización", choices=Prestamo.Metodo.choices)
    plazo = forms.IntegerField(label="Plazo (cuotas mensuales)", min_value=1)
    tasa = forms.DecimalField(label="Tasa de interés (% mensual)", required=False, max_digits=7, decimal_places=4,
                              help_text="Déjela vacía para usar la tasa configurada. Una tasa distinta es una "
                                        "excepción y requiere permiso de autorización y motivo.")
    motivo_excepcion = forms.CharField(label="Motivo de la excepción de tasa", required=False,
                                       widget=forms.Textarea(attrs={"rows": 2}))
    fecha_aprobacion = forms.DateField(label="Fecha de aprobación", widget=FECHA)
    fecha_primer_vencimiento = forms.DateField(label="Fecha del primer vencimiento", widget=FECHA)
    observaciones = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, metodos=None, **kwargs):
        super().__init__(*args, **kwargs)
        if metodos:
            self.fields["metodo_amortizacion"].choices = [c for c in Prestamo.Metodo.choices if c[0] in metodos]
        if not self.is_bound:
            self.initial.setdefault("fecha_aprobacion", timezone.localdate())


class DesembolsoForm(forms.Form):
    fecha = forms.DateField(label="Fecha de desembolso", widget=FECHA, initial=timezone.localdate)
    metodo_pago = forms.ChoiceField(label="Forma de entrega", choices=MetodoPago.choices)
    cuenta = forms.ModelChoiceField(label="Caja o cuenta de donde sale el dinero",
                                    queryset=CuentaFondo.objects.filter(activa=True))
    referencia = forms.CharField(required=False, max_length=100,
                                 help_text="Obligatoria para transferencias, depósitos bancarios y cheques.")


class PagoForm(forms.Form):
    clave_idempotencia = forms.UUIDField(widget=forms.HiddenInput)
    tipo = forms.ChoiceField(choices=PagoPrestamo.Tipo.choices, widget=forms.RadioSelect,
                             initial=PagoPrestamo.Tipo.PAGO,
                             help_text="El abono extraordinario va solo a capital y no modifica el cuadro aprobado.")
    fecha = forms.DateField(widget=FECHA)
    monto = forms.DecimalField(**DINERO)
    metodo_pago = forms.ChoiceField(label="Método de pago", choices=MetodoPago.choices)
    cuenta_fondo = forms.ModelChoiceField(label="Caja o cuenta", queryset=CuentaFondo.objects.filter(activa=True))
    referencia = forms.CharField(required=False, max_length=100,
                                 help_text="Obligatoria para transferencias, depósitos bancarios y cheques.")
    observacion = forms.CharField(label="Observación", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.setdefault("clave_idempotencia", uuid.uuid4())
            self.initial.setdefault("fecha", timezone.localdate())


class ResponsableForm(forms.Form):
    afiliado = AfiliadoChoiceField(label="Afiliado responsable",
                                   queryset=Afiliado.objects.filter(estado="ACTIVO").order_by("codigo"))
    motivo = forms.CharField(label="Motivo", min_length=10, widget=forms.Textarea(attrs={"rows": 3}))


class PrestatarioExternoForm(forms.Form):
    nombre_completo = forms.CharField(label="Nombre completo", max_length=200)
    identidad = forms.CharField(label="Número de identidad", max_length=15, help_text="13 dígitos, sin guiones.")
    telefono = forms.CharField(label="Teléfono", max_length=20, required=False)
    direccion = forms.CharField(label="Dirección", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    motivo = forms.CharField(label="Motivo del cambio", min_length=10, widget=forms.Textarea(attrs={"rows": 3}))


class MotivoForm(forms.Form):
    motivo = forms.CharField(label="Motivo", min_length=10, widget=forms.Textarea(attrs={"rows": 3}))
    confirmar = forms.BooleanField(label="Confirmo esta acción; quedará registrada en auditoría.")


class FiltroPrestamosForm(forms.Form):
    estado = forms.ChoiceField(required=False, choices=[("", "Todos")] + list(Prestamo.Estado.choices))
    tipo = forms.ChoiceField(required=False, choices=[("", "Todos")] + list(Prestamo.Tipo.choices))
    desde = forms.DateField(required=False, label="Aprobado desde", widget=FECHA)
    hasta = forms.DateField(required=False, label="Aprobado hasta", widget=FECHA)


class FiltroPagosForm(forms.Form):
    desde = forms.DateField(required=False, widget=FECHA)
    hasta = forms.DateField(required=False, widget=FECHA)
    tipo = forms.ChoiceField(required=False, choices=[("", "Todos")] + list(PagoPrestamo.Tipo.choices))
    estado = forms.ChoiceField(required=False, choices=[("", "Todos")] + list(PagoPrestamo.Estado.choices))
    prestamo = forms.ModelChoiceField(required=False, queryset=Prestamo.objects.exclude(estado="ANULADO"),
                                      empty_label="Todos")
