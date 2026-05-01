"""
retriever.py — Hybrid BM25 + dense embeddings + RRF retrieval
Each returned doc includes a 'retrieval_score' field (RRF score)
used by confidence.py for multi-signal scoring.
"""
import os
import pickle
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from config import EMBEDDING_MODEL as _EMBEDDING_MODEL, EMBEDDING_CACHE_PATH, EMBEDDING_TEXT_LIMIT, RRF_K

CACHE_PATH = EMBEDDING_CACHE_PATH

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(_EMBEDDING_MODEL)
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
    texts = [doc["text"][:EMBEDDING_TEXT_LIMIT] for doc in docs]
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=64)
    os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
    with open(CACHE_PATH, "wb") as f:
        pickle.dump(embeddings, f)
    print("  Embeddings cached.")
    return embeddings


def hybrid_retrieve(query, docs, bm25, embeddings,
                    domain_filter=None, top_k=5):
    """
    Return top_k most relevant docs using hybrid BM25 + dense + RRF.
    Each returned doc dict includes a 'retrieval_score' (RRF score)
    used downstream by confidence.py.
    """
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
    def rrf(scores, k=RRF_K):
        ranks = np.argsort(-scores)
        out = np.zeros(len(scores))
        for pos, idx in enumerate(ranks):
            out[idx] = 1.0 / (k + pos + 1)
        return out

    combined = rrf(bm25_scores) + rrf(cosine_scores)
    top_idx = np.argsort(-combined)[:top_k]

    # Attach retrieval_score to each returned doc
    results = []
    for i in top_idx:
        doc = dict(filtered_docs[i])          # copy so we don't mutate the original
        doc["retrieval_score"] = float(combined[i])
        results.append(doc)

    return results

