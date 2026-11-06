"""RAG verification script — Sprint 2 acceptance test (10 questions).

Run from the backend/ directory:
    python ../scripts/rag_test.py

Prints, for each question: top document, citation present (yes/no),
generation mode, and the first 200 chars of the answer. Then prints
the out-of-scope refusal check and a PASS/FAIL summary.
Exit code 0 = pass (>=8/10 correct + refusal works), 1 = fail.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.generation import answer_question
from app.services.retrieval import get_retriever, reranker_info

# Reuse the question list from the pytest file (single source of truth).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from test_rag import OUT_OF_SCOPE, QUESTIONS  # noqa: E402


def main() -> int:
    retriever = get_retriever()
    print(f"Reranker actually used: {reranker_info()}")
    print(f"Chunks in store: {len(retriever._chunks)}")
    correct = 0
    for i, (question, expected_docs, lang) in enumerate(QUESTIONS, start=1):
        if isinstance(expected_docs, str):
            expected_docs = {expected_docs}
        result = answer_question(question, retriever=retriever)
        top_doc = result["citations"][0]["document_id"] if result["citations"] else None
        ok = top_doc in expected_docs
        correct += ok
        print(f"\n{i}. [{lang}] Q: {question}")
        print(f"   top doc: {top_doc} | expected: {sorted(expected_docs)} | "
              f"citation: {'yes' if result['citations'] else 'no'} | "
              f"mode: {result['generation_mode']} | latency: {result['latency_ms']} ms | "
              f"{'PASS' if ok else 'FAIL'}")
        print(f"   answer: {result['answer'][:200].replace(chr(10), ' ')}...")
    print(f"\nOut-of-scope Q: {OUT_OF_SCOPE}")
    refused = answer_question(OUT_OF_SCOPE, retriever=retriever)
    refusal_ok = refused["refused"] and refused["citations"] == []
    print(f"   refused: {refused['refused']} | citations: {refused['citations']} | "
          f"answer: {refused['answer']} | {'PASS' if refusal_ok else 'FAIL'}")
    passed = correct >= 8 and refusal_ok
    print(f"\nRAG test: {correct}/10 correct, refusal {'OK' if refusal_ok else 'FAILED'} "
          f"-> {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
