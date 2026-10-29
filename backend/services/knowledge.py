# -*- coding: utf-8 -*-
"""检索层：商品混合检索 + 政策库检索。

设计取舍（速通版）：
- 商品数量少，先用 SQLite 做硬条件过滤（类目/价格/有货），再在候选内做 BM25 + 向量；
- 政策文档按标题分块，BM25 与向量 RRF 融合，Rerank 可用时精排；
- 没有 SILICONFLOW_API_KEY 时自动降级为纯 BM25，项目仍可完整演示；
- Chroma 类库延迟导入，未安装向量依赖也不影响关键词检索。
"""
from __future__ import annotations

import logging
import re
import threading
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

import requests

from backend.core.config import Settings, get_settings
from backend.services import catalog

logger = logging.getLogger(__name__)

PRODUCT_COLLECTION = "shop_products"
POLICY_COLLECTION = "shop_policies"

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[一-鿿]+")
_CJK_RE = re.compile(r"^[一-鿿]+$")

_policy_cache: list[dict] | None = None
_policy_lock = threading.Lock()
_index_lock = threading.Lock()


def tokenize(text: str) -> list[str]:
    """英文/数字按词，中文按「单字 + 二元词」，缓解无分词器时的召回问题。"""
    tokens: list[str] = []
    for part in _TOKEN_RE.findall((text or "").lower()):
        if _CJK_RE.match(part):
            tokens.extend(part)
            tokens.extend(part[i : i + 2] for i in range(len(part) - 1))
        else:
            tokens.append(part)
    return tokens


def _rrf(rankings: list[list[str]], k: int = 60) -> list[str]:
    scores: dict[str, float] = OrderedDict()
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda doc_id: scores[doc_id], reverse=True)


def _bm25_ranking(
    query: str, docs: list[dict], text_key: str = "text", min_ratio: float = 0.25
) -> list[str]:
    if not query or not docs:
        return []
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:  # pragma: no cover - 依赖缺失时退化为子串匹配
        q = query.lower()
        return [d["id"] for d in docs if q in d[text_key].lower()]

    corpus = [tokenize(d[text_key]) for d in docs]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(tokenize(query))
    scored = [
        (doc, float(score)) for doc, score in zip(docs, scores, strict=False) if score > 0
    ]
    if not scored:
        return []
    scored.sort(key=lambda item: item[1], reverse=True)
    best = scored[0][1]
    # 只保留与最佳命中相对接近的结果，过滤「手环」这类单字误命中
    return [doc["id"] for doc, score in scored if score >= best * min_ratio]


# ---------------- Embedding / Chroma ----------------

@lru_cache(maxsize=1)
def _embedding_client():
    settings = get_settings()
    if not settings.embed_api_key:
        return None
    from openai import OpenAI

    return OpenAI(
        api_key=settings.embed_api_key,
        base_url=settings.embed_base_url,
        timeout=settings.http_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


def embed_texts(texts: list[str], settings: Settings | None = None) -> list[list[float]]:
    settings = settings or get_settings()
    client = _embedding_client()
    if client is None:
        raise RuntimeError("未配置 SILICONFLOW_API_KEY")
    vectors: list[list[float]] = []
    batch_size = settings.embed_batch_size
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        resp = client.embeddings.create(model=settings.embed_model, input=batch)
        vectors.extend(item.embedding for item in sorted(resp.data, key=lambda d: d.index))
    return vectors


@lru_cache(maxsize=2)
def _chroma_client(path: str):
    import chromadb

    return chromadb.PersistentClient(path=path)


def _get_collection(name: str):
    settings = get_settings()
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    client = _chroma_client(str(settings.chroma_dir))
    return client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})


def invalidate_index_cache() -> None:
    _chroma_client.cache_clear()
    _embedding_client.cache_clear()


def _vector_ranking(name: str, query: str, k: int) -> list[str]:
    if not get_settings().embedding_enabled or not query:
        return []
    try:
        collection = _get_collection(name)
        if collection.count() == 0:
            return []
        vector = embed_texts([query])[0]
        result = collection.query(query_embeddings=[vector], n_results=min(k, collection.count()))
        return list((result.get("ids") or [[]])[0])
    except Exception as exc:
        logger.warning("向量检索失败，降级为 BM25: %s", exc)
        return []


