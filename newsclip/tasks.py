# newsclip/tasks.py

from django.core.management import call_command

def fetch_news_task(client_id: int):
    """
    Task que o django-q vai enfileirar.
    Apenas dispara o comando de management para buscar notícias.
    """
    call_command("fetch_news", "--client-id", str(client_id))