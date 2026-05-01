"""
retriever.py — Hybrid BM25 + dense embeddings + RRF retrieval
"""
import os
import pickle
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CACHE_PATH = "code/.embeddings_cache.pkl"

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def build_index(docs: list):
    """Build BM25 index and dense embeddings for all docs."""
    tokenized = [doc["text"].lower().split() for doc in docs]
    bm25 = BM25Okapi(tokenized)

    if os.path.exists(CACHE_PATH):
        print("  Loading embeddings from cache...")
        with open(CACHE_PATH, "rb") as f:
            embeddings = pickle.load(f)
        if len(embeddings) != len(docs):
            print("  Cache mismatch — rebuilding...")
            embeddings = _build_and_cache(docs)
    else:
        embeddings = _build_and_cache(docs)

    return bm25, embeddings


def _build_and_cache(docs: list):
    model = _get_model()
    print(f"  Building embeddings for {len(docs)} docs (~30 seconds)...")
    texts = [doc["text"][:512] for doc in docs]
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=64)
    os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
    with open(CACHE_PATH, "wb") as f:
        pickle.dump(embeddings, f)
    print("  Embeddings cached.")
    return embeddings


def hybrid_retrieve(query, docs, bm25, embeddings,
                    domain_filter=None, top_k=5):
    """Return top_k most relevant docs using hybrid BM25 + dense + RRF."""
    if domain_filter:
        indices = [i for i, d in enumerate(docs) if d["domain"] == domain_filter]
        if not indices:
            indices = list(range(len(docs)))
    else:
        indices = list(range(len(docs)))

    filtered_docs = [docs[i] for i in indices]
    filtered_emb  = embeddings[indices]

    # BM25 sparse scores
    tokenized_query = query.lower().split()
    all_bm25 = bm25.get_scores(tokenized_query)
    bm25_scores = np.array([all_bm25[i] for i in indices])

    # Dense cosine similarity
    model = _get_model()
    q_emb = model.encode([query])[0]
    norms = np.linalg.norm(filtered_emb, axis=1) * np.linalg.norm(q_emb) + 1e-8
    cosine_scores = np.dot(filtered_emb, q_emb) / norms

    # Reciprocal Rank Fusion
    def rrf(scores, k=60):
        ranks = np.argsort(-scores)
        out = np.zeros(len(scores))
        for pos, idx in enumerate(ranks):
            out[idx] = 1.0 / (k + pos + 1)
        return out

    combined = rrf(bm25_scores) + rrf(cosine_scores)
    top_idx = np.argsort(-combined)[:top_k]
    return [filtered_docs[i] for i in top_idx]
