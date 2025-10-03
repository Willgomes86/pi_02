from django import forms
from apps.utils.forms import SanitizedFormMixin
from .models import Usuario

class UsuarioPerfilForm(SanitizedFormMixin, forms.ModelForm):
    class Meta:
        model = Usuario
        fields = [
            "first_name",
            "last_name",
            "email",
            "genero",
            "telefone",
            "cpf",
            "endereco",
            "empresa",
            "papel",
        ]
        widgets = {
            "genero": forms.Select(attrs={"class": "form-select"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "telefone": forms.TextInput(attrs={"class": "form-control"}),
            "cpf": forms.TextInput(attrs={"class": "form-control"}),
            "endereco": forms.TextInput(attrs={"class": "form-control"}),
            "empresa": forms.TextInput(attrs={"class": "form-control"}),
            "papel": forms.Select(attrs={"class": "form-select"}),
        }
