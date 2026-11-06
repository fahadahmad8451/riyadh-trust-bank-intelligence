"""Run the Sprint 4 evaluation — 20 questions, local RAGAS-style metrics.

Run from the backend/ directory:
    python ../scripts/run_eval.py [--limit N]

Prints a per-question table (top doc, recall, faithfulness,
relevancy, phrase present, latency) and the aggregates vs the Design
targets, then stores the full report in data/eval_results.json.
Exit code is ALWAYS 0 when the run completes: evaluation is a
measurement, not a gate — a missed target is reported, never hidden
by failing the script. (Use the printed verdict lines to see it.)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.evaluation import METHOD, TARGETS, run_eval


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the 20-question eval (Sprint 4).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Run only the first N questions (default: all 20).")
    args = parser.parse_args()
    print(f"Method: {METHOD}")
    print("Running eval as ADMIN (all departments visible)...")
    report = run_eval(limit=args.limit)
    print(f"\n{'ID':<5}{'Top doc':<28}{'Recall':<7}{'Faith.':<7}{'Relev.':<7}{'Phrase':<7}{'ms':>7}")
    for row in report["questions"]:
        print(f"{row['id']:<5}{(row['top_document'] or '—'):<28}"
              f"{row['context_recall']:<7.2f}{row['faithfulness']:<7.2f}"
              f"{row['answer_relevancy']:<7.2f}"
              f"{'yes' if row['phrase_present'] else 'no':<7}"
              f"{row['latency_ms']:>7.0f}")
    agg = report["aggregates"]
    print("\nAggregates (mean over questions):")
    for name in ("faithfulness", "context_recall", "answer_relevancy"):
        target = TARGETS[name]
        actual = agg[name]
        print(f"  {name:<18} {actual:.4f}  (target >= {target})  "
              f"{'PASS' if actual >= target else 'MISS — reported as-is'}")
    print(f"  top_doc_accuracy   {agg['top_doc_accuracy']:.4f}")
    print(f"  phrase_present     {agg['phrase_present_rate']:.4f}")
    print(f"  refused            {agg['refused_count']}/{report['question_count']}")
    print(f"  latency p50/p95    {agg['latency_ms_p50']:.0f} / "
          f"{agg['latency_ms_p95']:.0f} ms   (run took {report['run_seconds']} s)")
    print(f"\nAll targets met: {report['all_targets_met']}")
    print("Full report stored in data/eval_results.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