def _rerank(query: str, docs: list[dict], text_key: str, top_n: int) -> list[dict]:
    settings = get_settings()
    if not docs or not settings.embedding_enabled:
        return docs[:top_n]
    try:
        resp = requests.post(
            f"{settings.embed_base_url.rstrip('/')}/rerank",
            headers={"Authorization": f"Bearer {settings.embed_api_key}"},
            json={
                "model": settings.rerank_model,
                "query": query,
                "documents": [d[text_key] for d in docs],
                "top_n": min(top_n, len(docs)),
            },
            timeout=(5, settings.http_timeout_seconds),
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        ordered = [docs[int(item["index"])] for item in results if 0 <= int(item.get("index", -1)) < len(docs)]
        return ordered or docs[:top_n]
    except Exception as exc:
        logger.warning("Rerank 失败，使用融合排序: %s", exc)
        return docs[:top_n]


# ---------------- 商品检索 ----------------

def _product_doc(product: dict) -> dict:
    return {"id": product["id"], "text": catalog.product_text(product), "product": product}


def search_products(
    query: str = "",
    *,
    category: str | None = None,
    max_price: float | None = None,
    min_price: float | None = None,
    in_stock: bool = False,
    top_k: int = 5,
) -> list[dict]:
    """返回 [{product, score}]，按相关度排序；无关键词命中时按销量排序。"""
    candidates = catalog.find_products(
        category=category,
        max_price=max_price,
        min_price=min_price,
        in_stock=in_stock,
    )
    if not candidates:
        return []

    docs = [_product_doc(p) for p in candidates]
    by_id = {doc["id"]: doc for doc in docs}
    if not (query or "").strip():
        return [{"product": doc["product"], "score": 0.0} for doc in docs[:top_k]]

    settings = get_settings()
    lexical = _bm25_ranking(query, docs, min_ratio=0.35)
    vector = [pid for pid in _vector_ranking(PRODUCT_COLLECTION, query, settings.recall_k) if pid in by_id]
    fused = _rrf([ranking for ranking in (vector, lexical) if ranking]) or [d["id"] for d in docs]

    shortlist = [by_id[pid] for pid in fused[: max(settings.recall_k, top_k)]]
    ranked = _rerank(query, shortlist, "text", top_k)
    return [{"product": doc["product"], "score": float(len(ranked) - i)} for i, doc in enumerate(ranked)]


# ---------------- 政策检索 ----------------

def _section_chunks(text: str, source: str, chunk_size: int) -> list[dict]:
    chunks: list[dict] = []
    section = "正文"
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        body = "\n".join(buffer).strip()
        if not body:
            return
        start = 0
        while start < len(body):
            piece = body[start : start + chunk_size].strip()
            if piece:
                chunks.append(
                    {
                        "id": f"{source}::{section}::{len(chunks)}",
                        "source": source,
                        "section": section,
                        "text": f"《{source}》{section}\n{piece}",
                    }
                )
            start += chunk_size

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            flush()
            buffer = []
            section = stripped.lstrip("#").strip() or section
            continue
        if stripped:
            buffer.append(stripped)
    flush()
    return chunks


def load_policy_chunks(force: bool = False) -> list[dict]:
    global _policy_cache
    settings = get_settings()
    with _policy_lock:
        if _policy_cache is not None and not force:
            return _policy_cache
        docs: list[dict] = []
        policy_dir = Path(settings.data_dir) / "policies"
        if policy_dir.is_dir():
            for path in sorted(policy_dir.glob("*.md")):
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                docs.extend(_section_chunks(text, path.name, settings.chunk_size))
        _policy_cache = docs
        return docs


def search_policies(query: str, top_k: int = 3) -> list[dict]:
    docs = load_policy_chunks()
    if not docs:
        return []
    if not (query or "").strip():
        return docs[:top_k]

    settings = get_settings()
    by_id = {doc["id"]: doc for doc in docs}
    lexical = _bm25_ranking(query, docs)
    vector = [pid for pid in _vector_ranking(POLICY_COLLECTION, query, settings.recall_k) if pid in by_id]
    fused = _rrf([ranking for ranking in (vector, lexical) if ranking]) or [d["id"] for d in docs]
    shortlist = [by_id[pid] for pid in fused[: max(settings.recall_k, top_k)]]
    return _rerank(query, shortlist, "text", top_k)


# ---------------- 索引构建 ----------------

def build_index() -> dict:
    """重建商品与政策向量索引。无 Embedding Key 时跳过。"""
    settings = get_settings()
    if not settings.embedding_enabled:
        return {
            "status": "skipped",
            "reason": "未配置 SILICONFLOW_API_KEY，当前仅使用 BM25 关键词检索",
            "products": 0,
            "policies": 0,
        }
    if not _index_lock.acquire(blocking=False):
        return {"status": "busy", "reason": "已有索引任务执行中"}

    try:
        products = catalog.find_products(limit=100)
        product_docs = [
            {
                "id": p["id"],
                "text": catalog.product_text(p),
                "metadata": {"category": p["category"], "price": p["price"]},
            }
            for p in products
        ]
        policies = load_policy_chunks(force=True)
        policy_docs = [
            {
                "id": doc["id"],
                "text": doc["text"],
                "metadata": {"source": doc["source"], "section": doc["section"]},
            }
            for doc in policies
        ]

        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        client = _chroma_client(str(settings.chroma_dir))
        for name, docs in (
            (PRODUCT_COLLECTION, product_docs),
            (POLICY_COLLECTION, policy_docs),
        ):
            try:
                client.delete_collection(name)
            except Exception:
                pass
            if not docs:
                continue
            collection = client.create_collection(name=name, metadata={"hnsw:space": "cosine"})
            collection.upsert(
                ids=[d["id"] for d in docs],
                documents=[d["text"] for d in docs],
                metadatas=[d["metadata"] for d in docs],
                embeddings=embed_texts([d["text"] for d in docs]),
            )
        invalidate_index_cache()
        return {
            "status": "ok",
            "products": len(product_docs),
            "policies": len(policy_docs),
        }
    finally:
        _index_lock.release()


def index_stats() -> dict:
    stats = {"embedding_enabled": get_settings().embedding_enabled}
    for name in (PRODUCT_COLLECTION, POLICY_COLLECTION):
        try:
            stats[name] = _get_collection(name).count()
        except Exception:
            stats[name] = 0
    stats["policy_chunks"] = len(load_policy_chunks())
    return stats
