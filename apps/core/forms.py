from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.models import Group

from .models import CuentaFondo, HistorialAuditoria, Parametro, Secuencia
from .roles import permisos_asignables

User = get_user_model()


class ParametroForm(forms.Form):
    motivo = forms.CharField(label="Motivo del cambio", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, parametro, **kwargs):
        super().__init__(*args, **kwargs)
        self.parametro = parametro
        tipo = parametro.tipo
        actual = parametro.valor_tipado()
        if tipo == Parametro.Tipo.BOOLEANO:
            campo = forms.BooleanField(required=False, initial=actual)
        elif tipo == Parametro.Tipo.DECIMAL:
            campo = forms.DecimalField(required=False, initial=actual, decimal_places=6, max_digits=18)
        elif tipo == Parametro.Tipo.ENTERO:
            campo = forms.IntegerField(required=False, initial=actual)
        else:
            campo = forms.CharField(required=False, initial=actual, max_length=500)
        campo.label = parametro.nombre
        campo.help_text = parametro.descripcion
        self.fields = {"valor": campo, **self.fields}
        if parametro.afecta_calculos:
            self.fields["motivo"].required = True
            self.fields["motivo"].help_text = "Obligatorio: este parámetro afecta cálculos o reglas financieras."


class CuentaFondoForm(forms.ModelForm):
    class Meta:
        model = CuentaFondo
        fields = ["tipo", "nombre", "banco", "numero_cuenta", "titular", "activa"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.movimientos_afiliado.exists():
            self.fields["tipo"].disabled = True
            self.fields["tipo"].help_text = "No se puede cambiar: ya tiene movimientos registrados."


class SecuenciaForm(forms.ModelForm):
    class Meta:
        model = Secuencia
        fields = ["descripcion", "relleno", "siguiente"]
        labels = {"relleno": "Cantidad de dígitos", "siguiente": "Siguiente número"}

    def clean_siguiente(self):
        valor = self.cleaned_data["siguiente"]
        actual = Secuencia.objects.get(pk=self.instance.pk).siguiente
        if valor < actual:
            raise forms.ValidationError(f"Solo puede avanzar la numeración (actual: {actual}); "
                                        "retroceder generaría números repetidos.")
        return valor


class UsuarioCrearForm(forms.ModelForm):
    roles = forms.ModelMultipleChoiceField(queryset=Group.objects.order_by("name"), required=False,
                                           widget=forms.CheckboxSelectMultiple)
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput, strip=False,
                                help_text=password_validation.password_validators_help_text_html())
    password2 = forms.CharField(label="Confirmar contraseña", widget=forms.PasswordInput, strip=False)

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email"]

    def clean(self):
        datos = super().clean()
        p1, p2 = datos.get("password1"), datos.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Las contraseñas no coinciden.")
        if p1:
            usuario = User(username=datos.get("username", ""), first_name=datos.get("first_name", ""),
                           last_name=datos.get("last_name", ""), email=datos.get("email", ""))
            try:
                password_validation.validate_password(p1, usuario)
            except forms.ValidationError as error:
                self.add_error("password1", error)
        return datos


class UsuarioEditarForm(forms.ModelForm):
    roles = forms.ModelMultipleChoiceField(queryset=Group.objects.order_by("name"), required=False,
                                           widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "is_active"]
        labels = {"is_active": "Usuario activo"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["roles"].initial = self.instance.groups.all()


class RolForm(forms.ModelForm):
    permissions = forms.ModelMultipleChoiceField(queryset=None, required=False, label="Permisos",
                                                 widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = Group
        fields = ["name", "permissions"]
        labels = {"name": "Nombre del rol"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["permissions"].queryset = permisos_asignables()
        self.fields["permissions"].label_from_instance = lambda p: p.name


class FiltroAuditoriaForm(forms.Form):
    desde = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    hasta = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    accion = forms.ChoiceField(required=False, choices=[("", "Todas")] + list(HistorialAuditoria.Accion.choices))
    usuario = forms.ModelChoiceField(required=False, queryset=User.objects.order_by("username"),
                                     empty_label="Todos")
