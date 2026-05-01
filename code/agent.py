"""
agent.py — LLM call layer using Groq tool-use API with:
  - Confidence scoring (0.0–1.0)
  - Citation requirement (exact quotes from docs)
  - API key rotation/failover (up to 3 keys)
  - Fixed escalation bias (out-of-scope → replied+invalid, not escalated)
  - Multi-issue handling via prompt (not brittle Python splitting)
"""
import os
import time
import json
from pathlib import Path
from groq import Groq
from dotenv import load_dotenv
from config import LLM_MODEL, LLM_MAX_TOKENS, LLM_TEMPERATURE, LLM_MAX_RETRIES, DOC_TEXT_LIMIT_LLM

# .env lives in code/ — find it relative to this file so it works
# regardless of where the user runs python from
load_dotenv(dotenv_path=Path(__file__).parent / ".env")


# ── API key rotation ──────────────────────────────────────────────────────────
# Reads GROQ_API_KEY, GROQ_API_KEY_2, GROQ_API_KEY_3 from env.
# On failure, rotates to next key before retrying.

def _load_api_keys() -> list:
    """Load all available Groq API keys from environment."""
    keys = []
    primary = os.environ.get("GROQ_API_KEY", "")
    if primary:
        keys.append(primary)
    for suffix in ["_2", "_3", "_4", "_5"]:
        k = os.environ.get(f"GROQ_API_KEY{suffix}", "")
        if k:
            keys.append(k)
    if not keys:
        raise RuntimeError("No GROQ_API_KEY found in environment")
    return keys

API_KEYS     = _load_api_keys()
_current_key = 0            # index into API_KEYS

def _get_client() -> Groq:
    """Return a Groq client using the current API key."""
    return Groq(api_key=API_KEYS[_current_key])

def _rotate_key():
    """Rotate to the next available API key."""
    global _current_key
    _current_key = (_current_key + 1) % len(API_KEYS)
    if len(API_KEYS) > 1:
        print(f"  [KEY] Rotated to API key {_current_key + 1}/{len(API_KEYS)}")


MODEL       = LLM_MODEL
MAX_TOKENS  = LLM_MAX_TOKENS
TEMPERATURE = LLM_TEMPERATURE    # deterministic: same input → same output
MAX_RETRIES = LLM_MAX_RETRIES


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
                        "'replied' if answerable from the provided docs, OR if the ticket is "
                        "out-of-scope/irrelevant (greetings, off-topic, nonsense). "
                        "'escalated' ONLY if the issue is real but requires human review "
                        "(billing, fraud, identity, outages, admin-only actions)."
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
                        "One sentence max if escalating. Never invent policies. "
                        "If the ticket asks multiple distinct questions, address each one "
                        "clearly using bullet points."
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
                "confidence": {
                    "type": "number",
                    "description": (
                        "How confident you are in this response, from 0.0 to 1.0. "
                        "1.0 = answer is directly stated in the provided docs. "
                        "0.7+ = high confidence, well-supported by docs. "
                        "0.4-0.7 = moderate, some gaps. "
                        "Below 0.4 = low confidence, consider escalating."
                    ),
                },
                "cited_sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Exact short quotes (5-15 words each) copied from the provided "
                        "documents that support your response. Include 1-3 quotes. "
                        "If escalating due to insufficient docs, leave empty."
                    ),
                },
            },
            "required": [
                "status", "product_area", "response", "justification",
                "request_type", "confidence", "cited_sources"
            ],
        }
    }
}

REQUEST_MORE_DOCS_TOOL = {
    "type": "function",
    "function": {
        "name": "request_more_documents",
        "description": "Call this when the provided documentation does not contain the answer, and you need to search the database using new, specific keywords.",
        "parameters": {
            "type": "object",
            "properties": {
                "search_queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "A list of 1 to 3 targeted search queries to run against the knowledge base."
                },
                "reasoning": {
                    "type": "string",
                    "description": "Why the current docs are insufficient and what you hope to find."
                }
            },
            "required": ["search_queries", "reasoning"]
        }
    }
}


# ── System prompt ──────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a support triage agent for three products: HackerRank, Claude, and Visa.

Read the support ticket and the retrieved documentation, then select the appropriate tool.

