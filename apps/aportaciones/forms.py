import uuid

from django import forms
from django.utils import timezone

from apps.afiliados.models import Afiliado
from apps.core.models import CuentaFondo

from .models import MetodoPago, MovimientoAfiliado, TipoMovimiento
from .services import tipo_tiene_movimientos

FECHA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class AfiliadoChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.codigo} · {obj.nombre_completo}" + ("" if obj.activo else " (inactivo)")


class MovimientoForm(forms.Form):
    clave_idempotencia = forms.UUIDField(widget=forms.HiddenInput)
    afiliado = AfiliadoChoiceField(queryset=Afiliado.objects.order_by("codigo"))
    tipo = forms.ModelChoiceField(label="Tipo de movimiento", queryset=TipoMovimiento.objects.filter(activo=True))
    fecha = forms.DateField(widget=FECHA)
    monto = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0.01,
                               widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}))
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


class AnulacionForm(forms.Form):
    motivo = forms.CharField(label="Motivo de la anulación", min_length=10, widget=forms.Textarea(attrs={"rows": 3}))
    confirmar = forms.BooleanField(label="Confirmo que esta operación debe anularse; quedará registrada en auditoría.")


class TipoMovimientoForm(forms.ModelForm):
    class Meta:
        model = TipoMovimiento
        fields = ["codigo", "nombre", "clase", "naturaleza", "participa_distribucion", "descripcion", "activo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if tipo_tiene_movimientos(self.instance):
            for campo in ("codigo", "clase", "naturaleza"):
                self.fields[campo].disabled = True
                self.fields[campo].help_text = "Bloqueado: ya existen movimientos de este tipo."

    def clean(self):
        from apps.core import parametros

        datos = super().clean()
        if (datos.get("clase") == TipoMovimiento.Clase.APORTACION
                and datos.get("naturaleza") == TipoMovimiento.Naturaleza.SALIDA
                and not parametros.obtener("movimientos.permitir_retiro_aportaciones")):
            raise forms.ValidationError("La configuración vigente no permite retiros de aportaciones.")
        return datos


class FiltroMovimientosForm(forms.Form):
    desde = forms.DateField(required=False, widget=FECHA)
    hasta = forms.DateField(required=False, widget=FECHA)
    afiliado = AfiliadoChoiceField(required=False, queryset=Afiliado.objects.order_by("codigo"), empty_label="Todos")
    clase = forms.ChoiceField(required=False, choices=[("", "Todas")] + list(TipoMovimiento.Clase.choices))
    tipo = forms.ModelChoiceField(required=False, queryset=TipoMovimiento.objects.all(), empty_label="Todos")
    metodo_pago = forms.ChoiceField(required=False, label="Método",
                                    choices=[("", "Todos")] + list(MetodoPago.choices))
    cuenta_fondo = forms.ModelChoiceField(required=False, label="Caja o cuenta", queryset=CuentaFondo.objects.all(),
                                          empty_label="Todas")
    estado = forms.ChoiceField(required=False, choices=[("", "Todos")] + list(MovimientoAfiliado.Estado.choices))

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            raise forms.ValidationError("La fecha inicial no puede ser posterior a la final.")
        return datos


def aplicar_filtro_movimientos(qs, datos):
    if datos.get("desde"):
        qs = qs.filter(fecha__gte=datos["desde"])
    if datos.get("hasta"):
        qs = qs.filter(fecha__lte=datos["hasta"])
    for campo in ("afiliado", "tipo", "metodo_pago", "cuenta_fondo", "estado"):
        if datos.get(campo):
            qs = qs.filter(**{campo: datos[campo]})
    if datos.get("clase"):
        qs = qs.filter(tipo__clase=datos["clase"])
    return qs
