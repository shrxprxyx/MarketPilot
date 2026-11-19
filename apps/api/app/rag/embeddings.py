"""fastembed (ONNX) embeddings, BAAI/bge-small-en-v1.5, 384-d (SRS D-06)."""
import asyncio
from functools import lru_cache

from fastembed import TextEmbedding

MODEL_NAME = "BAAI/bge-small-en-v1.5"


@lru_cache(maxsize=1)
def _model() -> TextEmbedding:
    return TextEmbedding(MODEL_NAME)


def _embed_docs(texts: list[str]) -> list[list[float]]:
    return [[float(x) for x in v] for v in _model().embed(texts)]


def _embed_query(query: str) -> list[float]:
    return [float(x) for x in next(iter(_model().query_embed(query)))]


async def embed_documents(texts: list[str]) -> list[list[float]]:
    return await asyncio.to_thread(_embed_docs, texts)  # CPU-bound: keep the loop free


async def embed_query(query: str) -> list[float]:
    return await asyncio.to_thread(_embed_query, query)