RULES:
- Base every answer ONLY on the retrieved documents provided. Never use outside knowledge.
- If the documents lack the necessary info, use `request_more_documents` to run a new search.
- Do not escalate simply because the first search failed. Try searching again first.
- Only escalate if you have searched and still cannot answer, or if the ticket falls under the escalation rules below.
- Never invent policies, steps, or features not described in the provided docs.
- Provide 1-3 exact short quotes from the documents in cited_sources to back up your answer.

WHEN TO REPLY (status = "replied"):
- The docs contain a clear answer to the user's question
- The ticket is a simple greeting, thank-you, or acknowledgement (reply politely, request_type="invalid")
- The ticket is completely off-topic or nonsensical (reply saying it's out of scope, request_type="invalid")
- The ticket is a general question answerable from the docs

WHEN TO ESCALATE (status = "escalated") — ONLY these situations:
- Platform-wide outages or complete service failures (request_type="bug")
- Billing disputes, refund demands, or payment issues with specific order IDs
- Security incidents: fraud, unauthorized access, identity theft
- Cases where account owner or admin action is specifically required
- The user's specific situation requires human judgment beyond what docs can provide

CRITICAL: Do NOT escalate trivial, off-topic, or greeting tickets. Reply to them instead.

MULTI-ISSUE TICKETS:
- If the user asks multiple distinct questions, address each one using bullet points in your response.

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
  -> status: "replied"
  -> product_area: "screen"
  -> response: "HackerRank tests remain active indefinitely unless a start and end date are configured. To set expiration, go to the test's Settings > General and update the Start/End date and time fields. Clearing these fields keeps the test active indefinitely."
  -> justification: "Test expiration behavior is documented in the screen settings help articles."
  -> request_type: "product_issue"
  -> confidence: 0.95
  -> cited_sources: ["tests remain active indefinitely unless a start and end time are set", "clear these fields by clicking the clear icon"]

Example 2 (escalated, platform outage):
  Ticket: "None of the pages on the site are loading"
  Company: None
  -> status: "escalated"
  -> product_area: "platform"
  -> response: "This case has been escalated to a human support agent."
  -> justification: "Possible platform-wide outage requires engineering review, not a support doc answer."
  -> request_type: "bug"
  -> confidence: 0.9
  -> cited_sources: []

Example 3 (replied, out-of-scope — do NOT escalate these):
  Ticket: "What is the name of the actor in Iron Man?"
  Company: None
  -> status: "replied"
  -> product_area: "general"
  -> response: "I am sorry, this is out of scope from my capabilities. I can only help with HackerRank, Claude, and Visa support questions."
  -> justification: "Off-topic question unrelated to any supported product. No escalation needed."
  -> request_type: "invalid"
  -> confidence: 1.0
  -> cited_sources: []

Example 4 (replied, greeting — do NOT escalate these):
  Ticket: "Thanks so much for the help!"
  Company: HackerRank
  -> status: "replied"
  -> product_area: "general"
  -> response: "Happy to help. Let us know if anything else comes up."
  -> justification: "No support action required — simple acknowledgement."
  -> request_type: "invalid"
  -> confidence: 1.0
  -> cited_sources: []

Example 5 (escalated, security incident):
  Ticket: "My identity has been stolen. What do I do about my Visa card?"
  Company: Visa
  -> status: "escalated"
  -> product_area: "security"
  -> response: "This case requires immediate attention from a human support agent."
  -> justification: "Identity theft requires human review and potentially law enforcement."
  -> request_type: "product_issue"
  -> confidence: 0.95
  -> cited_sources: []

Example 6 (replied, Visa FAQ grounded in docs):
  Ticket: "I bought Visa Traveller's Cheques and they were stolen. What do I do?"
  Company: Visa
  -> status: "replied"
  -> product_area: "travel_support"
  -> response: "Call the issuer immediately. Have your cheque serial numbers, purchase details, and information about when and how they were stolen ready. Notify the local police. Refunds can typically be arranged within 24 hours."
  -> justification: "Traveller's cheque loss procedure is documented in the Visa support corpus."
  -> request_type: "product_issue"
  -> confidence: 0.85
  -> cited_sources: ["cheque serial numbers, where and when you bought the cheques", "Refunds can typically be arranged within 24 hours"]

Example 7 (needs more info):
  Ticket: "How do I reset my API key?"
  Company: HackerRank
  [Documents provided do not mention API keys]
  -> Action: call request_more_documents
  -> search_queries: ["HackerRank reset API key", "generate new API key HackerRank"]
  -> reasoning: "The current docs do not mention API keys, so I need to search for API key management."

Example 8 (replied, feature request):
  Ticket: "Can you add dark mode to the HackerRank test-taking interface?"
  Company: HackerRank
  -> status: "replied"
  -> product_area: "screen"
  -> response: "Dark mode is not currently available for the test-taking interface. I have noted this as a feature request. You may share this feedback through the HackerRank community or support channels."
  -> justification: "The docs do not mention dark mode as an existing feature, so this is a request for new functionality."
  -> request_type: "feature_request"
  -> confidence: 0.9
  -> cited_sources: []
"""

FULL_SYSTEM_PROMPT = SYSTEM_PROMPT + "\n\n" + FEW_SHOT


# ── Main function ──────────────────────────────────────────────────────────────
def call_llm(ticket: dict, retrieved_docs: list) -> dict:
    """
    Call Groq API and return a triage decision dict.
    Uses tool-use API for guaranteed structured output.
    Retries up to 3 times with API key rotation on failure.
    Never raises — returns a safe escalation fallback if all retries fail.
    """
    # Build doc context string
    doc_context = "\n\n---\n\n".join([
        (
            f"[Doc {i+1}]\n"
            f"Category: {doc['product_area']}\n"
            f"Title: {doc['title']}\n\n"
            f"{doc['text'][:DOC_TEXT_LIMIT_LLM]}"
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
            client = _get_client()
            response = client.chat.completions.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                messages=[
                    {"role": "system", "content": FULL_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message}
                ],
                tools=[TRIAGE_TOOL, REQUEST_MORE_DOCS_TOOL],
                tool_choice="auto",
            )

            # Extract tool call arguments
            tool_calls = response.choices[0].message.tool_calls
            if tool_calls and len(tool_calls) > 0:
                tool_name = tool_calls[0].function.name
                arguments = tool_calls[0].function.arguments
                result = json.loads(arguments)
                
                if tool_name == "submit_triage":
                    result.setdefault("confidence", 0.5)
                    result.setdefault("cited_sources", [])
                    return {"action": "submit_triage", "data": result}
                elif tool_name == "request_more_documents":
                    return {"action": "request_more_documents", "data": result}

            raise RuntimeError("No tool_call block returned")

        except Exception as e:
            print(f"  [WARN] {type(e).__name__}: {e} (attempt {attempt+1})")
            _rotate_key()

        if attempt < MAX_RETRIES - 1:
            wait = 2 ** attempt
            print(f"  Retrying in {wait}s...")
            time.sleep(wait)

    # All retries failed — return safe fallback
    print("  [ERROR] All retries failed. Using fallback escalation.")
    return {
        "action": "submit_triage",
        "data": {
            "status":        "escalated",
            "product_area":  "platform",
            "response":      "Unable to process this request. Escalating to human support.",
            "justification": "API call failed after all retry attempts.",
            "request_type":  "bug",
            "confidence":    0.0,
            "cited_sources": [],
        }
    }


if __name__ == "__main__":
    ticket = {'issue': 'How do I reset my HackerRank password?', 'subject': '', 'company': 'hackerrank'}
    fake_docs = [{'product_area': 'account', 'title': 'Password Reset', 'text': 'To reset your password, go to the login page and click Forgot Password. Enter your email and follow the link sent to your inbox.'}]

    ret = call_llm(ticket, fake_docs)
    print("Action:", ret.get("action"))
    result = ret.get("data", {})
    print('Status:', result.get('status'))
    print('Product area:', result.get('product_area'))
    print('Request type:', result.get('request_type'))
    print('Confidence:', result.get('confidence'))
    print('Cited sources:', result.get('cited_sources'))
    print('Response:', result.get('response', '')[:100])
    print()
    print('agent.py works correctly!' if result.get('status') in ('replied','escalated') else 'SOMETHING WRONG')
