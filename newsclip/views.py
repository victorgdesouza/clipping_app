# newsclip/views.py
import os
import json
import pathlib
from .forms import ReportForm
from django.contrib import messages
from django.shortcuts import redirect, get_object_or_404, render
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, FileResponse, Http404
from django.conf import settings
from django import forms
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest, JsonResponse
from django.urls import reverse_lazy
from django.contrib.auth.forms import UserCreationForm
from django.views.generic import CreateView, UpdateView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import JsonResponse
from django.core.management.base import BaseCommand
from django.core.management import call_command

from django.views.decorators.http import require_POST 
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.urls import reverse
from .models import Client, Article
from django.utils.text import slugify

from newsclip.models import Article
from django.utils import timezone
from datetime import timedelta
from newsclip.management.commands.fetch_news import buscar_noticias_para_cliente

# 1) Cadastro de usuário
class SignUpView(CreateView):
    template_name = "signup.html"
    form_class = UserCreationForm
    success_url = reverse_lazy("login")



# 3) Cadastro de clientes
class ClientCreateView(LoginRequiredMixin, CreateView):
    model = Client
    # Remova "users" da lista!
    fields = ["name", "keywords", "domains", "instagram", "x", "youtube"]
    template_name = "newsclip/client_form.html"
    success_url = reverse_lazy("dashboard")

    def form_valid(self, form):
        response = super().form_valid(form)
        # Adiciona automaticamente o usuário logado como responsável
        self.object.users.add(self.request.user)
        return response

class ClientUpdateView(UpdateView):
    model = Client
    # Remova "users" da lista!
    fields = ["name", "keywords", "domains", "instagram", "x", "youtube"]
    template_name = "newsclip/client_form.html"
    success_url = reverse_lazy("dashboard")

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.user not in self.object.users.all():
            self.object.users.add(self.request.user)
        return response

