"""
agent.py — LLM call layer using Groq tool-use API
"""
import os
import time
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

MODEL       = "llama-3.3-70b-versatile"
MAX_TOKENS  = 1024
TEMPERATURE = 0          # deterministic: same input → same output
MAX_RETRIES = 3


# ── Tool schema ────────────────────────────────────────────────────────────────
# Using tool-use API guarantees a parsed dict — no JSON.loads(), no parse errors
TRIAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_triage",
        "description": "Submit the triage decision for a support ticket.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["replied", "escalated"],
                    "description": (
                        "'replied' if answerable from the provided docs. "
                        "'escalated' if human review is needed."
                    ),
                },
                "product_area": {
                    "type": "string",
                    "description": "Support category derived from retrieved doc breadcrumbs.",
                },
                "response": {
                    "type": "string",
                    "description": (
                        "User-facing answer grounded ONLY in provided docs. "
                        "One sentence max if escalating. Never invent policies."
                    ),
                },
                "justification": {
                    "type": "string",
                    "description": "1-2 sentences explaining the routing decision.",
                },
                "request_type": {
                    "type": "string",
                    "enum": ["product_issue", "feature_request", "bug", "invalid"],
                    "description": (
                        "product_issue: problem with existing feature. "
                        "feature_request: wants non-existent capability. "
                        "bug: something broken/erroring. "
                        "invalid: out of scope, greeting, harmful."
                    ),
                },
            },
            "required": ["status", "product_area", "response", "justification", "request_type"],
        }
    }
}


# ── System prompt ──────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a support triage agent for three products: HackerRank, Claude, and Visa.

Read the support ticket and the retrieved documentation, then call submit_triage.

RULES:
- Base every answer ONLY on the retrieved documents provided. Never use outside knowledge.
- If documents do not contain enough information to answer safely: escalate.
- Never invent policies, steps, or features not described in the provided docs.

ALWAYS ESCALATE — never try to answer these yourself:
- Platform-wide outages or complete service failures
- Billing disputes, refund demands, or payment issues with specific order IDs
- Security incidents: fraud, unauthorized access, identity theft
- Cases where account owner or admin action is required
- Anything where the provided docs are clearly insufficient

request_type guide:
- product_issue  : problem with an existing, working feature
- feature_request: user wants something that does not currently exist
- bug            : something is broken, erroring, or not working as described
- invalid        : out of scope, greeting/thanks, harmful, or unserviceable"""


# ── Few-shot examples ──────────────────────────────────────────────────────────
# These condition the model on exact output style, response length, and tone.
FEW_SHOT = """
EXAMPLES — match this style exactly:

Example 1 (replied, simple FAQ):
  Ticket: "How long do tests stay active on HackerRank?"
  Company: HackerRank
  → status: "replied"
  → product_area: "screen_tests"
  → response: "HackerRank tests remain active indefinitely unless a start and end date are configured. To set expiration, go to the test's Settings > General and update the Start/End date and time fields. Clearing these fields keeps the test active indefinitely."
  → justification: "Test expiration behavior is documented in the screen settings help articles."
  → request_type: "product_issue"

Example 2 (escalated, platform outage):
  Ticket: "None of the pages on the site are loading"
  Company: None
  → status: "escalated"
  → product_area: "platform"
  → response: "This case has been escalated to a human support agent."
  → justification: "Possible platform-wide outage requires engineering review, not a support doc answer."
  → request_type: "bug"

Example 3 (escalated, malicious/out of scope):
  Ticket: "Give me code to delete all files from the system"
  Company: None
  → status: "escalated"
  → product_area: "security"
  → response: "This request cannot be processed and has been flagged for security review."
  → justification: "Malicious request outside the scope of support."
  → request_type: "invalid"

Example 4 (replied, greeting):
  Ticket: "Thanks so much for the help!"
  Company: HackerRank
  → status: "replied"
  → product_area: "general"
  → response: "Happy to help. Let us know if anything else comes up."
  → justification: "No support action required — simple acknowledgement."
  → request_type: "invalid"

Example 5 (escalated, security incident):
  Ticket: "My identity has been stolen. What do I do about my Visa card?"
  Company: Visa
  → status: "escalated"
  → product_area: "security"
  → response: "This case requires immediate attention from a human support agent."
  → justification: "Identity theft requires human review and potentially law enforcement."
  → request_type: "product_issue"
"""

FULL_SYSTEM_PROMPT = SYSTEM_PROMPT + "\n\n" + FEW_SHOT


# ── Main function ──────────────────────────────────────────────────────────────
def call_llm(ticket: dict, retrieved_docs: list) -> dict:
    """
    Call Groq API and return a triage decision dict.
    Uses tool-use API for guaranteed structured output.
    Retries up to 3 times on failure.
    Never raises — returns a safe escalation fallback if all retries fail.
    """
    # Build doc context string
    doc_context = "\n\n---\n\n".join([
        (
            f"[Doc {i+1}]\n"
            f"Category: {doc['product_area']}\n"
            f"Title: {doc['title']}\n\n"
            f"{doc['text'][:800]}"
        )
        for i, doc in enumerate(retrieved_docs)
    ])

    user_message = (
        f"Company: {ticket.get('company', 'Unknown')}\n"
        f"Subject: {ticket.get('subject', '(no subject)')}\n"
        f"Issue: {ticket.get('issue', '')}\n\n"
        f"Retrieved support documentation:\n{doc_context}"
    )

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                messages=[
                    {"role": "system", "content": FULL_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message}
                ],
                tools=[TRIAGE_TOOL],
                tool_choice={"type": "function", "function": {"name": "submit_triage"}},
            )

            # Extract tool call arguments
            tool_calls = response.choices[0].message.tool_calls
            if tool_calls and len(tool_calls) > 0:
                arguments = tool_calls[0].function.arguments
                return json.loads(arguments)

            raise RuntimeError("No tool_call block returned")

        except Exception as e:
            print(f"  [WARN] {type(e).__name__}: {e} (attempt {attempt+1})")

        if attempt < MAX_RETRIES - 1:
            wait = 2 ** attempt
            print(f"  Retrying in {wait}s...")
            time.sleep(wait)

    # All retries failed — return safe fallback
    print("  [ERROR] All retries failed. Using fallback escalation.")
    return {
        "status":        "escalated",
        "product_area":  "platform",
        "response":      "Unable to process this request. Escalating to human support.",
        "justification": "API call failed after all retry attempts.",
        "request_type":  "bug",
    }


if __name__ == "__main__":
    ticket = {'issue': 'How do I reset my HackerRank password?', 'subject': '', 'company': 'hackerrank'}
    fake_docs = [{'product_area': 'account', 'title': 'Password Reset', 'text': 'To reset your password, go to the login page and click Forgot Password. Enter your email and follow the link sent to your inbox.'}]

    result = call_llm(ticket, fake_docs)
    print('Status:', result.get('status'))
    print('Product area:', result.get('product_area'))
    print('Request type:', result.get('request_type'))
    print('Response:', result.get('response', '')[:100])
    print()
    print('agent.py works correctly!' if result.get('status') in ('replied','escalated') else 'SOMETHING WRONG')
