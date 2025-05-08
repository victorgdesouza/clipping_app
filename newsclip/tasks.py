from background_task import background
from django.core.management import call_command

@background(schedule=0, queue='fetch')
def fetch_news_task(client_id):
    """
    Esse job dispara a management command de fetch_news
    (o mesmo que você já tinha) — em background.
    """
    call_command("fetch_news", "--client-id", str(client_id))