class BuscarTodasNoticiasView(ListView):
    template_name = 'newsclip/todas_noticias.html'
    context_object_name = 'clientes'

    def get(self, request, *args, **kwargs):
        # Busca novas notícias para todos os clientes antes de exibir
        clientes = Client.objects.all()
        for cliente in clientes:
            buscar_noticias_para_cliente(cliente)
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        return Client.objects.all().order_by('name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        clientes = context['clientes']
        clientes_noticias = []
        for cliente in clientes:
            artigos = Article.objects.filter(client=cliente).order_by('-published_at')[:5]  # Só 5!
            total = Article.objects.filter(client=cliente).count()
            clientes_noticias.append({
                'cliente': cliente,
                'noticias': artigos,
                'total': total,
            })
        context['clientes_noticias'] = clientes_noticias
        return context

def noticias_cliente_json(request, pk):
        artigos = Article.objects.filter(client_id=pk).order_by('-published_at')
        dados = []
        for artigo in artigos:
            dados.append({
                "title": artigo.title,
                "source": artigo.source,
                "published_at": artigo.published_at.strftime("%d/%m/%Y %H:%M"),
                "url": artigo.url
            })
        return JsonResponse({"noticias": dados})


@login_required
def dashboard(request):
    clients = Client.objects.all() if request.user.is_superuser else request.user.clients.all()
    return render(request, "newsclip/dashboard.html", {"clients": clients})

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponseForbidden
from django.db.models import Count
from django.db.models.functions import TruncDate

@login_required
def client_news(request, client_id):
    client = get_object_or_404(Client, id=client_id)

    # 1) page_size e ordenação
    page_size   = int(request.GET.get("page_size", 20))
    page_number = request.GET.get("page")
    sort        = request.GET.get("sort", "date-desc")

    qs = Article.objects.filter(client=client, excluded=False)
    if sort == "date-asc":
        qs = qs.order_by("published_at")
    elif sort == "source":
        qs = qs.order_by("source", "-published_at")
    else:
        qs = qs.order_by("-published_at")

    # Aqui entra o processamento do POST!
    if request.method == "POST":
        acao = request.POST.get('acao')
        ids = request.POST.getlist('ids[]')
        if not ids:
            messages.warning(request, "Selecione pelo menos uma notícia.")
            return redirect(request.path)
        if acao == "excluir":
            Article.objects.filter(id__in=ids).update(excluded=True)
        elif acao == "manter":
            Article.objects.filter(id__in=ids).update(excluded=False)
        return redirect(request.path)

    # 2) paginação
    page = Paginator(qs, page_size).get_page(page_number)

    # 3) para os gráficos, precisa do QS completo (sem paginar nem NULLs)
    qs_all = qs.exclude(published_at__isnull=True)

    # artigos por dia
    daily_qs = (
        qs_all
        .annotate(day=TruncDate("published_at"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )
    daily_labels = [d["day"].strftime("%d/%m") for d in daily_qs]
    daily_counts = [d["count"]            for d in daily_qs]

    # top 5 fontes
    top_sources = (
        qs_all
        .values("source")
        .annotate(count=Count("id"))
        .order_by("-count")[:5]
    )
    source_labels = [s["source"] for s in top_sources]
    source_counts = [s["count"]   for s in top_sources]

    # prepara JSON para o template
    context = {
        "client": client,
        "daily_labels_json": json.dumps(daily_labels),
        "daily_counts_json": json.dumps(daily_counts),
        "source_labels_json": json.dumps(source_labels),
        "source_counts_json": json.dumps(source_counts),
        "articles": page,
        "page_size": page_size,
        "sort": sort,
        "selected_source": request.GET.get("source", ""),
        "page_size_options": [10, 20, 50],
        "sources": Article.objects.filter(client=client)
                          .values_list("source", flat=True)
                          .distinct(),
    }
    return render(request, "newsclip/client_news.html", context)

@require_POST
@login_required
def bulk_update_news(request, client_id):
    client = get_object_or_404(Client, id=client_id)

    # recupera ação e lista de IDs
    action = request.POST.get("action")
    ids    = (
        request.POST.getlist("ids[]")
        or request.POST.getlist("selected_articles")
    )

    if action not in ("exclude", "keep") or not ids:
        return JsonResponse({"error": "Parâmetros inválidos"}, status=400)

    # aqui definimos o queryset corretamente
    articles_qs = Article.objects.filter(client=client, id__in=ids)

    # aplica a atualização
    if action == "exclude":
        updated = articles_qs.update(excluded=True)
        verb = "excluídos"
    else:
        updated = articles_qs.update(excluded=False)
        verb = "marcados como mantidos"

    # se veio via AJAX, devolve JSON
    if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
        return JsonResponse({
            "updated": updated,
            "message": f"{updated} artigo(s) {verb}."
        })

    # senão, flash message e redirect normal
    messages.success(request, f"{updated} artigo(s) {verb}.")
    return redirect("client_news", client_id=client_id)

@login_required
def fetch_news_view(request, client_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Método inválido")
    # chama sincronamente o management command
    call_command("fetch_news", "--client-id", str(client_id))

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"status": "ok"})
    return redirect("client_news", client_id=client_id)

@login_required
def client_reports(request, client_id):
    client = get_object_or_404(Client, pk=client_id)
    # checa permissão
    if not (request.user.is_superuser or request.user in client.users.all()):
        return HttpResponseForbidden()

    rep_dir = pathlib.Path(settings.MEDIA_ROOT) / "reports"
    # slug do cliente pra bater com o nome de arquivo
    client_slug = slugify(client.name)

    # lista todos os arquivos que comecem com 'relatorio_{slug}_'
    files = sorted(
        [f.name for f in rep_dir.glob(f"relatorio_{client_slug}_*.*")],
        reverse=True
    )

    form = ReportForm(request.POST or None)
    return render(request, "newsclip/client_reports.html", {
        "client": client,
        "files": files,
        "form": form,
    })

@require_POST
@login_required
def bulk_update_news(request, client_id):
    client = get_object_or_404(Client, id=client_id)

    action = request.POST.get("action")
    ids    = (
        request.POST.getlist("ids[]")
        or request.POST.getlist("selected_articles")
    )

    if action not in ("exclude", "keep") or not ids:
        return JsonResponse({"error": "Parâmetros inválidos"}, status=400)

    # **Aqui** definimos o queryset corretamente
    articles_qs = Article.objects.filter(client=client, id__in=ids)

    if action == "exclude":
        updated = articles_qs.update(excluded=True)
        verb = "excluídos"
    else:
        updated = articles_qs.update(excluded=False)
        verb = "marcados como mantidos"

    # Se for AJAX, devolve JSON
    if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
        return JsonResponse({
            "updated": updated,
            "message": f"{updated} artigo(s) {verb}."
        })

    # Senão, flash message e redireciona
    messages.success(request, f"{updated} artigo(s) {verb}.")
    return redirect("client_news", client_id=client_id)

@require_POST
@login_required
def generate_report_view(request, client_id):
    client = get_object_or_404(Client, id=client_id)
    if not (request.user.is_superuser or request.user in client.users.all()):
        return HttpResponseForbidden()

    if request.method == "POST":
        form = ReportForm(request.POST)
        if form.is_valid():
            days_str   = form.cleaned_data["days"]
            out_format = form.cleaned_data["out_format"]

            # Prepara label para feedback
            if days_str == "all":
                label = "todas as notícias"
            else:
                label = f"últimos {days_str} dias"

            # Chama o comando passando days_str (string) para podermos tratar "all"
            call_command(
                "generate_report",
                client_id=client_id,
                days=days_str,
                format=out_format
            )

            messages.success(
                request,
                f"Relatório de {label} ({out_format.upper()}) agendado com sucesso."
            )
            return redirect("client_reports", client_id=client_id)
        else:
            messages.error(request, "Formulário inválido. Verifique os dados e tente novamente.")
            return redirect("client_reports", client_id=client_id)

    # Se não for POST, apenas redireciona
    return redirect("client_reports", client_id=client_id)



@login_required
def download_report(request, client_id, filename):
    # 1) traga o client pelo seu ID (cid), nunca por user=…
    client = get_object_or_404(Client, pk=client_id)

    # 2) verifique permissão: ou é superuser, ou o usuário está na M2M users
    if not (request.user.is_superuser or request.user in client.users.all()):
        return HttpResponseForbidden()

    # 3) monte o caminho para o media/reports/<filename>
    path = pathlib.Path(settings.MEDIA_ROOT) / "reports" / filename
    if not path.exists():
        raise Http404("Arquivo não encontrado")

    # 4) devolva o PDF/CSV/XLSX
    return FileResponse(open(path, "rb"), as_attachment=True, filename=filename)



