# newsclip/utils.py

import re
import hashlib
from pathlib import Path
from collections import Counter
from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone as dj_timezone
from googlesearch import search
from dateutil import parser as date_parser


from newsclip.models import Article


# —————————————————————————————————————————
# 1) Summary extractivo rápido (NLTK)
# —————————————————————————————————————————

# ATENÇÃO: Execute uma única vez:
#   pip install nltk
#   python -m nltk.downloader punkt stopwords


def generate_summary(text: str, num_sentences: int = 3) -> str:
    # resumo extractivo simples: pega as N primeiras sentenças
    sentences = text.split('.')
    return '.'.join(sentences[:num_sentences]).strip() + '.'

    


# —————————————————————————————————————————
# 2) Busca no Google via GPT + googlesearch
# —————————————————————————————————————————

def buscar_com_google(queries: list[str], num_results: int = 10) -> list[str]:
    urls = []
    for q in queries:
        for url in search(q, num_results=num_results, lang="pt"):
            urls.append(url)
    return urls


# —————————————————————————————————————————
# 3) Classificação de tópico simples
# —————————————————————————————————————————

class SimpleTopicClassifier:
    def __init__(self):
        self.topic_keywords = {
            "Política": ["presidente","governo","ministro","senado","câmara","política"],
            "Economia": ["economia","inflação","juros","pib","comércio","financeiro"],
            "Esportes": ["jogo","time","futebol","campeonato","esportes","olímpico"],
            "Tecnologia": ["tecnologia","startup","inovação","software","hardware","internet"],
            "Cultura": ["cultura","música","filme","arte","literatura","teatro"],
            "Saúde": ["saúde","hospital","vacina","doença","médico","tratamento"],
        }

    def classify(self, text: str) -> str:
        text_low = text.lower()
        scores = {
            topic: sum(text_low.count(kw) for kw in kws)
            for topic, kws in self.topic_keywords.items()
        }
        best, val = max(scores.items(), key=lambda x: x[1])
        return best if val > 0 else "Sem classificação"

_topic_clf = SimpleTopicClassifier()


# —————————————————————————————————————————
# 4) Salvamento de artigos no banco
# —————————————————————————————————————————

def save_article(client, title, url, raw_date, source):
    # converte raw_date em datetime
    dt = None
    if raw_date:
        try:
            parsed = date_parser.parse(raw_date)
            dt = parsed if parsed.tzinfo else dj_timezone.make_aware(
                parsed, dj_timezone.get_current_timezone()
            )
        except Exception:
            dt = None

    try:
        Article.objects.create(
            client=client,
            title=title[:300],
            url=url,
            published_at=dt,
            source=(source or "")[:200],
            summary=generate_summary(title),
            topic=_topic_clf.classify(title),
        )
    except IntegrityError:
        # já existe
        pass

#



