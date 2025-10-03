"""Views relacionadas à autenticação de usuários."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.html import strip_tags
from django.utils.http import url_has_allowed_host_and_scheme


def _resolve_redirect_url(request: HttpRequest, default: str) -> str:
    """Retorna uma URL segura para redirecionamento após o login."""

    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return default


def login_view(request: HttpRequest) -> HttpResponse:
    """Renderiza a página de login e autentica o usuário."""

    dashboard_url = "dashboards:overview"
    if request.user.is_authenticated:
        return redirect(dashboard_url)

    if request.method == "POST":
        username = strip_tags(request.POST.get("username", "")).strip()
        password = request.POST.get("password", "")
        usuario = authenticate(request, username=username, password=password)
        if usuario is not None:
            login(request, usuario)
            messages.success(request, "Login realizado com sucesso.")
            return redirect(_resolve_redirect_url(request, dashboard_url))
        messages.error(request, "Usuário ou senha inválidos.")

    context = {"next": request.GET.get("next", "")}
    return render(request, "usuarios/login.html", context)


@login_required
def logout_view(request: HttpRequest) -> HttpResponse:
    """Realiza o logout do usuário autenticado."""

    logout(request)
    messages.success(request, "Sessão encerrada com sucesso.")
    return redirect("usuarios:login")
