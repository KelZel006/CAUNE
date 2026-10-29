from django import forms
from django.utils import timezone

from apps.afiliados.models import Afiliado
from apps.aportaciones.models import MetodoPago
from apps.core.models import CuentaFondo

from .models import PagoGanancia

FECHA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class DistribucionForm(forms.Form):
    fecha_inicio = forms.DateField(label="Inicio del período", widget=FECHA)
    fecha_fin = forms.DateField(label="Fin del período", widget=FECHA)
    observaciones = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            hoy = timezone.localdate()
            self.initial.setdefault("fecha_inicio", hoy.replace(month=1, day=1))
            self.initial.setdefault("fecha_fin", hoy)

    def clean(self):
        datos = super().clean()
        if datos.get("fecha_inicio") and datos.get("fecha_fin") and datos["fecha_inicio"] > datos["fecha_fin"]:
            raise forms.ValidationError("La fecha inicial no puede ser posterior a la final.")
        return datos


class EntregaForm(forms.Form):
    forma = forms.ChoiceField(label="Forma de entrega", choices=PagoGanancia.Forma.choices, widget=forms.RadioSelect,
                              initial=PagoGanancia.Forma.PAGO)
    fecha = forms.DateField(widget=FECHA, initial=timezone.localdate)
    cuenta_fondo = forms.ModelChoiceField(label="Caja o cuenta", queryset=CuentaFondo.objects.filter(activa=True),
                                          help_text="Pago: de dónde sale el dinero. Capitalización: dónde queda.")
    metodo_pago = forms.ChoiceField(label="Método de pago", choices=MetodoPago.choices, required=False,
                                    help_text="Solo para pagos. En la capitalización no sale dinero.")
    referencia = forms.CharField(required=False, max_length=100,
                                 help_text="Obligatoria para transferencias, depósitos bancarios y cheques.")
    afiliados = forms.ModelMultipleChoiceField(queryset=Afiliado.objects.none(), widget=forms.CheckboxSelectMultiple,
                                               label="Afiliados")

    def __init__(self, *args, pendientes, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["afiliados"].queryset = Afiliado.objects.filter(pk__in=[f["afiliado"].pk for f in pendientes])
        montos = {f["afiliado"].pk: f["total"] for f in pendientes}
        self.fields["afiliados"].label_from_instance = (
            lambda a: f"{a.codigo} · {a.nombre_completo} — L {montos[a.pk]:,.2f}")
        if not self.is_bound:
            self.initial.setdefault("afiliados", list(montos))


class MotivoForm(forms.Form):
    motivo = forms.CharField(label="Motivo", min_length=10, widget=forms.Textarea(attrs={"rows": 3}))


class FiltroGananciasForm(forms.Form):
    desde = forms.DateField(required=False, widget=FECHA, help_text="Vacío: desde siempre.")
    hasta = forms.DateField(required=False, widget=FECHA, help_text="Vacío: hasta hoy.")
    borradores = forms.BooleanField(label="Incluir distribuciones en borrador", required=False)

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            raise forms.ValidationError("La fecha inicial no puede ser posterior a la final.")
        return datos
