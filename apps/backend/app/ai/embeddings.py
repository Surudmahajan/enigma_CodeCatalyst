"""Provider-agnostic text embeddings for semantic candidate retrieval.

Embeddings are a *retrieval aid*, never proof of compatibility: a semantic
hit still has to pass every deterministic check in the matching engine.

* ``local`` (default): deterministic feature-hashing embeddings over word
  tokens, word bigrams and character trigrams. No network, fully
  reproducible, good at catching shared vocabulary and spelling variants.
* ``openai_compatible``: any HTTP endpoint implementing ``POST /embeddings``
  (configure EMBEDDING_API_URL / EMBEDDING_MODEL / AI_API_KEY).
"""

import hashlib
import logging
import math
import re
from functools import lru_cache

import httpx

from app.core.config import get_settings

logger = logging.getLogger("symbio.ai.embeddings")

LOCAL_MODEL = "symbio-hash-v1"
LOCAL_DIMENSIONS = 512
_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or per that the this to was we with our "
    "tonnes tonne tons ton month monthly year yearly week weekly day daily kg t available required need".split()
)


def _features(text: str) -> list[tuple[str, float]]:
    words = [w for w in _TOKEN.findall(text.lower()) if w not in _STOPWORDS]
    feats: list[tuple[str, float]] = [(f"w:{w}", 1.0) for w in words]
    feats += [(f"b:{a}_{b}", 0.7) for a, b in zip(words, words[1:], strict=False)]
    for w in words:
        padded = f"#{w}#"
        feats += [(f"c:{padded[i:i + 3]}", 0.25) for i in range(len(padded) - 2)]
    return feats


def local_embedding(text: str) -> list[float]:
    vector = [0.0] * LOCAL_DIMENSIONS
    for feature, weight in _features(text):
        digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "little") % LOCAL_DIMENSIONS
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign * weight
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [round(v / norm, 6) for v in vector]


def _remote_embedding(text: str) -> list[float]:
    settings = get_settings()
    response = httpx.post(
        settings.embedding_api_url.rstrip("/") + "/embeddings",
        headers={"Authorization": f"Bearer {settings.ai_api_key}"} if settings.ai_api_key else {},
        json={"model": settings.embedding_model, "input": text},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]


def embedding_model_name() -> str:
    settings = get_settings()
    if settings.embedding_provider == "openai_compatible" and settings.embedding_api_url:
        return settings.embedding_model or "remote"
    return LOCAL_MODEL


@lru_cache(maxsize=4096)
def embed(text: str) -> tuple[float, ...]:
    settings = get_settings()
    if settings.embedding_provider == "openai_compatible" and settings.embedding_api_url:
        try:
            return tuple(_remote_embedding(text))
        except Exception:  # remote failure must not break matching; fall back deterministically
            logger.warning("Remote embedding failed; using local embedding", exc_info=True)
    return tuple(local_embedding(text))


def cosine(a: tuple[float, ...] | list[float] | None, b: tuple[float, ...] | list[float] | None) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return None
    return max(0.0, min(1.0, dot / (na * nb)))


def listing_text(name: str, description: str | None, material_name: str | None, extra: list[str] | None = None) -> str:
    """Text used to embed a listing: its own words plus its canonical material context."""
    parts = [name, description or "", material_name or "", *(extra or [])]
    return " ".join(p for p in parts if p)
