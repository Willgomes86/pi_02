from __future__ import annotations
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.html import strip_tags
from django.views.decorators.http import require_http_methods

from .forms import UsuarioPerfilForm

def login_view(request: HttpRequest) -> HttpResponse:
    """Renderiza a página de login e autentica o usuário."""

    if request.user.is_authenticated:
        return redirect("usuarios:dashboard")

    if request.method == "POST":
        username = strip_tags(request.POST.get("username", "")).strip()
        password = request.POST.get("password", "")
        usuario = authenticate(request, username=username, password=password)
        if usuario is not None:
            login(request, usuario)
            messages.success(request, "Login realizado com sucesso.")
            return redirect("usuarios:dashboard")
        messages.error(request, "Usuário ou senha inválidos.")

    return render(request, "usuarios/login.html")