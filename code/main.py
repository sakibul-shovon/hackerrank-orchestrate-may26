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


# ── Confidence threshold ───────────────────────────────────────────────────────
CONFIDENCE_ESCALATION_THRESHOLD = 0.4  # auto-escalate if below this


# ── Process one ticket ─────────────────────────────────────────────────────────

def process_ticket(ticket, idx, docs, bm25, embeddings, log_path, verbose=False):
    issue   = ticket.get("issue", "")
    subject = ticket.get("subject", "")
    company = ticket.get("company", "none").strip().lower()
    query   = f"{subject} {issue}".strip()

    if verbose:
        print(f"\n  Issue  : {issue[:80]}")
        print(f"  Company: {company}")

    # Stage 1: Safety
    threat, reason = check_safety(issue)
    lang = detect_language(issue)
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
        log_ticket(log_path, idx, ticket, "safety_filter", result, lang)
        return result

    # Stage 2: Domain routing + inference
    domain_filter = DOMAIN_MAP.get(company)
    inferred_domain = None
    if domain_filter is None:
        # company is None/empty — try to infer from content
        inferred_domain = infer_domain(issue, subject)
        domain_filter = inferred_domain
        if verbose and inferred_domain:
            print(f"  Domain : {inferred_domain} (inferred from content)")
        elif verbose:
            print(f"  Domain : None (searching all domains)")

    # Stage 3: Retrieve
    retrieved = hybrid_retrieve(query, docs, bm25, embeddings,
                                domain_filter=domain_filter, top_k=5)
    if verbose:
        print(f"  Docs   : {[d['title'][:30] for d in retrieved]}")

    # Stage 4: Escalation rules (deterministic)
    esc_area, esc_req_type, esc_reason = check_escalation_rules(issue)
    if esc_area:
        if verbose:
            print(f"  [RULE]   {esc_reason}")
        result = {
            "status": "escalated", "product_area": esc_area,
            "response": "This case requires attention from a human support agent.",
            "justification": esc_reason, "request_type": esc_req_type,
        }
        log_ticket(log_path, idx, ticket, "escalation_rules", result, lang)
        return result

    # Stage 5: LLM call
    if verbose:
        print(f"  Calling LLM...")
    result = call_llm({"issue": issue, "subject": subject, "company": company}, retrieved)

    # Stage 5b: Confidence-based auto-escalation
    confidence = result.get("confidence", 0.5)
    if verbose:
        print(f"  Confidence: {confidence:.2f}")
    if confidence < CONFIDENCE_ESCALATION_THRESHOLD and result.get("status") == "replied":
        if verbose:
            print(f"  [LOW CONFIDENCE] {confidence:.2f} < {CONFIDENCE_ESCALATION_THRESHOLD} -> auto-escalating")
        result["status"] = "escalated"
        result["justification"] = (
            f"Auto-escalated due to low confidence ({confidence:.2f}). "
            + result.get("justification", "")
        )

    # Stage 6: Grounding check (only for replied tickets)
    if result.get("status") == "replied" and result.get("request_type") != "invalid":
        grounded, why = is_grounded(result.get("response", ""), retrieved)
        if not grounded:
            if verbose:
                print(f"  [UNGROUNDED] {why}")
            result = {
                "status": "escalated",
                "product_area": result.get("product_area", "general"),
                "response": "This case requires attention from a human support agent.",
                "justification": f"Response not grounded in corpus: {why}".rstrip(": "),
                "request_type": "product_issue",
            }

    # Stage 7: Validate + normalize
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
        print(f"  -> {result['status'].upper()} | {result['product_area']} | {result['request_type']}")

    log_ticket(log_path, idx, ticket, "llm_call", result, lang)
    return result


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Support Triage Agent")
    parser.add_argument("--input",    "-i", default="support_tickets/support_tickets.csv")
    parser.add_argument("--output",   "-o", default="support_tickets/output.csv")
    parser.add_argument("--data-dir",       default="data")
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

    results        = []
    replied_count  = 0
    escalated_count = 0
    start          = time.time()

    for i, ticket in enumerate(tickets):
        print(f"Ticket {i+1}/{len(tickets)}...", end=" ", flush=True)
        h = _hash(ticket)
        if h in cache:
            result = cache[h]
            results.append(result)
            print(f"CACHED")
        else:
            result = process_ticket(ticket, i, docs, bm25, embeddings,
                                    log_path, verbose=args.verbose)
            results.append(result)
            print(f"{result['status'].upper()} [{result['request_type']}]")
            time.sleep(0.3)

        if result["status"] == "replied":
            replied_count += 1
        else:
            escalated_count += 1

        # Write every 5 tickets (crash-safe)
        if (i + 1) % 5 == 0 or i == len(tickets) - 1:
            write_output(args.output, tickets[:i+1], results)

    duration = time.time() - start
    log_session_end(log_path, len(tickets), replied_count, escalated_count, duration)

    print(f"\n{'='*50}")
    print(f"Done in {duration:.1f}s")
    print(f"  Replied   : {replied_count}")
    print(f"  Escalated : {escalated_count}")
    print(f"  Output    : {args.output}")
    print(f"  Log       : {log_path}")


if __name__ == "__main__":
    main()
