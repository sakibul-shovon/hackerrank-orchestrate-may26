"""Check API quota status for both models."""
from groq import Groq
import os, re
from dotenv import load_dotenv
load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

for model, label in [("llama-3.3-70b-versatile", "70B (main)"), ("llama-3.1-8b-instant", "8B (grounding)")]:
    try:
        client.chat.completions.create(model=model, max_tokens=5,
            messages=[{"role":"user","content":"hi"}])
        print(f"{label}: OK - quota available")
    except Exception as e:
        msg = str(e)
        m = re.search(r"Please try again in ([^.\"']+)", msg)
        wait = m.group(1).strip() if m else "unknown"
        if "rate_limit" in msg.lower():
            print(f"{label}: Rate limited. Reset in ~{wait}")
        else:
            print(f"{label}: Error: {msg[:150]}")
