"""
eval.py — run the full test set through the pipeline and score it.

Usage:
    python3 eval.py                  # run all 53 questions, print table
    python3 eval.py --save out.json  # also save raw results

Scoring rules:
    - status match: predicted status == expected status. Exact string
      match, not fuzzy — this is why the pipeline's output schema matters.
    - For ANSWERED / CONTRADICTION questions, we additionally check that
      at least one *verified* citation matches an expected_sections entry
      (a right status with fabricated/irrelevant citations does not count
      as a pass for that half of the check, printed separately).

No prose is read to produce this score. Every number below comes from
comparing structured fields.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import Pipeline

DATA_DIR = Path(__file__).parent.parent / "data"


def load_test_set() -> list[dict]:
    path = DATA_DIR / "test_set.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def section_hit(result_dict: dict, expected_sections: list[str]) -> bool:
    """True if at least one expected section was actually cited AND verified
    by the pipeline (not just retrieved — cited and confirmed).

    test_set.jsonl uses 'file:section' (single colon); chunk_id uses
    'file::section' (double colon) since '::' is the chunker's separator.
    Normalize both to a (file, section) tuple before comparing.
    """
    if not expected_sections:
        return True  # nothing to check (e.g. hard negatives have none)

    def split_chunk_id(chunk_id: str) -> tuple[str, str]:
        file_part, _, section_part = chunk_id.partition("::")
        return file_part, section_part

    def split_expected(ref: str) -> tuple[str, str]:
        file_part, _, section_part = ref.partition(":")
        return file_part, section_part

    verified_cited = {
        split_chunk_id(c["chunk_id"])
        for c in result_dict.get("citations", [])
        if c.get("verified", True) and "chunk_id" in c
    }
    expected = {split_expected(e) for e in expected_sections}

    return bool(verified_cited & expected)


def run_eval(save_path: str | None = None, limit: int | None = None, resume: bool = True):
    test_set = load_test_set()
    if limit:
        test_set = test_set[:limit]

    # Resume support: if save_path already has results, skip questions we
    # already scored so a quota/rate-limit error mid-run doesn't waste the
    # calls you already spent. Re-run the same command to pick up where
    # you left off.
    done_by_id = {}
    if resume and save_path and Path(save_path).exists():
        try:
            existing = json.loads(Path(save_path).read_text())
            done_by_id = {r["id"]: r for r in existing}
            print(f"Resuming: {len(done_by_id)} questions already scored in {save_path}", file=sys.stderr)
        except Exception:
            pass

    pipeline = Pipeline()
    if pipeline.use_mock:
        print("!! WARNING: no GEMINI_API_KEY or ANTHROPIC_API_KEY found — running in MOCK mode.")
        print("!! All results below are meaningless except as a plumbing check.\n")

    results = list(done_by_id.values())
    t0 = time.time()
    for i, q in enumerate(test_set, 1):
        if q["id"] in done_by_id:
            continue
        print(f"[{i}/{len(test_set)}] {q['id']}: {q['question'][:70]}...", file=sys.stderr)
        try:
            r = pipeline.ask(q["question"])
        except Exception as e:
            print(f"  !! error on {q['id']}: {e}", file=sys.stderr)
            print(f"  !! stopping here — re-run the same command to resume from this point.", file=sys.stderr)
            break
        rd = r.to_dict()

        status_correct = rd["status"] == q["expected_status"]
        sec_correct = section_hit(rd, q.get("expected_sections", []))

        results.append({
            "id": q["id"],
            "category": q["category"],
            "question": q["question"],
            "expected_status": q["expected_status"],
            "predicted_status": rd["status"],
            "status_correct": status_correct,
            "section_correct": sec_correct,
            "overall_correct": status_correct and sec_correct,
            "answer": rd["answer"],
            "citations": rd["citations"],
            "top_retrieval_score": rd["top_retrieval_score"],
        })

        # Save after every question, not just at the end, so partial
        # progress survives a crash or a quota error.
        if save_path:
            Path(save_path).write_text(json.dumps(results, indent=2))

    elapsed = time.time() - t0
    print_report(results, elapsed)

    if save_path:
        Path(save_path).write_text(json.dumps(results, indent=2))
        print(f"\nSaved raw results to {save_path}")

    return results


def print_report(results: list[dict], elapsed: float):
    categories = ["hard_negative", "answerable", "contradiction"]

    print("\n" + "=" * 72)
    print("EVAL REPORT")
    print("=" * 72)

    total_correct = sum(r["overall_correct"] for r in results)
    print(f"\nOVERALL: {total_correct}/{len(results)} correct  ({100*total_correct/len(results):.1f}%)")
    print(f"Time: {elapsed:.1f}s for {len(results)} questions\n")

    for cat in categories:
        cat_results = [r for r in results if r["category"] == cat]
        if not cat_results:
            continue
        correct = sum(r["overall_correct"] for r in cat_results)
        status_correct = sum(r["status_correct"] for r in cat_results)
        print(f"{cat:16s}  {correct}/{len(cat_results)} correct  "
              f"(status-only: {status_correct}/{len(cat_results)})")

    print("\n" + "-" * 72)
    print("FAILURES (for debugging):")
    print("-" * 72)
    any_failures = False
    for r in results:
        if not r["overall_correct"]:
            any_failures = True
            reason = []
            if not r["status_correct"]:
                reason.append(f"status: expected {r['expected_status']}, got {r['predicted_status']}")
            if not r["section_correct"]:
                reason.append("citation didn't match expected section")
            print(f"  [{r['id']}] {r['question'][:60]}...")
            print(f"      {'; '.join(reason)}")
    if not any_failures:
        print("  (none)")

    print("\n" + "=" * 72)
    print(f"25/25 THRESHOLD CHECK — hard negatives specifically: "
          f"{sum(r['overall_correct'] for r in results if r['category']=='hard_negative')}/25")
    print("=" * 72)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", type=str, default="eval_results.json", help="Save raw results JSON to this path (also used to resume)")
    parser.add_argument("--limit", type=int, default=None, help="Only run the first N questions (for quick iteration)")
    parser.add_argument("--no-resume", action="store_true", help="Ignore any existing --save file and start fresh")
    args = parser.parse_args()

    run_eval(save_path=args.save, limit=args.limit, resume=not args.no_resume)
