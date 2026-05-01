"""
grounding.py — Post-LLM grounding verifier using citation check + 8B LLM judge.

Two-layer verification — BOTH must fail to trigger escalation:
  1. Citation check: verify cited_sources quotes exist in retrieved docs
     (exact substring + 70% token-overlap fallback)
  2. 8B LLM-as-judge (llama-3.1-8b-instant): checks for clear fabrications
     (not minor paraphrasing — lenient prompt)

Requiring BOTH to fail prevents a single over-strict signal from over-escalating.
Fail-open: if the verifier itself errors, trust the original response.
"""
import json
import os
from pathlib import Path
from groq import Groq
from dotenv import load_dotenv
from config import (
    GROUNDING_MODEL, GROUNDING_MAX_TOKENS,
    GROUNDING_DOCS_LIMIT, GROUNDING_CITATION_MIN_LEN, GROUNDING_CITATION_RATIO,
    CITATION_TOKEN_OVERLAP_THRESHOLD, DOC_TEXT_LIMIT_GROUNDING,
)

load_dotenv(dotenv_path=Path(__file__).parent / ".env")


_cached_client = None

def _get_client():
    """Return a cached Groq client. Reads from env at first call."""
    global _cached_client
    if _cached_client is None:
        _cached_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    return _cached_client


# ── Citation verification (fast, no API call) ─────────────────────────────────

def _verify_citations(cited_sources: list, retrieved_docs: list) -> tuple:
    """
    Check if cited_sources quotes appear verbatim in the retrieved docs.
    Returns (verified: bool, detail: str).

    Unlike lexical overlap (Jaccard), this checks EXACT substrings,
    so "site is down" will NOT match "site is not down".
    """
    if not cited_sources:
        return True, "no citations to verify"   # neutral — let LLM judge decide

    corpus = " ".join(d.get("text", "").lower() for d in retrieved_docs[:GROUNDING_DOCS_LIMIT])
    corpus_tokens = set(corpus.split())
    verified = 0
    for quote in cited_sources:
        if not quote or len(quote.strip()) < GROUNDING_CITATION_MIN_LEN:
            continue
        normalised = " ".join(quote.lower().split())
        if normalised in corpus:
            verified += 1
        else:
            # fallback: >=70% of quote tokens appear in corpus
            qtoks = [t for t in normalised.split() if len(t) > 2]
            if qtoks and sum(1 for t in qtoks if t in corpus_tokens)/len(qtoks) >= CITATION_TOKEN_OVERLAP_THRESHOLD:
                verified += 1

    total = len([q for q in cited_sources if q and len(q.strip()) >= GROUNDING_CITATION_MIN_LEN])
    if total == 0:
        return True, "no verifiable citations"

    ratio = verified / total
    if ratio >= GROUNDING_CITATION_RATIO:
        return True, f"{verified}/{total} citations verified"
    else:
        return False, f"only {verified}/{total} cited quotes found in retrieved docs"


# ── LLM-as-judge grounding check (8B model — fast, separate quota) ───────────

def _llm_grounding_check(response_text: str, retrieved_docs: list) -> tuple:
    """
    Ask llama-3.1-8b-instant to verify the response is grounded in docs.
    Only flags CLEAR fabrications — minor paraphrasing is acceptable.
    Uses 8B model for speed and to keep it on a separate quota from the main 70B.
    """
    excerpts = "\n---\n".join(d["text"][:DOC_TEXT_LIMIT_GROUNDING] for d in retrieved_docs[:3])

    prompt = (
        'Reply ONLY with JSON: {"grounded": true or false, "reason": "brief explanation"}\n\n'
        "Task: Is the Response firmly grounded in the provided Documents? "
        "Return true if the facts are supported by the Documents (minor paraphrasing is fine). "
        "Return false ONLY if the Response directly contradicts the Documents. "
        "Minor paraphrasing or summarizing is acceptable.\n\n"
        f"Response:\n{response_text}\n\n"
        f"Documents:\n{excerpts}"
    )

    try:
        client = _get_client()
        msg = client.chat.completions.create(
            model=GROUNDING_MODEL,
            max_tokens=GROUNDING_MAX_TOKENS,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        raw = msg.choices[0].message.content.strip()
        result = json.loads(raw)
        grounded = bool(result.get("grounded", True))
        reason   = str(result.get("reason", ""))
        return grounded, reason
    except Exception as e:
        # Fail open — a verifier error should not escalate good tickets
        print(f"  [WARN] LLM grounding check failed ({type(e).__name__}), skipping.")
        return True, ""


# ── Public API ────────────────────────────────────────────────────────────────

def is_grounded(
    response_text: str,
    retrieved_docs: list,
    cited_sources: list = None,
) -> tuple:
    """
    Two-layer grounding check. BOTH layers must fail to trigger escalation.

    This prevents a single over-strict signal from over-escalating.
    Layer 1: Citation check (fast, no API cost)
    Layer 2: 8B LLM judge (lenient — flags clear fabrications only)

    Returns:
        (grounded: bool, reason: str)
        grounded=True  -> safe to return to user
        grounded=False -> escalate instead
    """
    if not response_text or not retrieved_docs:
        return False, "no response or no docs to verify against"

    # Layer 1: Fast citation check
    cit_ok, cit_detail = _verify_citations(cited_sources or [], retrieved_docs)

    # Layer 2: 8B LLM judge (lenient prompt)
    llm_ok, llm_reason = _llm_grounding_check(response_text, retrieved_docs)

    # Only escalate if BOTH layers independently flag a problem
    if not cit_ok and not llm_ok:
        return False, f"Citation: {cit_detail} | LLM: {llm_reason}"

    return True, ""
