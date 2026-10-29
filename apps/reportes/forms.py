from django import forms
from django.utils import timezone

from apps.actividades.forms import FECHA
from apps.core.models import CuentaFondo
from apps.prestamos.models import Prestamo


def _no_futura(valor, campo="fecha"):
    if valor and valor > timezone.localdate():
        raise forms.ValidationError({campo: "La fecha no puede ser futura."})


class FiltroCorteForm(forms.Form):
    """Balance general e indicadores: una fecha de corte y, opcionalmente, otra para comparar."""
    hasta = forms.DateField(label="Fecha de corte", required=False, widget=FECHA)
    comparar = forms.DateField(label="Comparar con", required=False, widget=FECHA,
                               help_text="Por ejemplo, el 31/12 del año anterior.")

    def clean(self):
        datos = super().clean()
        _no_futura(datos.get("hasta"), "hasta")
        _no_futura(datos.get("comparar"), "comparar")
        return datos


class FiltroEjercicioForm(forms.Form):
    """Estados de un período. Por defecto, el ejercicio en curso (1 de enero a hoy)."""
    desde = forms.DateField(required=False, widget=FECHA)
    hasta = forms.DateField(required=False, widget=FECHA)

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            raise forms.ValidationError("La fecha inicial no puede ser posterior a la final.")
        _no_futura(datos.get("hasta"), "hasta")
        return datos

    def periodo(self):
        hoy = timezone.localdate()
        datos = self.cleaned_data if self.is_valid() else {}
        hasta = datos.get("hasta") or hoy
        desde = datos.get("desde") or hasta.replace(month=1, day=1)
        return desde, hasta


class FiltroResultadosForm(FiltroEjercicioForm):
    comparar = forms.BooleanField(label="Comparar con el mismo período del año anterior", required=False)


class FiltroCajaDiariaForm(FiltroEjercicioForm):
    cuenta = forms.ModelChoiceField(label="Caja o cuenta", required=False, queryset=CuentaFondo.objects.all(),
                                    empty_label="Todas (consolidado)")

    def periodo(self):
        hoy = timezone.localdate()
        datos = self.cleaned_data if self.is_valid() else {}
        hasta = datos.get("hasta") or hoy
        return datos.get("desde") or hasta.replace(day=1), hasta


class FiltroCarteraForm(forms.Form):
    tipo = forms.ChoiceField(label="Tipo de prestatario", required=False,
                             choices=[("", "Todos")] + list(Prestamo.Tipo.choices))
