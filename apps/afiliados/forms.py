import re

from django import forms
from django.utils import timezone

from .models import Afiliado

FECHA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class AfiliadoForm(forms.ModelForm):
    identidad = forms.CharField(label="Número de identidad", max_length=17,
                                help_text="13 dígitos, con o sin guiones (ej. 0801-1990-12345).")

    class Meta:
        model = Afiliado
        fields = ["nombres", "apellidos", "identidad", "telefono", "direccion", "fecha_ingreso"]
        widgets = {"fecha_ingreso": FECHA, "direccion": forms.Textarea(attrs={"rows": 2})}

    def clean_identidad(self):
        valor = re.sub(r"[\s-]", "", self.cleaned_data["identidad"])
        if not re.fullmatch(r"\d{13}", valor):
            raise forms.ValidationError("La identidad debe tener exactamente 13 dígitos.")
        return valor

    def _limpiar_nombre(self, campo):
        valor = " ".join(self.cleaned_data[campo].split())
        if len(valor) < 2:
            raise forms.ValidationError("Escriba al menos 2 caracteres.")
        return valor

    def clean_nombres(self):
        return self._limpiar_nombre("nombres")

    def clean_apellidos(self):
        return self._limpiar_nombre("apellidos")

    def clean_telefono(self):
        valor = self.cleaned_data["telefono"].strip()
        if valor and not re.fullmatch(r"[+\d][\d\s-]{6,18}", valor):
            raise forms.ValidationError("Teléfono inválido.")
        return valor


class CambioEstadoForm(forms.Form):
    fecha_efectiva = forms.DateField(widget=FECHA, initial=timezone.localdate)
    motivo = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), min_length=10)


class FiltroAfiliadosForm(forms.Form):
    estado = forms.ChoiceField(required=False, choices=[("", "Todos")] + list(Afiliado.Estado.choices))
    ingreso_desde = forms.DateField(required=False, label="Ingreso desde", widget=FECHA)
    ingreso_hasta = forms.DateField(required=False, label="Ingreso hasta", widget=FECHA)


class RangoFechasForm(forms.Form):
    desde = forms.DateField(required=False, widget=FECHA)
    hasta = forms.DateField(required=False, widget=FECHA)

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            raise forms.ValidationError("La fecha inicial no puede ser posterior a la final.")
        return datos
