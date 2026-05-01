"""
grounding.py — Post-LLM grounding verifier
Only runs on 'replied' tickets. Escalates ungrounded responses.
Fail-open: if the verifier itself breaks, it trusts the original response.
"""
import json
import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))


def is_grounded(response_text: str, retrieved_docs: list) -> tuple:
    """
    Check if response_text is supported by retrieved_docs.

    Returns:
        (True,  "")      — grounded, safe to return to user
        (False, "why")   — ungrounded, should escalate instead
        (True,  "")      — fallback if verifier itself fails (fail-open)
    """
    if not response_text or not retrieved_docs:
        return False, "no response or no docs"

    excerpts = "\n---\n".join(d["text"][:600] for d in retrieved_docs[:3])

    prompt = (
        'Reply ONLY with JSON: {"grounded": true or false, "unsupported": "brief reason or empty"}\n\n'
        "Is every factual claim in the Response supported by the Documents?\n\n"
        f"Response:\n{response_text}\n\n"
        f"Documents:\n{excerpts}"
    )

    try:
        msg = _client.chat.completions.create(
            model="llama3-8b-8192",  # using a smaller model for faster/cheaper verification
            max_tokens=200,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        raw = msg.choices[0].message.content.strip()
        result = json.loads(raw)
        return bool(result.get("grounded", True)), str(result.get("unsupported", ""))
    except Exception as e:
        # Fail open — don't over-escalate on verifier bug
        print(f"  [WARN] Grounding check failed ({type(e).__name__}), skipping.")
        return True, ""
