"""
corpus.py — Loads all markdown documents from data/
"""
import os
import re
from pathlib import Path


def load_corpus(base_path="data"):
    docs = []
    base = Path(base_path)

    for path in sorted(base.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        # Extract breadcrumbs from YAML frontmatter
        breadcrumbs = []
        bc_match = re.search(r'breadcrumbs:\s*\n((?:\s*-\s*".+"\n?)+)', text)
        if bc_match:
            breadcrumbs = re.findall(r'-\s*"(.+)"', bc_match.group(1))

        # Domain = top-level subfolder name
        try:
            rel = path.relative_to(base)
            domain = rel.parts[0]
        except ValueError:
            domain = "unknown"

        # product_area from last 2 breadcrumbs
        if breadcrumbs:
            product_area = "_".join(breadcrumbs[-2:]).lower().replace(" ", "_")
        else:
            product_area = (
                str(path.parent.relative_to(base))
                .replace(os.sep, "_")
                .lower()
            )

        # Strip YAML frontmatter for clean retrieval text
        body = re.sub(r"^---.*?---\s*", "", text, flags=re.DOTALL).strip()

        docs.append({
            "path":         str(path),
            "domain":       domain,
            "breadcrumbs":  breadcrumbs,
            "product_area": product_area,
            "title":        breadcrumbs[-1] if breadcrumbs else path.stem,
            "text":         body,
        })

    return docs


if __name__ == "__main__":
    docs = load_corpus("data")
    domains = {}
    for d in docs:
        domains[d["domain"]] = domains.get(d["domain"], 0) + 1

    print(f"Loaded {len(docs)} documents")
    for domain, count in sorted(domains.items()):
        print(f"  {domain}: {count} docs")

    print("\nSample breadcrumbs (first 5):")
    for d in docs[:5]:
        print(f"  {d['breadcrumbs']} -> {d['product_area']}")
