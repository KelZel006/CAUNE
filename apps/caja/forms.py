import uuid

from django import forms
from django.utils import timezone

from apps.aportaciones.models import MetodoPago
from apps.core.models import CuentaFondo

from .models import CategoriaCaja, MovimientoCaja

FECHA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class MovimientoCajaForm(forms.Form):
    """El tipo (ingreso, egreso o transferencia) llega fijo desde la página y ajusta los campos."""

    clave_idempotencia = forms.UUIDField(widget=forms.HiddenInput)
    categoria = forms.ModelChoiceField(label="Categoría", queryset=CategoriaCaja.objects.none())
    fecha = forms.DateField(widget=FECHA)
    concepto = forms.CharField(max_length=200)
    monto = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0.01,
                               widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}))
    metodo_pago = forms.ChoiceField(label="Método", choices=MetodoPago.choices)
    cuenta_fondo = forms.ModelChoiceField(label="Caja o cuenta", queryset=CuentaFondo.objects.filter(activa=True))
    cuenta_destino = forms.ModelChoiceField(label="Caja o cuenta destino",
                                            queryset=CuentaFondo.objects.filter(activa=True))
    referencia = forms.CharField(required=False, max_length=100,
                                 help_text="Obligatoria para transferencias, depósitos bancarios y cheques.")
    observacion = forms.CharField(label="Observación", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, tipo, **kwargs):
        super().__init__(*args, **kwargs)
        self.tipo = tipo
        if tipo == MovimientoCaja.Tipo.TRANSFERENCIA:
            del self.fields["categoria"]
            self.fields["cuenta_fondo"].label = "Sale de (origen)"
            self.fields["cuenta_destino"].label = "Entra en (destino)"
        else:
            del self.fields["cuenta_destino"]
            self.fields["categoria"].queryset = CategoriaCaja.objects.filter(activa=True, tipo=tipo)
            self.fields["cuenta_fondo"].label = "Entra en" if tipo == MovimientoCaja.Tipo.INGRESO else "Sale de"
        if not self.is_bound:
            self.initial.setdefault("clave_idempotencia", uuid.uuid4())
            self.initial.setdefault("fecha", timezone.localdate())


class CategoriaCajaForm(forms.ModelForm):
    class Meta:
        model = CategoriaCaja
        fields = ["nombre", "tipo", "afecta_utilidades", "descripcion", "activa"]
        widgets = {"descripcion": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, bloquear_tipo=False, **kwargs):
        super().__init__(*args, **kwargs)
        if bloquear_tipo:
            self.fields["tipo"].disabled = True
            self.fields["tipo"].help_text = "No se cambia porque la categoría ya tiene movimientos."


class MotivoForm(forms.Form):
    motivo = forms.CharField(label="Motivo", min_length=10, widget=forms.Textarea(attrs={"rows": 3}))


class FiltroLibroForm(forms.Form):
    cuenta = forms.ModelChoiceField(label="Caja o cuenta", required=False, queryset=CuentaFondo.objects.all(),
                                    empty_label="Todas (consolidado)")
    desde = forms.DateField(required=False, widget=FECHA)
    hasta = forms.DateField(required=False, widget=FECHA)

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            raise forms.ValidationError("La fecha inicial no puede ser posterior a la final.")
        return datos
