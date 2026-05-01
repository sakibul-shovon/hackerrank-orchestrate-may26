"""
interactive.py — Interactive CLI to test the triage agent with custom questions.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from corpus import load_corpus
from retriever import build_index
from main import process_ticket

def main():
    print("Loading corpus...")
    docs = load_corpus("data")
    print("Building index...")
    bm25, embeddings = build_index(docs)
    print("\n" + "="*50)
    print("🤖 Interactive Support Triage Agent Ready!")
    print("="*50 + "\n")

    log_path = Path.home() / "hackerrank_orchestrate" / "log.txt"

    while True:
        try:
            print("\n--- New Ticket ---")
            company = input("Company (hackerrank, claude, visa, or leave empty): ").strip()
            issue = input("Issue / Question: ").strip()
            
            if not issue:
                print("Issue cannot be empty.")
                continue

            ticket = {
                "issue": issue,
                "subject": "",
                "company": company
            }

            print("\nProcessing...")
            result, trace = process_ticket(ticket, idx=0, docs=docs, bm25=bm25, embeddings=embeddings, log_path=log_path, verbose=False)

            print("\n" + "="*50)
            print(f"Status       : {result['status'].upper()}")
            print(f"Product Area : {result['product_area']}")
            print(f"Request Type : {result['request_type']}")
            print(f"Response     : {result['response']}")
            print(f"Justification: {result['justification']}")
            print("="*50)

        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"\nError: {e}")

if __name__ == "__main__":
    main()
