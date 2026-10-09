import uuid

from django import forms
from django.utils import timezone

from apps.aportaciones.models import MetodoPago
from apps.core.models import CuentaFondo

from .models import Actividad, MovimientoActividad, Subactividad

FECHA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class ActividadForm(forms.Form):
    nombre = forms.CharField(max_length=150)
    descripcion = forms.CharField(label="Descripción", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    fecha_inicio = forms.DateField(label="Fecha de inicio", widget=FECHA, initial=timezone.localdate)


class SubactividadForm(forms.Form):
    nombre = forms.CharField(max_length=150)
    descripcion = forms.CharField(label="Descripción", required=False, widget=forms.Textarea(attrs={"rows": 2}))


class MovimientoActividadForm(forms.Form):
    clave_idempotencia = forms.UUIDField(widget=forms.HiddenInput)
    tipo = forms.ChoiceField(choices=MovimientoActividad.Tipo.choices, widget=forms.RadioSelect)
    subactividad = forms.ModelChoiceField(required=False, queryset=Subactividad.objects.none(),
                                          empty_label="General (sin subactividad)")
    fecha = forms.DateField(widget=FECHA)
    concepto = forms.CharField(max_length=200)
    monto = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0.01,
                               widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}))
    metodo_pago = forms.ChoiceField(label="Método de pago", choices=MetodoPago.choices)
    cuenta_fondo = forms.ModelChoiceField(label="Caja o cuenta", queryset=CuentaFondo.objects.filter(activa=True))
    referencia = forms.CharField(required=False, max_length=100,
                                 help_text="Obligatoria para transferencias, depósitos bancarios y cheques.")
    observacion = forms.CharField(label="Observación", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, actividad, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["subactividad"].queryset = actividad.subactividades.filter(activa=True)
        if not self.is_bound:
            self.initial.setdefault("clave_idempotencia", uuid.uuid4())
            self.initial.setdefault("fecha", timezone.localdate())


class MotivoForm(forms.Form):
    motivo = forms.CharField(label="Motivo", min_length=10, widget=forms.Textarea(attrs={"rows": 3}))


class FiltroPeriodoForm(forms.Form):
    desde = forms.DateField(required=False, widget=FECHA)
    hasta = forms.DateField(required=False, widget=FECHA)
    actividad = forms.ModelChoiceField(required=False, queryset=Actividad.objects.all(), empty_label="Todas")

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            raise forms.ValidationError("La fecha inicial no puede ser posterior a la final.")
        return datos
