"""
domain_inference.py — Infer the most likely domain when company field is None/empty.

Problem statement (line 48): "If company is None, the issue may be generic
or cross-domain, and your agent should infer the best handling from the content"
"""


# ── Domain keyword sets ────────────────────────────────────────────────────────
# Weighted keywords: (keyword, weight) — higher weight = stronger signal

DOMAIN_SIGNALS = {
    "hackerrank": [
        ("hackerrank", 5), ("hacker rank", 5),
        ("test", 1), ("assessment", 3), ("candidate", 3),
        ("coding", 2), ("challenge", 2), ("screen", 2),
        ("interview", 2), ("recruiter", 3), ("hiring", 3),
        ("submission", 2), ("leaderboard", 2), ("contest", 2),
        ("proctoring", 3), ("certificate", 2), ("skillup", 4),
        ("chakra", 4), ("code pair", 3), ("codepair", 3),
    ],
    "claude": [
        ("claude", 5), ("anthropic", 5),
        ("ai", 1), ("conversation", 2), ("chat", 1),
        ("prompt", 2), ("model", 1), ("opus", 4), ("sonnet", 4),
        ("haiku", 4), ("artifact", 3), ("temporary chat", 4),
        ("bedrock", 3), ("api key", 2), ("token", 1),
        ("connector", 3), ("claude code", 5), ("claude desktop", 5),
        ("lti", 2),
    ],
    "visa": [
        ("visa", 4), ("card", 2), ("payment", 2),
        ("transaction", 3), ("merchant", 3), ("bank", 2),
        ("refund", 2), ("cheque", 4), ("traveller", 3),
        ("atm", 3), ("cardholder", 4), ("credit card", 3),
        ("debit card", 3), ("stolen", 2), ("fraud", 2),
        ("dispute", 2), ("chargeback", 4), ("issuer", 3),
    ],
}


def infer_domain(issue_text: str, subject: str = "") -> str | None:
    """
    Infer the most likely domain from ticket content.

    Returns:
        "hackerrank", "claude", "visa", or None if ambiguous/no signal.
    """
    combined = f"{subject} {issue_text}".lower()
    scores = {}

    for domain, keywords in DOMAIN_SIGNALS.items():
        score = 0
        for keyword, weight in keywords:
            if keyword in combined:
                score += weight
        scores[domain] = score

    best_domain = max(scores, key=scores.get)
    best_score = scores[best_domain]

    # Need minimum signal strength to make a call
    if best_score < 2:
        return None  # Too ambiguous — search all domains

    # Need clear winner (at least 2x the runner-up)
    second_best = sorted(scores.values(), reverse=True)[1]
    if best_score <= second_best:
        return None  # Too close to call

    return best_domain


if __name__ == "__main__":
    tests = [
        # (issue, subject, expected_domain)
        ("My HackerRank test score seems wrong", "", "hackerrank"),
        ("Claude has stopped working completely", "", "claude"),
        ("My Visa card was charged twice", "", "visa"),
        ("it's not working, help", "Help needed", None),
        ("Thank you for helping me", "", None),
        ("site is down & none of the pages are accessible", "", None),
        ("What is the name of the actor in Iron Man?", "Urgent, please help", None),
        ("I want Claude to stop crawling my website", "", "claude"),
        ("none of the submissions across any challenges are working", "", "hackerrank"),
        ("I bought Visa Traveller's Cheques and they were stolen", "", "visa"),
    ]

    all_passed = True
    for issue, subject, expected in tests:
        result = infer_domain(issue, subject)
        passed = result == expected
        mark = "[OK]" if passed else "[FAIL]"
        if not passed:
            all_passed = False
        print(f"  {mark} Expected={expected}, Got={result}: {issue[:60]}")

    print(f"\n{'All tests passed!' if all_passed else 'SOME TESTS FAILED'}")
