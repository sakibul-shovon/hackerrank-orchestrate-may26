"""
escalation_rules.py — Hard-coded deterministic escalation rules
Order matters: first match wins. Most critical rules are listed first.
"""
import re

# Format: (regex_pattern, product_area, escalation_reason)
ESCALATION_RULES = [
    (
        r"identity\s+(stolen|theft|compromised)",
        "security",
        "Identity theft — requires human agent and potentially law enforcement"
    ),
    (
        r"(card|account)\s+(stolen|hacked|compromised|fraud)",
        "security",
        "Financial security incident — requires immediate human review"
    ),
    (
        r"none\s+of\s+the\s+submissions.*(working|failing)",
        "platform",
        "Platform-wide submission failure — requires engineering escalation"
    ),
    (
        r"all\s+requests\s+are\s+failing",
        "platform",
        "Service outage detected — requires engineering escalation"
    ),
    (
        r"(site|platform|everything)\s+is\s+down",
        "platform",
        "Platform-wide outage — requires engineering escalation"
    ),
    (
        r"(stopped|stop)\s+working\s+completely",
        "platform",
        "Complete service failure — requires engineering escalation"
    ),
    (
        r"restore\s+my\s+access.{0,80}(not|no longer).{0,20}(owner|admin)",
        "account_management",
        "Access restoration for non-admin requires admin or owner action"
    ),
    (
        r"refund.{0,20}asap",
        "billing",
        "Urgent refund request — requires human billing agent"
    ),
    (
        r"give\s+me\s+my\s+money",
        "billing",
        "Billing dispute — requires human billing agent"
    ),
    (
        r"payment.{0,30}order\s+(id|#)",
        "billing",
        "Specific payment dispute with order ID — requires billing lookup"
    ),
    (
        r"(increase|change|modify)\s+my\s+score",
        "screen",
        "Score modification — HackerRank cannot alter recruiter decisions"
    ),
    (
        r"tell\s+the\s+company\s+to\s+move\s+me",
        "screen",
        "Candidate requesting recruiter action — outside support scope"
    ),
]


def check_escalation_rules(issue_text: str):
    for pattern, area, reason in ESCALATION_RULES:
        if re.search(pattern, issue_text, re.IGNORECASE):
            return area, reason
    return None, None


if __name__ == "__main__":
    tests = [
        ("My identity has been stolen",                              True),
        ("None of the submissions across any challenges are working", True),
        ("Claude has stopped working completely",                     True),
        ("Please increase my score",                                  True),
        ("I had a payment issue with order ID: cs_live_abc123",       True),
        ("How do I update my profile picture?",                       False),
        ("I can't find the certificate download button",              False),
    ]

    all_passed = True
    for text, should_escalate in tests:
        area, reason = check_escalation_rules(text)
        did_escalate = area is not None
        passed = did_escalate == should_escalate
        mark = "✓" if passed else "✗ FAIL"
        label = "ESCALATE" if should_escalate else "PASS"
        print(f"[{mark}] Expected {label}: {text[:60]}")
        if area:
            print(f"      -> {area}: {reason}")
        if not passed:
            all_passed = False

    print(f"\n{'All tests passed!' if all_passed else 'SOME TESTS FAILED — fix escalation_rules.py'}")
