"""
escalation_rules.py — Hard-coded deterministic escalation rules
Order matters: first match wins. Most critical rules are listed first.

Each rule: (regex_pattern, product_area, request_type, escalation_reason)
"""
import re

# Format: (regex_pattern, product_area, request_type, escalation_reason)
ESCALATION_RULES = [
    (
        r"identity\s+(?:\w+\s+)*(stolen|theft|compromised)",
        "security", "product_issue",
        "Identity theft — requires human agent and potentially law enforcement"
    ),
    (
        r"(card|account)\s+(stolen|hacked|compromised|fraud)",
        "security", "product_issue",
        "Financial security incident — requires immediate human review"
    ),
    (
        r"none\s+of\s+the\s+submissions.*(working|failing)",
        "platform", "bug",
        "Platform-wide submission failure — requires engineering escalation"
    ),
    (
        r"all\s+(api\s+)?requests\s+are\s+failing",
        "platform", "bug",
        "Service outage detected — requires engineering escalation"
    ),
    (
        r"(site|platform|everything)\s+is\s+down",
        "platform", "bug",
        "Platform-wide outage — requires engineering escalation"
    ),
    (
        r"none\s+of\s+the\s+pages",
        "platform", "bug",
        "Platform-wide page failure — requires engineering escalation"
    ),
    (
        r"(everything|entire\s+\w+)\s+(stopped|stop)\s+working",
        "platform", "bug",
        "Complete service failure — requires engineering escalation"
    ),
    (
        r"restore\s+my\s+access.{0,80}(not|no longer).{0,20}(owner|admin)",
        "account_management", "product_issue",
        "Access restoration for non-admin requires admin or owner action"
    ),
    (
        r"refund.{0,20}asap",
        "billing", "product_issue",
        "Urgent refund request — requires human billing agent"
    ),
    (
        r"give\s+me\s+my\s+money",
        "billing", "product_issue",
        "Billing dispute — requires human billing agent"
    ),
    (
        r"payment.{0,30}order\s+(id|#)",
        "billing", "product_issue",
        "Specific payment dispute with order ID — requires billing lookup"
    ),
    (
        r"(increase|change|modify)\s+my\s+score",
        "screen", "product_issue",
        "Score modification — HackerRank cannot alter recruiter decisions"
    ),
    (
        r"tell\s+the\s+company\s+to\s+move\s+me",
        "screen", "product_issue",
        "Candidate requesting recruiter action — outside support scope"
    ),
]


def check_escalation_rules(issue_text: str):
    """
    Check if the issue matches any hard escalation rule.
    Returns (product_area, request_type, reason) or (None, None, None).
    """
    for pattern, area, req_type, reason in ESCALATION_RULES:
        if re.search(pattern, issue_text, re.IGNORECASE):
            return area, req_type, reason
    return None, None, None


if __name__ == "__main__":
    tests = [
        ("My identity has been stolen",                              True),
        ("None of the submissions across any challenges are working", True),
        ("Everything stopped working on the platform",                True),
        ("Please increase my score",                                  True),
        ("I had a payment issue with order ID: cs_live_abc123",       True),
        ("site is down & none of the pages are accessible",           True),
        ("How do I update my profile picture?",                       False),
        ("I can't find the certificate download button",              False),
        ("Claude has stopped working completely",                     False),
    ]

    all_passed = True
    for text, should_escalate in tests:
        area, req_type, reason = check_escalation_rules(text)
        did_escalate = area is not None
        passed = did_escalate == should_escalate
        mark = "[OK]" if passed else "[FAIL]"
        label = "ESCALATE" if should_escalate else "PASS"
        print(f"  {mark} Expected {label}: {text[:60]}")
        if area:
            print(f"      -> {area} [{req_type}]: {reason}")
        if not passed:
            all_passed = False

    print(f"\n{'All tests passed!' if all_passed else 'SOME TESTS FAILED'}")
