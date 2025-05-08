import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
_tokenizer = AutoTokenizer.from_pretrained("distilgpt2")
_tokenizer = AutoTokenizer.from_pretrained("distilgpt2")
_model_fp = AutoModelForCausalLM.from_pretrained("distilgpt2")

_model = torch.quantization.quantize_dynamic(
    _model_fp,
    {torch.nn.Linear},
    dtype=torch.qint8
)

# 3) Cria pipeline já com o modelo quantizado
_generator = pipeline(
    "text-generation",
    model=_model,
    tokenizer=_tokenizer,
    device=-1,            # -1 força CPU
    torch_dtype=None,     # ignora dtype pois já foi quantizado
    truncation=True,
)

from django.core.cache import cache

def gerar_consultas_com_distilgpt(keywords: list[str], max_queries: int = 5) -> list[str]:
    cache_key = f"gpt_query_{tuple(keywords)}_{max_queries}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    prompt = (
        f"Você é um buscador de notícias. Gere até {max_queries} consultas Google "
        f"otimizadas para estas palavras-chave: {keywords}."
    )
    out = _generator(
        prompt,
        max_length=150,
        num_return_sequences=1,
        pad_token_id=_tokenizer.eos_token_id,
    )[0]["generated_text"]
    # Extrai as linhas não-vazias
    queries = [l.strip() for l in out.splitlines() if l.strip()]
    cache.set(cache_key, queries, 3600)  # cache 1h
    return queries[:max_queries]