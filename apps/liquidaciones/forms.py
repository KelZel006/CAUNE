from django import forms

from apps.aportaciones.models import MetodoPago
from apps.core.models import CuentaFondo


class LiquidacionForm(forms.Form):
    motivo = forms.CharField(label="Motivo del retiro", min_length=10, widget=forms.Textarea(attrs={"rows": 3}),
                             help_text="Por ejemplo: «Renuncia voluntaria presentada por escrito el 20/10/2026».")
    descontar_avalados = forms.BooleanField(
        label="Descontar los préstamos de terceros que avala", required=False,
        help_text="Se le resta lo que deben y esos préstamos quedan cancelados. Si no, siguen vigentes.")

    def __init__(self, *args, hay_avalados=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not hay_avalados:
            del self.fields["descontar_avalados"]


class EjecutarForm(forms.Form):
    cuenta_fondo = forms.ModelChoiceField(label="Caja o cuenta de donde sale el dinero",
                                          queryset=CuentaFondo.objects.filter(activa=True))
    metodo_pago = forms.ChoiceField(label="Forma de entrega", choices=MetodoPago.choices)
    referencia = forms.CharField(required=False, max_length=100,
                                 help_text="Obligatoria para transferencias, depósitos bancarios y cheques.")
    confirmar = forms.BooleanField(label="Confirmo la liquidación: el afiliado quedará dado de baja y la operación "
                                         "quedará registrada en auditoría.")


class MotivoForm(forms.Form):
    motivo = forms.CharField(label="Motivo", min_length=10, widget=forms.Textarea(attrs={"rows": 3}))
