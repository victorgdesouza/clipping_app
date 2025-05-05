# newsclip/utils.py
import re
import hashlib
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone as dj_timezone
from django.core.cache import cache
from googlesearch import search
import dateutil.parser
from newsclip.models import Article

# ↓ Imports do HF e GPT4All
from huggingface_hub import hf_hub_download
from gpt4all import GPT4All

# —————————————————————————————————————————
# 1) Carregamento do modelo LOCAL (.gguf) em BASE_DIR/models/
# —————————————————————————————————————————

# 1.1) Cria pasta de cache "models" dentro do seu projeto
MODELS_DIR = Path(settings.BASE_DIR) / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# 1.2) Defina seu repositório e nome exato do arquivo no HF Hub
HF_REPO_ID    = "victorgdesouza/gpt4all-falcon-newbpe-q4_0-gguf"
MODEL_FILENAME = "gpt4all-falcon-newbpe-q4_0.gguf"

# 1.3) Baixa (ou usa cache) - só uma chamada
local_model_path = hf_hub_download(
    repo_id=HF_REPO_ID,
    filename=MODEL_FILENAME,
    cache_dir=str(MODELS_DIR),
    repo_type="model"  # importante para repos de modelo
)

# 1.4) Inicializa o GPT4All com o caminho do arquivo exato
gpt = GPT4All(
    model_name=MODEL_FILENAME,
    model_path=str(local_model_path),
    allow_download=False,
    verbose=False
)


# —————————————————————————————————————————
# 2) Geração de queries otimizadas + busca Google
# —————————————————————————————————————————

def gerar_consultas_com_gpt4all(keywords: list[str], max_queries: int = 5) -> list[str]:
    prompt = (
        f"Você é um buscador de notícias. Gere até {max_queries} consultas Google "
        f"otimizadas para estas palavras-chave: {keywords}. "
        "Inclua termos como site:instagram.com, site:linkedin.com, site:youtube.com "
        "e portais de jornais impressos."
    )
    resp = gpt.generate(prompt)
    queries = [linha.strip() for linha in resp.splitlines() if linha.strip()]
    return queries[:max_queries]

def buscar_com_google(queries: list[str], num_results: int = 20) -> list[str]:
    key = "llm_urls:" + hashlib.md5("|".join(queries).encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return cached

    urls = []
    for q in queries:
        try:
            for url in search(q, num_results=num_results, lang="pt"):
                urls.append(url)
        except Exception:
            continue

    urls = list(dict.fromkeys(urls))
    cache.set(key, urls, timeout=86400)
    return urls


# —————————————————————————————————————————
# 3) Resumo simples e classificação de tópico
# —————————————————————————————————————————

STOPWORDS = {
    "de","a","o","que","e","do","da","em","um","para",
    "é","com","não","uma","os","no","se","na","por","mais",
    "as","dos","como","mas","foi","ao","ele","das","tem",
    "à","seu","sua","ou","ser","quando","muito","há","nos",
    "já","está","eu","também","só","pelo","pela","até"
}

def generate_summary(text: str, num_sentences: int = 3) -> str:
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if len(sentences) <= num_sentences:
        return text

    words = re.findall(r'\w+', text.lower())
    freq = Counter(w for w in words if w not in STOPWORDS)

    scored = [(sum(freq[w] for w in re.findall(r'\w+', s.lower())), s)
              for s in sentences]
    top = sorted(scored, key=lambda x: x[0], reverse=True)[:num_sentences]
    top_sents = {s for _, s in top}
    summary = [s for s in sentences if s in top_sents]
    return " ".join(summary)

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
        scores = {topic: sum(text_low.count(kw) for kw in kws)
                  for topic,kws in self.topic_keywords.items()}
        best,val = max(scores.items(), key=lambda x:x[1])
        return best if val>0 else "Sem classificação"

_topic_clf = SimpleTopicClassifier()


# —————————————————————————————————————————
# 4) Salvamento de artigos no banco
# —————————————————————————————————————————

def save_article(client, title, url, raw_date, source):
    dt = None
    if raw_date:
        try:
            parsed = dateutil.parser.parse(raw_date)
            dt = (parsed if parsed.tzinfo 
                  else dj_timezone.make_aware(parsed, dj_timezone.get_current_timezone()))
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
        pass
