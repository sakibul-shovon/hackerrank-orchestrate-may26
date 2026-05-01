"""
product_areas.py — Normalize raw breadcrumb-derived product_area strings
into clean, consistent category labels for output CSV.

The corpus produces 146 unique raw product_area strings. This module maps
them to ~20 clean labels that match the expected output format.
"""

# ── Prefix-based mapping (order matters: longest prefix wins) ──────────────────
# Each tuple: (prefix, normalized_label)
# We match from top to bottom; first match wins.

PREFIX_RULES = [
    # HackerRank — Screen (tests, candidates, settings)
    ("screen_",                          "screen"),
    ("question_types_",                  "screen"),

    # HackerRank — Interviews
    ("interviews_",                      "interviews"),

    # HackerRank — Chakra (AI Interviewer)
    ("chakra_",                          "chakra"),

    # HackerRank — Library
    ("library_",                         "library"),

    # HackerRank — Community
    ("hackerrank_hackerrank_community",  "community"),
    ("contests",                         "community"),
    ("practice_coding_challenges",       "community"),
    ("prep_kits",                        "community"),
    ("certifications",                   "community"),
    ("mock_interviews",                  "community"),

    # HackerRank — Settings & Admin
    ("settings_",                        "settings"),
    ("integrations_",                    "integrations"),
    ("applicant_tracking_systems_",      "integrations"),

    # HackerRank — Account
    ("account_settings_",               "account_settings"),
    ("subscriptions,_payments,_and_billing", "billing"),

    # HackerRank — SkillUp
    ("skillup_",                         "skillup"),

    # HackerRank — Engage
    ("engage",                           "engage"),

    # HackerRank — General Help
    ("general_help_",                    "general"),
    ("getting_started",                  "general"),
    ("additional_resources",             "general"),

    # Claude — Privacy & Legal
    ("privacy_and_legal",                "privacy"),
    ("safeguards",                       "privacy"),

    # Claude — Plans & Billing
    ("pro_and_max_plans_",               "claude_plans"),
    ("team_and_enterprise_plans_",       "claude_plans"),

    # Claude — API & Code
    ("claude_api_and_console_",          "claude_api"),
    ("claude_code",                      "claude_code"),

    # Claude — Features & Usage
    ("claude_features_and_capabilities", "claude_features"),
    ("claude_usage_and_limits",          "claude_usage"),
    ("claude_conversation_management",   "conversation_management"),
    ("claude_get_started_with_claude",   "claude_getting_started"),
    ("claude_troubleshooting",           "claude_troubleshooting"),
    ("claude_personalization",           "claude_settings"),
    ("claude_account_management",        "claude_account"),

    # Claude — Platform-specific
    ("claude_desktop_",                  "claude_desktop"),
    ("claude_mobile_apps_",              "claude_mobile"),
    ("claude_in_chrome",                 "claude_chrome"),
    ("claude_for_education",             "claude_education"),
    ("claude_for_government",            "claude_government"),
    ("claude_for_nonprofits",            "claude_nonprofits"),
    ("connectors",                       "claude_connectors"),
    ("identity_management",              "claude_identity"),
    ("amazon_bedrock",                   "claude_bedrock"),

    # Visa
    ("visa_support_consumer_travel",     "travel_support"),
    ("visa_support_consumer",            "visa_consumer"),
    ("visa_support_small",               "visa_business"),
    ("visa_support",                     "visa_support"),
    ("visa",                             "visa_general"),

    # HackerRank catch-all
    ("hackerrank_uncategorized",         "general"),
    ("hackerrank",                       "general"),

    # Claude catch-all
    ("claude",                           "claude_general"),
]


def normalize_product_area(raw: str, domain: str = None) -> str:
    """
    Normalize a raw product_area string into a clean label.

    Args:
        raw: the raw product_area from corpus.py (e.g. 'screen_test_settings')
        domain: optional domain hint ('hackerrank', 'claude', 'visa')

    Returns:
        Normalized product area label (e.g. 'screen')
    """
    if not raw:
        return "general"

    raw_lower = raw.lower().strip()

    for prefix, label in PREFIX_RULES:
        if raw_lower.startswith(prefix):
            return label

    # Fallback: use domain if available
    if domain:
        return domain

    return "general"


if __name__ == "__main__":
    # Self-test: verify all 146 raw areas get mapped
    import sys
    sys.path.insert(0, "code")
    from corpus import load_corpus

    docs = load_corpus("data")
    raw_areas = set(d["product_area"] for d in docs)
    mapped = {}
    unmapped = []

    for raw in sorted(raw_areas):
        norm = normalize_product_area(raw)
        mapped.setdefault(norm, []).append(raw)
        if norm == "general" and not raw.startswith("general"):
            unmapped.append(raw)

    print(f"Raw areas: {len(raw_areas)}")
    print(f"Normalized to: {len(mapped)} categories\n")

    for label in sorted(mapped):
        count = len(mapped[label])
        print(f"  {label:30s} ({count} raw areas)")

    if unmapped:
        print(f"\n[WARN] Unmapped areas ({len(unmapped)}):")
        for u in unmapped:
            print(f"  - {u}")
    else:
        print("\n✓ All areas mapped successfully!")
