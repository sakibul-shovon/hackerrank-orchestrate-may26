"""
main.py — Entry point. Agentic triage pipeline with:
  - Smart domain inference (when company=None)
  - Multi-signal confidence scoring
  - Product area normalization
  - Self-reflection loop (Phase 2)

Run:
    python code/main.py                           # default paths
    python code/main.py --verbose                 # print per-ticket details
    python code/main.py --input path --output path
"""
import argparse
import csv
import hashlib
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from corpus            import load_corpus
from safety            import check_safety, detect_language
from retriever         import build_index, hybrid_retrieve
from escalation_rules  import check_escalation_rules
from agent             import call_llm
from grounding         import is_grounded
from domain_inference  import infer_domain
from product_areas     import normalize_product_area
from confidence        import compute_confidence, REFLECTION_THRESHOLD, ESCALATION_THRESHOLD
from reasoning_trace   import create_trace, add_stage, finalize_trace, format_trace_for_log, summarize_traces


# ── Configuration ──────────────────────────────────────────────────────────────

DOMAIN_MAP = {
    "hackerrank": "hackerrank",
    "claude":     "claude",
    "visa":       "visa",
    "none":       None,
    "":           None,
}

OUTPUT_FIELDS = [
    "issue", "subject", "company",
    "status", "product_area", "response", "request_type", "justification"
]

VALID_STATUSES      = {"replied", "escalated"}
VALID_REQUEST_TYPES = {"product_issue", "feature_request", "bug", "invalid"}


# ── Log file ───────────────────────────────────────────────────────────────────

def get_log_path() -> Path:
    log_dir = Path.home() / "hackerrank_orchestrate"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "log.txt"


def _log(path: Path, content: str):
    with open(path, "a", encoding="utf-8") as f:
        f.write(content + "\n")


def log_session_start(path, input_path, output_path):
    ts = datetime.now(timezone.utc).isoformat()
    _log(path, f"""
## [{ts}] SESSION START

Agent: support-triage-agent
Repo: {Path(__file__).parent.parent.resolve()}
Input: {input_path}
Output: {output_path}
""")


def log_ticket(path, idx, ticket, stage, result, lang):
    ts = datetime.now(timezone.utc).isoformat()
    preview = ticket.get("issue", "")[:100].replace("\n", " ")
    _log(path, f"""
## [{ts}] Ticket {idx+1} — {preview}

Input:
  Company : {ticket.get('company','')}
  Subject : {ticket.get('subject','')}
  Issue   : {ticket.get('issue','')}
  Language: {lang}

Decision:
  Stage        : {stage}
  Status       : {result.get('status','?')}
  Product area : {result.get('product_area','?')}
  Request type : {result.get('request_type','?')}
  Justification: {result.get('justification','?')}
""")


def log_session_end(path, total, replied, escalated, duration):
    ts = datetime.now(timezone.utc).isoformat()
    _log(path, f"""
## [{ts}] SESSION END

Total     : {total} tickets in {duration:.1f}s
Replied   : {replied}
Escalated : {escalated}
""")


# ── CSV writer (called every 5 tickets — crash-safe) ──────────────────────────

def write_output(path, tickets, results):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        w.writeheader()
        for t, r in zip(tickets, results):
            w.writerow({
                "issue":         t.get("issue", ""),
                "subject":       t.get("subject", ""),
                "company":       t.get("company", ""),
                "status":        r["status"],
                "product_area":  r["product_area"],
                "response":      r["response"],
                "request_type":  r["request_type"],
                "justification": r["justification"],
            })

    # Also write Title Case version
    titlecase_path = str(path).replace(".csv", "_titlecase.csv")
    titlecase_fields = ["Issue", "Subject", "Company", "Response", "Product Area", "Status", "Request Type", "Justification"]
    with open(titlecase_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=titlecase_fields, extrasaction="ignore")
        w.writeheader()
        for t, r in zip(tickets, results):
            w.writerow({
                "Issue":         t.get("issue", ""),
                "Subject":       t.get("subject", ""),
                "Company":       t.get("company", ""),
                "Status":        r["status"],
                "Product Area":  r["product_area"],
                "Response":      r["response"],
                "Request Type":  r["request_type"],
                "Justification": r["justification"],
            })


# ── Resume support ─────────────────────────────────────────────────────────────

