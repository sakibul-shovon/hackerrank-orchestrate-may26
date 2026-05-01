# Support Triage Agent

An agentic support triage system that resolves tickets across HackerRank, Claude, and Visa ecosystems using hybrid retrieval, deterministic safety rules, and a self-correcting confidence loop.

## Quick start
```bash
cd code
pip install -r requirements.txt
cp .env.example .env  # add your GROQ_API_KEY (and _2, _3 for rotation)
python main.py --input ../support_tickets/support_tickets.csv \
               --output ../support_tickets/output.csv --verbose
```

## Architecture (9 modules, 7 stages)

```
┌──────────────────────────────────────────────────────────────┐
│  Input Ticket                                                │
│  ┌─────────┐  ┌───────────┐  ┌──────────┐  ┌────────────┐  │
│  │ safety  │→│ domain    │→│ retriever│→│ escalation │  │
│  │ .py     │  │ inference │  │ .py      │  │ rules.py   │  │
│  └────┬────┘  └───────────┘  └──────────┘  └─────┬──────┘  │
│       │                                          │           │
│  ┌────▼──────────────────────────────────────────▼──────┐   │
│  │  agent.py — Agentic Tool Loop (max 2 iterations)     │   │
│  │  ┌─────────────────┐  ┌──────────────────────────┐   │   │
│  │  │ submit_triage   │  │ request_more_documents   │   │   │
│  │  │ (final answer)  │  │ (dynamic re-retrieval)   │   │   │
│  │  └─────────────────┘  └──────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────┘   │
│       │                                                      │
│  ┌────▼────┐  ┌───────────┐  ┌──────────────────────────┐  │
│  │confiden-│→│ grounding │→│ validate + normalize     │  │
│  │ ce.py   │  │ .py       │  │ (product_areas.py)       │  │
│  └─────────┘  └───────────┘  └──────────────────────────┘  │
│                                                              │
│  Output: status | product_area | response | justification   │
│          | request_type                                      │
└──────────────────────────────────────────────────────────────┘
```

1. **`safety.py`** — Pre-LLM regex blocks injection + malicious requests (EN+FR+encoded). Catches threats before any API token is spent.
2. **`domain_inference.py`** — Weighted keyword scoring when `company=None`. Minimum score + tie-break thresholds prevent false routing.
3. **`retriever.py`** — Hybrid BM25 + dense (MiniLM-L6-v2) + RRF fusion. BM25 catches exact terms; dense catches paraphrase.
4. **`escalation_rules.py`** — Deterministic regex for high-risk cases (identity theft, billing, outages). These never reach the LLM.
5. **`agent.py`** — Groq tool-call (llama-3.3-70b-versatile) with **dynamic tool selection**: `submit_triage` or `request_more_documents`. The LLM *chooses* its next action.
6. **`confidence.py`** — Multi-signal scoring: 50% LLM self-assessment + 25% retrieval relevance + 25% citation verification.
7. **`grounding.py`** — Two-layer verification: token-overlap citation check + 8B LLM-as-judge. BOTH must fail to trigger escalation.
8. **`config.py`** — All tunable parameters in one place. Every magic number is documented and justified.
9. **`main.py`** — Orchestrator with self-correction loop + crash-safe incremental writes every 5 tickets.

## Ablation study (sample set, 10 rows)

Run with: `cd code && python eval.py`

| Configuration | Status acc | Type acc | Wall time |
|--------------|-----------|----------|-----------|
| LLM-only (naive) | ~50% | ~70% | ~34s |
| + Hybrid retrieval | ~70% | ~90% | ~52s |
| + Escalation rules | ~80% | ~100% | ~55s |
| + Full (grounding) | ~90% | ~100% | ~60s |

> Each stage adds measurable value. The escalation rules add ~10pp on status accuracy by deterministically catching high-risk tickets the LLM might miss. The grounding check adds 0pp on accuracy but reduces hallucination risk to near zero on security/billing tickets.

## Design decisions

| Decision | Rationale |
|----------|-----------|
| **Groq llama-3.3-70b** | Sub-2s p50 latency, free tier for hackathon. Temperature 0 + enum schema = deterministic. |
| **Hybrid retrieval (BM25 + dense)** | BM25 alone misses paraphrase. Dense alone misses exact product names. |
| **Deterministic escalation rules** | Identity theft, billing, outages must never get a probabilistic answer. |
| **Two-layer grounding** | Single-layer over-escalates paraphrased but correct answers. AND-fail is more conservative. |
| **No vector DB** | 770 docs = in-memory NumPy is millisecond-class. FAISS adds dependency without benefit at this scale. |
| **No LangChain/CrewAI** | Framework abstraction debt not payable in 24h. 7-stage pipeline is a state machine, not a graph. |
| **Dynamic tool selection** | LLM chooses between `submit_triage` and `request_more_documents` — genuine agentic behavior. |
| **Config centralization** | All magic numbers in `config.py` — auditable, tunable, interview-ready. |

## Known limitations

- **Multi-issue tickets**: single status output per row. Detection heuristic exists in prompt but no per-sub-issue routing.
- **Non-English tickets**: corpus is English-only. `langdetect` logs language but agent responds in English regardless.
- **No cross-ticket memory**: each ticket is independent. Duplicate detection would save ~10% latency.
- **No async processing**: serial pipeline. `asyncio.gather` with semaphore could 5× throughput.

## Operational notes

- **Crash-safe**: writes every 5 rows to disk + content-hash resume on restart.
- **API failover**: rotates across up to 5 `GROQ_API_KEY_N` environment variables with exponential backoff.
- **PII redaction**: card numbers, SSNs, CVVs, tokens, emails, API keys redacted before LLM and before log.
- **Reasoning trace**: every ticket decision produces an 8-stage audit trail in `~/hackerrank_orchestrate/log.txt`.
- **Determinism**: `temperature=0`, `DetectorFactory.seed=0`, pinned dependencies.

## Key metrics

- **Latency**: ~3-5s per ticket (dominated by LLM call).
- **Token cost**: ~4-5K tokens per ticket average. 56 tickets ≈ 250K tokens. Free on Groq; $0.04 on Haiku 4.5.
- **Sample accuracy**: 90% status, 100% request_type on 10-row sample set.
