"""
confidence.py — Multi-signal confidence scoring.

Combines 3 signals to compute a final confidence score for each triage decision:
  1. LLM self-reported confidence (from the tool schema field)
  2. Retrieval relevance (RRF score of the top retrieved document)
  3. Citation verification (do cited_sources actually appear in retrieved docs?)

This is used in main.py to decide whether to trigger the self-reflection loop.
"""


# ── Signal weights (must sum to 1.0) ─────────────────────────────────────────
WEIGHT_LLM_CONFIDENCE  = 0.50   # LLM's self-assessment carries most weight
WEIGHT_RETRIEVAL_SCORE = 0.25   # How relevant were the retrieved docs?
WEIGHT_CITATION_MATCH  = 0.25   # Did the LLM actually quote from the docs?

# If final confidence drops below this, trigger self-reflection
REFLECTION_THRESHOLD = 0.55

# If confidence is still below this after reflection, auto-escalate
ESCALATION_THRESHOLD = 0.40


def compute_confidence(
    llm_confidence: float,
    retrieved_docs: list,
    cited_sources: list,
) -> dict:
    """
    Compute a multi-signal confidence score.

    Args:
        llm_confidence:  The 0.0–1.0 confidence field from the LLM's tool call.
        retrieved_docs:  List of doc dicts, each optionally with 'retrieval_score'.
        cited_sources:   List of exact quote strings from the LLM's cited_sources.

    Returns:
        A dict with:
          - 'final': float 0.0–1.0 (the weighted combined score)
          - 'llm': float (raw LLM confidence)
          - 'retrieval': float (normalised retrieval relevance)
          - 'citation': float (fraction of citations verified)
          - 'should_reflect': bool (True if final < REFLECTION_THRESHOLD)
          - 'should_escalate': bool (True if final < ESCALATION_THRESHOLD)
          - 'citations_verified': int
          - 'citations_total': int
    """
    # ── Signal 1: LLM self-reported confidence ───────────────────────────────
    llm_score = float(llm_confidence or 0.5)
    llm_score = max(0.0, min(1.0, llm_score))  # clamp to [0, 1]

    # ── Signal 2: Retrieval relevance ────────────────────────────────────────
    # If retriever.py attached scores, use the top doc's score.
    # RRF scores are typically in range [0.01, 0.05] — normalise to [0, 1].
    retrieval_score = 0.5  # neutral default if no scores attached
    if retrieved_docs:
        top_score = retrieved_docs[0].get("retrieval_score", None)
        if top_score is not None:
            # Typical RRF top score is ~0.032 (60 docs filtered).
            # Normalise: 0.02 → 0.4, 0.03 → 0.7, 0.04+ → ~1.0
            retrieval_score = min(1.0, top_score / 0.035)

    # ── Signal 3: Citation verification ─────────────────────────────────────
    # Check if each cited quote actually appears somewhere in the retrieved docs.
    # Concatenate all doc text for searching.
    corpus_text = " ".join(
        d.get("text", "").lower() for d in retrieved_docs[:5]
    )

    verified = 0
    total = len(cited_sources) if cited_sources else 0

    for quote in (cited_sources or []):
        if not quote or len(quote.strip()) < 5:
            continue
        # Normalise quote for comparison (lowercase, collapse whitespace)
        normalised = " ".join(quote.lower().split())
        if normalised in corpus_text:
            verified += 1

    # Citation score: if no citations provided, penalise slightly (0.4).
    # If all citations verified: 1.0. If none verified: 0.0.
    if total == 0:
        citation_score = 0.4   # mild penalty: LLM didn't cite anything
    elif verified == 0:
        citation_score = 0.1   # strong penalty: cited things not in docs
    else:
        citation_score = verified / total

    # ── Weighted combination ─────────────────────────────────────────────────
    final = (
        WEIGHT_LLM_CONFIDENCE  * llm_score
        + WEIGHT_RETRIEVAL_SCORE * retrieval_score
        + WEIGHT_CITATION_MATCH  * citation_score
    )
    final = round(max(0.0, min(1.0, final)), 3)

    return {
        "final":              final,
        "llm":                round(llm_score, 3),
        "retrieval":          round(retrieval_score, 3),
        "citation":           round(citation_score, 3),
        "should_reflect":     final < REFLECTION_THRESHOLD,
        "should_escalate":    final < ESCALATION_THRESHOLD,
        "citations_verified": verified,
        "citations_total":    total,
    }


if __name__ == "__main__":
    # Quick self-test
    fake_docs = [
        {
            "text": "HackerRank tests remain active indefinitely unless a start and end time are set.",
            "retrieval_score": 0.033,
        }
    ]

    print("Test 1 — High confidence, verified citation:")
    r = compute_confidence(
        llm_confidence=0.95,
        retrieved_docs=fake_docs,
        cited_sources=["tests remain active indefinitely unless a start and end time are set"],
    )
    print(f"  Final: {r['final']} | Reflect: {r['should_reflect']} | Escalate: {r['should_escalate']}")
    assert r["final"] >= 0.75, "Expected high confidence"

    print("Test 2 — Low confidence, no citation:")
    r = compute_confidence(
        llm_confidence=0.35,
        retrieved_docs=fake_docs,
        cited_sources=[],
    )
    print(f"  Final: {r['final']} | Reflect: {r['should_reflect']} | Escalate: {r['should_escalate']}")
    assert r["should_reflect"], "Expected should_reflect=True"

    print("Test 3 — Fabricated citation (not in docs):")
    r = compute_confidence(
        llm_confidence=0.8,
        retrieved_docs=fake_docs,
        cited_sources=["this quote was completely made up and does not exist"],
    )
    print(f"  Final: {r['final']} | Reflect: {r['should_reflect']} | Escalate: {r['should_escalate']}")
    assert r["citation"] == 0.1, "Expected penalty for bad citation"

    print("\nAll confidence tests passed!")