def _hash(ticket):
    key = f"{ticket.get('issue','')[:200]}|{ticket.get('subject','')[:100]}|{ticket.get('company','')}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def load_cache(output_path, tickets):
    cache = {}
    if not os.path.exists(output_path):
        return cache
    try:
        with open(output_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                h = _hash({"issue": row.get("issue",""), "subject": row.get("subject",""), "company": row.get("company","")})
                cache[h] = {k: row.get(k,"") for k in ["status","product_area","response","request_type","justification"]}
        if cache:
            print(f"Resume: {len(cache)} previously processed tickets found.")
    except Exception:
        pass
    return cache


# ── Agentic process_ticket ─────────────────────────────────────────────────────

def process_ticket(ticket, idx, docs, bm25, embeddings, log_path, enable_retrieval=True, enable_rules=True, enable_grounding=True, verbose=False):
    """
    Full agentic triage pipeline:
      Stage 1: Safety filter
      Stage 2: Domain routing + inference
      Stage 3: Hybrid retrieval (BM25 + dense + RRF)
      Stage 4: Deterministic escalation rules
      Stage 5: LLM call (attempt 1)
      Stage 5b: Multi-signal confidence scoring
      Stage 5c: Self-reflection loop (re-retrieve + retry if confidence low)
      Stage 6: Grounding check (citation + 70B LLM judge)
      Stage 7: Validate + normalize product_area
    """
    from redact import redact
    issue   = redact(ticket.get("issue", ""))
    subject = redact(ticket.get("subject", ""))
    company = ticket.get("company", "none").strip().lower()
    
    # Update ticket with redacted versions for downstream logging
    ticket["issue"] = issue
    ticket["subject"] = subject
    
    query   = f"{subject} {issue}".strip()

    # Start reasoning trace
    trace = create_trace(idx + 1, issue, company)

    if verbose:
        print(f"\n  Issue  : {issue[:80]}")
        print(f"  Company: {company}")

    # ── Stage 1: Safety ────────────────────────────────────────────────────────
    if not issue.strip():
        result = {
            "status": "escalated", "product_area": "general",
            "response": "Please provide more details about your issue.",
            "justification": "Empty or whitespace ticket.", "request_type": "invalid",
        }
        finalize_trace(trace, result)
        _append_trace_to_log(log_path, trace)
        log_ticket(log_path, idx, ticket, "safety_filter", result, "en")
        return result

    threat, reason = check_safety(issue)
    lang = detect_language(issue)
    add_stage(trace, "safety", {"passed": not bool(threat), "language": lang, "threat": threat or None})
    if verbose and lang != "en":
        print(f"  Lang   : {lang}")

    if threat:
        if verbose:
            print(f"  [BLOCKED] {threat}: {reason}")
        result = {
            "status": "escalated", "product_area": "security",
            "response": "This request has been flagged for review by our security team.",
            "justification": reason, "request_type": "invalid",
        }
        finalize_trace(trace, result)
        _append_trace_to_log(log_path, trace)
        log_ticket(log_path, idx, ticket, "safety_filter", result, lang)
        return result

    # ── Stage 2: Domain routing + inference ────────────────────────────────────
    domain_filter = DOMAIN_MAP.get(company)
    inferred_domain = None
    domain_source = "company_field"
    if domain_filter is None:
        inferred_domain = infer_domain(issue, subject)
        domain_filter = inferred_domain
        domain_source = "content_inference" if inferred_domain else "none"
        if verbose and inferred_domain:
            print(f"  Domain : {inferred_domain} (inferred from content)")
        elif verbose:
            print(f"  Domain : None (searching all domains)")
    add_stage(trace, "domain", {"detected": domain_filter, "source": domain_source})

    # ── Stage 3: Retrieve ──────────────────────────────────────────────────────
    if enable_retrieval:
        retrieved = hybrid_retrieve(query, docs, bm25, embeddings,
                                    domain_filter=domain_filter, top_k=5)
    else:
        retrieved = []
    top_score = retrieved[0].get("retrieval_score", None) if retrieved else None
    add_stage(trace, "retrieval", {
        "query_preview": query[:60],
        "docs_found":    len(retrieved),
        "top_doc":       retrieved[0]["title"][:40] if retrieved else None,
        "top_score":     round(top_score, 4) if top_score else None,
    })
    if verbose:
        print(f"  Docs   : {[d['title'][:25] for d in retrieved]}")

    # ── Stage 4: Escalation rules (deterministic) ──────────────────────────────
    if enable_rules:
        esc_area, esc_req_type, esc_reason = check_escalation_rules(issue)
        add_stage(trace, "escalation_rules", {"matched": bool(esc_area), "rule": esc_reason})
        if esc_area:
            if verbose:
                print(f"  [RULE]   {esc_reason}")
            result = {
                "status": "escalated", "product_area": esc_area,
                "response": "This case requires attention from a human support agent.",
                "justification": esc_reason, "request_type": esc_req_type,
            }
            finalize_trace(trace, result)
            _append_trace_to_log(log_path, trace)
            log_ticket(log_path, idx, ticket, "escalation_rules", result, lang)
            return result, trace
    else:
        add_stage(trace, "escalation_rules", {"matched": False, "rule": "disabled"})

    # ── Stage 5: LLM call (attempt 1) ─────────────────────────────────────────
    if verbose:
        print(f"  LLM attempt 1...")
    result = call_llm({"issue": issue, "subject": subject, "company": company}, retrieved)
    add_stage(trace, "llm_attempt_1", {
        "model":      "llama-3.3-70b-versatile",
        "status":     result.get("status"),
        "confidence": result.get("confidence"),
    })

    # ── Stage 5b: Multi-signal confidence scoring ─────────────────────────────
    conf = compute_confidence(
        llm_confidence=result.get("confidence", 0.5),
        retrieved_docs=retrieved,
        cited_sources=result.get("cited_sources", []),
    )
    add_stage(trace, "confidence", conf)
    if verbose:
        print(f"  Confidence: {conf['final']} (llm={conf['llm']}, ret={conf['retrieval']}, cit={conf['citation']})")

    # ── Stage 5c: Self-reflection loop ────────────────────────────────────────
    # If confidence is low AND we're about to reply (not already escalating),
    # expand the query using keywords from the LLM response and try again.
    reflected = False
    reflect_reason = "confidence OK"

    if conf["should_reflect"] and result.get("status") == "replied" and result.get("request_type") != "invalid":
        if verbose:
            print(f"  [REFLECT] confidence {conf['final']} < {REFLECTION_THRESHOLD} — re-retrieving...")
        reflected = True
        reflect_reason = f"confidence {conf['final']} below threshold {REFLECTION_THRESHOLD}"

        # Expand query: add keywords from LLM's justification + product_area
        extra_terms = f"{result.get('justification','')} {result.get('product_area','')}"
        expanded_query = f"{query} {extra_terms}".strip()

        retrieved2 = hybrid_retrieve(expanded_query, docs, bm25, embeddings,
                                     domain_filter=domain_filter, top_k=7)
        if verbose:
            print(f"  Re-retrieved {len(retrieved2)} docs with expanded query")

        result2 = call_llm({"issue": issue, "subject": subject, "company": company}, retrieved2)
        conf2 = compute_confidence(
            llm_confidence=result2.get("confidence", 0.5),
            retrieved_docs=retrieved2,
            cited_sources=result2.get("cited_sources", []),
        )
        if verbose:
            print(f"  Attempt 2 confidence: {conf2['final']}")

        add_stage(trace, "llm_attempt_2", {
            "model":           "llama-3.3-70b-versatile",
            "status":          result2.get("status"),
            "confidence":      result2.get("confidence"),
            "final_confidence": conf2["final"],
        })

        # Use attempt 2 if it improved confidence, otherwise keep attempt 1
        if conf2["final"] >= conf["final"]:
            result    = result2
            retrieved = retrieved2
            conf      = conf2
        else:
            if verbose:
                print(f"  Attempt 2 worse — keeping attempt 1")

    add_stage(trace, "reflection", {"triggered": reflected, "reason": reflect_reason})

    # ── Auto-escalate if still low confidence ─────────────────────────────────
    if conf["should_escalate"] and result.get("status") == "replied" and result.get("request_type") != "invalid":
        if verbose:
            print(f"  [AUTO-ESCALATE] final confidence {conf['final']} < {ESCALATION_THRESHOLD}")
        result["status"] = "escalated"
        result["justification"] = (
            f"Auto-escalated: confidence {conf['final']} below threshold after reflection. "
            + result.get("justification", "")
        )

    # ── Stage 6: Grounding check ───────────────────────────────────────────────
    grounding_result = {"skipped": True, "reason": "not a replied+substantive ticket or disabled"}
    if enable_grounding and result.get("status") == "replied" and result.get("request_type") != "invalid":
        grounded, why = is_grounded(
            result.get("response", ""),
            retrieved,
            cited_sources=result.get("cited_sources", []),
        )
        grounding_result = {"grounded": grounded, "detail": why or "ok"}
        if not grounded:
            if verbose:
                print(f"  [UNGROUNDED] {why}")
            result = {
                "status":       "escalated",
                "product_area": result.get("product_area", "general"),
                "response":     "This case requires attention from a human support agent.",
                "justification": f"Response not grounded in corpus: {why}".rstrip(": "),
                "request_type": "product_issue",
            }
    add_stage(trace, "grounding", grounding_result)

    # ── Stage 7: Validate + normalize ─────────────────────────────────────────
    if result.get("status") not in VALID_STATUSES:
        result["status"] = "escalated"
    if result.get("request_type") not in VALID_REQUEST_TYPES:
        result["request_type"] = "product_issue"
    if not result.get("product_area"):
        result["product_area"] = retrieved[0]["product_area"] if retrieved else "general"
    if not result.get("response"):
        result["response"] = "Please contact support for further assistance."
    if not result.get("justification"):
        result["justification"] = "Handled based on retrieved documentation."

    # Normalize product_area to clean label
    raw_area = result["product_area"]
    result["product_area"] = normalize_product_area(
        raw_area, domain=domain_filter or inferred_domain
    )
    if verbose and result["product_area"] != raw_area:
        print(f"  Area   : {raw_area} -> {result['product_area']}")

    if verbose:
        print(f"  -> {result['status'].upper()} | {result['product_area']} | {result['request_type']} (conf={conf['final']})")

    # Finalise trace + write to log
    finalize_trace(trace, {**result, "confidence": conf["final"]})
    _append_trace_to_log(log_path, trace)
    log_ticket(log_path, idx, ticket, "llm_call", result, lang)
    return result, trace


def _append_trace_to_log(log_path: str, trace: dict):
    """Append formatted reasoning trace to log file."""
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n" + format_trace_for_log(trace) + "\n")
    except Exception:
        pass


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Support Triage Agent")
    parser.add_argument("--input",    "-i", default="support_tickets/support_tickets.csv")
    parser.add_argument("--output",   "-o", default="support_tickets/output.csv")
    parser.add_argument("--data-dir",       default="data")
    parser.add_argument("--config",         choices=["naive", "retrieval", "rules", "full"], default="full")
    parser.add_argument("--verbose",  "-v", action="store_true")
    args = parser.parse_args()

    log_path = get_log_path()
    log_session_start(log_path, args.input, args.output)
    print(f"Log : {log_path}")

    print("\nLoading corpus...")
    docs = load_corpus(args.data_dir)
    print(f"Loaded {len(docs)} documents")

    print("Building index...")
    bm25, embeddings = build_index(docs)
    print("Index ready.\n")

    with open(args.input, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # Normalize all headers to lowercase immediately to prevent key errors
        reader.fieldnames = [name.lower().strip() for name in reader.fieldnames]
        tickets = list(reader)
        
    print(f"Processing {len(tickets)} tickets...\n")

    cache = load_cache(args.output, tickets)

    enable_retrieval = args.config in ["retrieval", "rules", "full"]
    enable_rules = args.config in ["rules", "full"]
    enable_grounding = args.config == "full"

    results         = []
    traces          = []
    replied_count   = 0
    escalated_count = 0
    start           = time.time()

    for i, ticket in enumerate(tickets):
        print(f"Ticket {i+1}/{len(tickets)}...", end=" ", flush=True)
        h = _hash(ticket)
        if h in cache:
            result = cache[h]
            results.append(result)
            print("CACHED")
        else:
            ret = process_ticket(ticket, i, docs, bm25, embeddings,
                                 log_path, enable_retrieval=enable_retrieval,
                                 enable_rules=enable_rules, enable_grounding=enable_grounding,
                                 verbose=args.verbose)
            # process_ticket now returns (result, trace)
            result, trace = ret if isinstance(ret, tuple) else (ret, {})
            results.append(result)
            traces.append(trace)
            print(f"{result['status'].upper()} [{result['request_type']}]")
            time.sleep(0.3)  # reduced from 2s to 0.3s

        if result["status"] == "replied":
            replied_count += 1
        else:
            escalated_count += 1

        # Write every 5 tickets (crash-safe)
        if (i + 1) % 5 == 0 or i == len(tickets) - 1:
            write_output(args.output, tickets[:i+1], results)

    duration = time.time() - start
    log_session_end(log_path, len(tickets), replied_count, escalated_count, duration)

    # Print run summary (includes self-reflection stats)
    summary = summarize_traces(traces)
    print(summary)
    print(f"\n{'='*50}")
    print(f"Done in {duration:.1f}s")
    print(f"  Output    : {args.output}")
    print(f"  Log       : {log_path}")

    # Append summary to log
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(summary + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()
