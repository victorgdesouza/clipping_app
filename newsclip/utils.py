# newsclip/utils.py

import re
import hashlib
from pathlib import Path
from collections import Counter
from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError
from django.utils import timezone as dj_timezone
from googlesearch import search
from dateutil import parser as date_parser
from nltk.tokenize import sent_tokenize, word_tokenize
from nltk.corpus import stopwords

from newsclip.models import Article
from newsclip.gpt_utils import gerar_consultas_com_distilgpt

# —————————————————————————————————————————
# 1) Summary extractivo rápido (NLTK)
# —————————————————————————————————————————

# ATENÇÃO: Execute uma única vez:
#   pip install nltk
#   python -m nltk.downloader punkt stopwords

def generate_summary(text: str, num_sentences: int = 3) -> str:
    # 1) quebrou em sentenças
    sentences = sent_tokenize(text, language='portuguese')
    if len(sentences) <= num_sentences:
        return text

    # 2) tokeniza e conta frequência, sem stopwords
    words = word_tokenize(text.lower(), language='portuguese')
    tokens = [w for w in words if w.isalpha()]
    stop = set(stopwords.words('portuguese'))
    freqs = Counter(w for w in tokens if w not in stop)

    # 3) pontua cada sentença
    scores = {}
    for idx, sent in enumerate(sentences):
        sent_tokens = [w for w in word_tokenize(sent.lower()) if w.isalpha()]
        scores[idx] = sum(freqs.get(w, 0) for w in sent_tokens)

    # 4) escolhe as top N
    best_idxs = sorted(scores, key=scores.get, reverse=True)[:num_sentences]
    # 5) ordena de volta e junta
    best_sentences = [sentences[i] for i in sorted(best_idxs)]
    return " ".join(best_sentences)


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

# —————————————————————————————————————————
# 5) Wrapper para gerar consultas via DistilGPT
# —————————————————————————————————————————

def gerar_consultas_com_distilgpt(kws, max_queries=5):
    """
    Gera consultas via DistilGPT e faz cache do resultado por 1h
    usando uma chave MD5 “segura” para o Memcached.
    """
    # 1) cria string “bruta” a partir das keywords
    key_raw = "|".join(kws) + f"|{max_queries}"
    # 2) gera hash MD5 dessa string
    key_hash = hashlib.md5(key_raw.encode("utf-8")).hexdigest()
    cache_key = f"gpt_queries_{key_hash}"

    # 3) tenta ler do cache
    consultas = cache.get(cache_key)
    if consultas:
        return consultas

    # 4) se não tem no cache, geramos de fato
    prompt = (
        f"Você é um buscador de notícias. Gere até {max_queries} consultas Google "
        f"otimizadas para estas palavras-chave: {kws}."
    )
    resp = generator(prompt, max_length=200, num_return_sequences=1)[0]['generated_text']

    # 5) cleanup e limit
    consultas = [linha.strip() for linha in resp.splitlines() if linha.strip()][:max_queries]

    # 6) salva no cache por 1 hora (3600s)
    cache.set(cache_key, consultas, timeout=3600)

    return consultas
