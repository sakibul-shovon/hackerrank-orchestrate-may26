"""
reasoning_trace.py — Structured reasoning trace for every ticket decision.

Records what happened at each stage of the pipeline for:
  - Debugging during development
  - The AI judge interview (show your reasoning clearly)
  - Log file evidence of agentic behaviour

Usage:
    trace = create_trace(ticket_id=1, issue="...", company="...")
    add_stage(trace, "safety",    {"passed": True, "language": "en"})
    add_stage(trace, "domain",    {"detected": "hackerrank", "source": "field"})
    add_stage(trace, "retrieval", {"docs_found": 5, "top_doc": "...", "top_score": 0.87})
    add_stage(trace, "llm",       {"model": "llama-3.3-70b", "confidence": 0.82, "attempt": 1})
    add_stage(trace, "reflection",{"triggered": False, "reason": "confidence OK"})
    add_stage(trace, "grounding", {"verified": True, "citations_checked": 2})
    add_stage(trace, "confidence",{"final": 0.81, "signals": {...}})
    finalize_trace(trace, result_dict)
"""
import time


def create_trace(ticket_id: int, issue: str = "", company: str = "") -> dict:
    """Initialise a new reasoning trace for one ticket."""
    return {
        "ticket_id":    ticket_id,
        "issue_preview": issue[:80],
        "company":      company,
        "start_time":   time.time(),
        "stages":       {},
        "decision":     None,
        "processing_ms": None,
    }


def add_stage(trace: dict, stage_name: str, data: dict):
    """Record the output of one pipeline stage."""
    trace["stages"][stage_name] = data


def finalize_trace(trace: dict, result: dict) -> dict:
    """
    Mark the trace as complete. Records the final decision and
    processing time. Returns the updated trace.
    """
    elapsed_ms = int((time.time() - trace["start_time"]) * 1000)
    trace["processing_ms"] = elapsed_ms
    trace["decision"] = {
        "status":       result.get("status"),
        "product_area": result.get("product_area"),
        "request_type": result.get("request_type"),
        "confidence":   result.get("confidence", "N/A"),
    }
    return trace


def format_trace_for_log(trace: dict) -> str:
    """
    Render the trace as a clean, human-readable string for the log file.
    This is what judges see in the AI interview when you show your logs.
    """
    lines = []
    lines.append(f"=== TRACE: Ticket #{trace['ticket_id']} ===")
    lines.append(f"  Issue   : {trace['issue_preview']}")
    lines.append(f"  Company : {trace['company']}")
    lines.append(f"  Time    : {trace.get('processing_ms', 'N/A')}ms")
    lines.append("")

    # Stages
    for stage, data in trace.get("stages", {}).items():
        lines.append(f"  [{stage.upper()}]")
        for k, v in data.items():
            lines.append(f"    {k}: {v}")

    # Final decision
    dec = trace.get("decision") or {}
    lines.append("")
    lines.append("  [DECISION]")
    lines.append(f"    status       : {dec.get('status', 'N/A')}")
    lines.append(f"    product_area : {dec.get('product_area', 'N/A')}")
    lines.append(f"    request_type : {dec.get('request_type', 'N/A')}")
    lines.append(f"    confidence   : {dec.get('confidence', 'N/A')}")
    lines.append("=" * 40)

    return "\n".join(lines)


def summarize_traces(traces: list) -> str:
    """
    Produce a run-level summary across all traces.
    Useful for end-of-run reporting.
    """
    total    = len(traces)
    replied  = sum(1 for t in traces if t.get("decision", {}).get("status") == "replied")
    escalated = total - replied
    avg_ms   = (
        sum(t.get("processing_ms", 0) for t in traces) // total
        if total else 0
    )

    reflected = sum(
        1 for t in traces
        if t.get("stages", {}).get("reflection", {}).get("triggered", False)
    )

    confidences = [
        t.get("decision", {}).get("confidence", None)
        for t in traces
        if isinstance(t.get("decision", {}).get("confidence"), (int, float))
    ]
    avg_conf = round(sum(confidences) / len(confidences), 2) if confidences else "N/A"

    lines = [
        "",
        "=== RUN SUMMARY ===",
        f"  Total tickets     : {total}",
        f"  Replied           : {replied}  ({replied*100//total if total else 0}%)",
        f"  Escalated         : {escalated}  ({escalated*100//total if total else 0}%)",
        f"  Self-reflected    : {reflected}  ({reflected*100//total if total else 0}%)",
        f"  Avg confidence    : {avg_conf}",
        f"  Avg latency       : {avg_ms}ms",
        "=" * 20,
    ]
    return "\n".join(lines)
