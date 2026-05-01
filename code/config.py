"""
config.py — Centralized configuration for all pipeline parameters.

All tunable constants in one place. This makes it easy to:
  1. Understand the system's behavior at a glance
  2. Tune parameters during experimentation
  3. Explain design choices in the AI judge interview
"""

# ── LLM Configuration ─────────────────────────────────────────────────────────
LLM_MODEL = "llama-3.3-70b-versatile"
LLM_MAX_TOKENS = 1024
LLM_TEMPERATURE = 0          # deterministic: same input → same output
LLM_MAX_RETRIES = 3

# Grounding judge model (separate quota from main model)
GROUNDING_MODEL = "llama-3.1-8b-instant"
GROUNDING_MAX_TOKENS = 100

# ── Retrieval Configuration ───────────────────────────────────────────────────
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_CACHE_PATH = "code/.embeddings_cache.pkl"
EMBEDDING_TEXT_LIMIT = 512    # chars of doc text to embed
RRF_K = 60                   # reciprocal rank fusion constant

# Retrieval limits
RETRIEVAL_TOP_K = 5           # default top-K docs returned
RETRIEVAL_TOP_K_REFLECTION = 7  # top-K for reflection re-retrieval
RETRIEVAL_AGENTIC_TOP_K = 3  # top-K per sub-query in agentic loop

# ── Document Processing ──────────────────────────────────────────────────────
DOC_TEXT_LIMIT_LLM = 3000      # chars of doc text sent to LLM per doc
DOC_TEXT_LIMIT_GROUNDING = 3000  # chars of doc text for grounding check
DOC_HASH_KEY_LIMIT = 200      # chars of issue for hash-based resume key

# ── Confidence Scoring ────────────────────────────────────────────────────────
WEIGHT_LLM_CONFIDENCE = 0.50  # LLM's self-assessment carries most weight
WEIGHT_RETRIEVAL_SCORE = 0.25 # How relevant were the retrieved docs?
WEIGHT_CITATION_MATCH = 0.25  # Did the LLM actually quote from the docs?

REFLECTION_THRESHOLD = 0.45   # Below this → trigger self-reflection
ESCALATION_THRESHOLD = 0.25   # Below this after reflection → auto-escalate

# RRF score normalization factor (typical top RRF score is ~0.032)
RRF_NORMALIZATION = 0.035

# Citation scoring
CITATION_NO_CITE_PENALTY = 0.4   # mild penalty: LLM didn't cite anything
CITATION_BAD_CITE_PENALTY = 0.1  # strong penalty: cited things not in docs
CITATION_TOKEN_OVERLAP_THRESHOLD = 0.7  # min % of tokens to match for fallback

# ── Grounding Check ──────────────────────────────────────────────────────────
GROUNDING_DOCS_LIMIT = 5      # top-N docs to check citations against
GROUNDING_CITATION_MIN_LEN = 5  # min chars for a citation to be verifiable
GROUNDING_CITATION_RATIO = 0.5  # min ratio of verified/total to pass

# ── Agentic Loop ─────────────────────────────────────────────────────────────
AGENTIC_MAX_ITERATIONS = 3    # max tool-call iterations per ticket

# ── Operational ──────────────────────────────────────────────────────────────
INTER_TICKET_DELAY = 0.3      # seconds between API calls
CRASH_SAFE_INTERVAL = 5       # write output every N tickets

# ── Domain Inference ─────────────────────────────────────────────────────────
DOMAIN_MIN_SCORE = 2          # minimum keyword score to infer domain
