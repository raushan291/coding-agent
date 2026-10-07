import re
import time

import chromadb
from rank_bm25 import BM25Okapi

from coding_agent.config import config
from coding_agent.llm.factory import get_embedder
from coding_agent.observability.logger import get_logger

logger = get_logger(__name__)


RRF_K = 60
MAX_QUERY_TOKENS = 64

_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_CAMEL_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")

# Built once per process: the index is only written at startup, so it cannot change
# while a session is running.
_bm25_cache: dict[str, dict] = {}


def _tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, plus camelCase subtokens for identifiers."""
    tokens: list[str] = []
    for word in _WORD_RE.findall(text):
        tokens.append(word.lower())
        subs = _CAMEL_RE.findall(word)
        if len(subs) > 1:
            tokens.extend(s.lower() for s in subs)
    return tokens


def _get_collection() -> chromadb.Collection:
    chroma_client = chromadb.PersistentClient(path=config["chromadb"]["persist_dir"])
    return chroma_client.get_or_create_collection(
        name=config["chromadb"]["collection_name"]
    )


def _load_index(collection: chromadb.Collection) -> dict:
    """Tokenize every stored document and build a BM25Okapi over it, once."""
    cache_key = (
        f"{config['chromadb']['persist_dir']}::{config['chromadb']['collection_name']}"
    )
    cached = _bm25_cache.get(cache_key)
    if cached is not None:
        return cached

    started = time.perf_counter()
    data = collection.get(include=["documents", "metadatas"])
    ids = data["ids"]
    docs = data["documents"] or []
    metas = data["metadatas"] or []
    corpus = [_tokenize(doc or "") for doc in docs]

    if docs and any(corpus):
        bm25 = BM25Okapi(corpus)
    else:
        bm25 = None
        logger.warning("BM25 index not built: collection has no tokenizable documents")

    entry = {"bm25": bm25, "ids": ids, "docs": docs, "metas": metas}
    _bm25_cache[cache_key] = entry
    logger.info(
        f"Built BM25 index over {len(docs)} chunks in "
        f"{time.perf_counter() - started:.2f}s"
    )
    return entry


def _dense_leg(
    collection: chromadb.Collection, query_embedding: list[float], n: int
) -> tuple[list[str], list[str], list[dict], list[float]]:
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n,
        include=["documents", "metadatas", "distances"],
    )
    return (
        results["ids"][0],
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    )


def _keyword_leg(
    entry: dict, query: str, n: int
) -> tuple[list[str], list[str], list[dict]]:
    """Rank the stored corpus with BM25 for this query."""
    if entry["bm25"] is None:
        return [], [], []

    query_tokens = _tokenize(query)[:MAX_QUERY_TOKENS]
    if not query_tokens:
        logger.debug("Keyword leg skipped: query produced no tokens")
        return [], [], []

    scores = entry["bm25"].get_scores(query_tokens)
    order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
    hits = [i for i in order if scores[i] > 0][:n]

    return (
        [entry["ids"][i] for i in hits],
        [entry["docs"][i] for i in hits],
        [entry["metas"][i] for i in hits],
    )


def _rrf(rankings: list[list[str]]) -> list[str]:
    """Reciprocal Rank Fusion over ranked id lists, best first."""
    scores: dict[str, float] = {}
    for ranked in rankings:
        for rank, doc_id in enumerate(ranked, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (RRF_K + rank)
    return [
        doc_id for doc_id, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def _fetch_distances(
    collection: chromadb.Collection, query_embedding: list[float], doc_ids: list[str]
) -> dict[str, float]:
    """Look up dense distances for chunks that only the keyword leg surfaced."""
    if not doc_ids:
        return {}
    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=len(doc_ids),
            include=["distances"],
            ids=doc_ids,
        )
        return dict(zip(results["ids"][0], results["distances"][0]))
    except Exception as e:
        logger.debug(f"Distance lookup failed for {len(doc_ids)} chunks: {e}")
        return {}


def retrieve(query: str, k: int = 5) -> list[dict]:
    """
    Retrieve top-k chunks using dense, sparse, or hybrid mode — controlled by config.
    Dense is ChromaDB vector search, sparse is BM25 over the stored corpus, hybrid
    fuses both with reciprocal rank fusion.
    """
    mode = config["vector_store"].get("retrieval_mode", "hybrid")
    if mode not in ("dense", "sparse", "hybrid"):
        mode = "hybrid"

    collection = _get_collection()
    logger.info(f"Retrieving top {k} chunks — mode: {mode} — query: {query}")

    embedder = get_embedder()
    query_embedding = embedder.embed_query(query)

    pool = k if mode == "dense" else max(k * 4, 40)

    dense_ids: list[str] = []
    dense_docs: list[str] = []
    dense_metas: list[dict] = []
    dense_dists: list[float] = []
    if mode in ("dense", "hybrid"):
        dense_ids, dense_docs, dense_metas, dense_dists = _dense_leg(
            collection, query_embedding, pool
        )

    keyword_ids: list[str] = []
    keyword_docs: list[str] = []
    keyword_metas: list[dict] = []
    if mode in ("sparse", "hybrid"):
        entry = _load_index(collection)
        keyword_ids, keyword_docs, keyword_metas = _keyword_leg(entry, query, pool)

    if mode == "dense":
        ordered = dense_ids
    elif mode == "sparse":
        ordered = keyword_ids
    else:
        ordered = _rrf([dense_ids, keyword_ids])

    ordered = ordered[:k]

    dense_by_id = {
        doc_id: (doc, meta, dist)
        for doc_id, doc, meta, dist in zip(
            dense_ids, dense_docs, dense_metas, dense_dists
        )
    }
    keyword_by_id = {
        doc_id: (doc, meta)
        for doc_id, doc, meta in zip(keyword_ids, keyword_docs, keyword_metas)
    }

    chunks = []
    needs_distance = []
    for doc_id in ordered:
        if doc_id in dense_by_id:
            doc, meta, dist = dense_by_id[doc_id]
        else:
            doc, meta = keyword_by_id[doc_id]
            dist = None
            needs_distance.append(doc_id)

        meta = meta or {}
        chunks.append(
            {
                "content": doc,
                "source": meta["source"],
                "name": meta["name"],
                "type": meta["type"],
                "start_line": meta["start_line"],
                "end_line": meta["end_line"],
                "distance": dist,
            }
        )

    if needs_distance:
        found = _fetch_distances(collection, query_embedding, needs_distance)
        for doc_id, chunk in zip(ordered, chunks):
            if chunk["distance"] is None and doc_id in found:
                chunk["distance"] = found[doc_id]

    logger.info(f"Retrieved {len(chunks)} chunks")
    return chunks
