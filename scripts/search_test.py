"""Search test — Sprint 1 verification (no chat, no LLM answers).

Run from the backend/ directory:
    python ../scripts/search_test.py

Loads the local vector store + embedding model, runs two queries and
prints the top-3 chunks (title + page + score). Asserts the top result
comes from the correct document. Exit code 0 = pass, 1 = fail.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.db.vector_store import LocalVectorStore
from app.services import embeddings as emb

QUERIES = [
    # The KYC Policy holds the authoritative "Documents Needed for Account
    # Opening" list (section 3), so it — not the Account Opening Policy —
    # is the correct top result for this question. Both docs contain the
    # list; the KYC chunk scores higher because it is KYC-specific.
    ("What documents are needed for KYC account opening?",
     "01-kyc-policy.pdf"),
    ("What is the AML reporting threshold?",
     "02-aml-policy.pdf"),
    # Unique to the Account Opening Policy: branch opening takes 45 minutes.
    ("How long does it take to open an account at a branch?",
     "05-account-opening-policy.pdf"),
]


def main() -> int:
    store = LocalVectorStore()
    if not store.load():
        print("FAIL: no vector store found — run scripts/index_chunks.py first")
        return 1
    print(f"Embedding model: {emb.model_info()}")
    print(f"Chunks in store: {len(store._meta)}")
    ok = True
    for question, expected_doc in QUERIES:
        print(f"\nQ: {question}")
        qvec = emb.encode_query(question)
        results = store.search(qvec, top_k=3)
        for i, r in enumerate(results, start=1):
            print(f"  {i}. [{r['score']:.4f}] {r['title']} (p.{r['page_no']}) — {r['document_id']}")
            print(f"     {r['content'][:180].replace(chr(10), ' ')}...")
        top_doc = results[0]["document_id"] if results else None
        passed = top_doc == expected_doc
        ok = ok and passed
        print(f"  -> top result doc: {top_doc} | expected: {expected_doc} | {'PASS' if passed else 'FAIL'}")
    print(f"\nSearch test: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
