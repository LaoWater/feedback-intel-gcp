"""
Sprint 06 — WER (Word Error Rate) evaluation for Chirp transcriptions.

Compares Chirp 3 STT output (from BigQuery call_transcripts) against the
original TTS scripts (from local ground_truth/ JSONs).

This is the one clean evaluation we can do on synthetic data:
  original script text -> TTS -> audio -> Chirp STT -> transcribed text
The ground truth is the original script. The metric is how many words
Chirp got wrong.

WER = (Substitutions + Insertions + Deletions) / Reference Words

Usage:
    python evaluate_wer.py                # Full report
    python evaluate_wer.py --verbose      # Show per-call diffs
    python evaluate_wer.py --export csv   # Export results to CSV
"""

import argparse
import json
import os
import sys
from collections import defaultdict

from jiwer import wer, mer, wil, process_words
from google.cloud import bigquery

# ─── Config ─────────────────────────────────────────────────────────

PROJECT_ID = "feedback-intel-demo"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GROUND_TRUTH_DIR = os.path.join(SCRIPT_DIR, "..", "data", "ground_truth")

bq = bigquery.Client(project=PROJECT_ID)


# ─── Data loading ───────────────────────────────────────────────────

def load_ground_truth() -> dict:
    """
    Load all ground truth JSONs.

    Returns dict: call_id -> {full_text, turns, expected_department, ...}
    """
    ground_truth = {}
    gt_dir = os.path.normpath(GROUND_TRUTH_DIR)

    for filename in os.listdir(gt_dir):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(gt_dir, filename)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ground_truth[data["call_id"]] = data

    return ground_truth


def load_transcripts(call_ids: list[str]) -> dict:
    """
    Query BigQuery for Chirp transcriptions matching the given call IDs.

    Returns dict: call_id -> {transcript_full, speaker_count, duration_seconds, ...}
    """
    # Build parameterized query
    placeholders = ", ".join(f"'{cid}'" for cid in call_ids)
    query = f"""
    SELECT id, transcript_full, speaker_count, duration_seconds,
           confidence_avg, chirp_model, error_message
    FROM `feedback.call_transcripts`
    WHERE id IN ({placeholders})
      AND error_message IS NULL
    """
    rows = bq.query(query).result()
    return {row.id: dict(row) for row in rows}


# ─── Text normalization ────────────────────────────────────────────

def normalize_text(text: str) -> str:
    """
    Normalize text for WER comparison.

    Both reference (ground truth) and hypothesis (Chirp output) get
    the same treatment so we're comparing content, not formatting.

    - Lowercase
    - Strip punctuation (Chirp adds its own punctuation)
    - Collapse whitespace
    - Remove filler tokens like [SaaS Company Name] from ground truth
    """
    import re

    text = text.lower()

    # Remove bracketed placeholders from ground truth scripts
    # e.g. "[SaaS Company Name]" -> ""
    text = re.sub(r"\[.*?\]", "", text)

    # Remove all punctuation except apostrophes (for contractions like "don't")
    text = re.sub(r"[^\w\s']", " ", text)

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


# ─── WER computation ───────────────────────────────────────────────

def compute_wer_for_call(reference: str, hypothesis: str) -> dict:
    """
    Compute WER and related metrics for a single call.

    Returns dict with:
      - wer: Word Error Rate (primary metric)
      - mer: Match Error Rate
      - wil: Word Information Lost
      - ref_words: number of words in reference
      - hyp_words: number of words in hypothesis
      - substitutions, insertions, deletions: edit counts
    """
    ref_norm = normalize_text(reference)
    hyp_norm = normalize_text(hypothesis)

    # jiwer's process_words gives us the detailed alignment
    result = process_words(ref_norm, hyp_norm)

    return {
        "wer": result.wer,
        "mer": mer(ref_norm, hyp_norm),
        "wil": wil(ref_norm, hyp_norm),
        "ref_words": len(ref_norm.split()),
        "hyp_words": len(hyp_norm.split()),
        "substitutions": result.substitutions,
        "insertions": result.insertions,
        "deletions": result.deletions,
        "hits": result.hits,
    }


# ─── Main evaluation ───────────────────────────────────────────────

def run_evaluation(verbose: bool = False) -> list[dict]:
    """
    Run WER evaluation on all calls with ground truth.

    Returns list of per-call results.
    """
    print("Loading ground truth...")
    ground_truth = load_ground_truth()
    print(f"  Found {len(ground_truth)} ground truth files\n")

    print("Querying BigQuery for Chirp transcripts...")
    transcripts = load_transcripts(list(ground_truth.keys()))
    print(f"  Found {len(transcripts)} matching transcripts\n")

    # Find calls with both ground truth and transcription
    matched_ids = set(ground_truth.keys()) & set(transcripts.keys())
    missing = set(ground_truth.keys()) - set(transcripts.keys())

    if missing:
        print(f"  WARNING: {len(missing)} calls have ground truth but no transcript:")
        for cid in sorted(missing):
            print(f"    - {cid}")
        print()

    print(f"Evaluating {len(matched_ids)} calls...\n")

    results = []
    for call_id in sorted(matched_ids):
        gt = ground_truth[call_id]
        tr = transcripts[call_id]

        reference = gt["full_text"]
        hypothesis = tr["transcript_full"]

        metrics = compute_wer_for_call(reference, hypothesis)
        metrics["call_id"] = call_id
        metrics["department"] = gt.get("expected_department", "Unknown")
        metrics["scenario"] = gt.get("scenario", "")
        metrics["duration_seconds"] = tr.get("duration_seconds", 0)
        metrics["speaker_count"] = tr.get("speaker_count", 0)

        results.append(metrics)

        if verbose:
            print(f"  {call_id[:8]}... WER={metrics['wer']:.1%} "
                  f"(S={metrics['substitutions']} I={metrics['insertions']} "
                  f"D={metrics['deletions']} / {metrics['ref_words']} words) "
                  f"— {gt.get('scenario', '')[:50]}")

    return results


def print_report(results: list[dict]):
    """Print a formatted WER evaluation report."""
    if not results:
        print("No results to report.")
        return

    print("=" * 70)
    print("  CHIRP 3 WER EVALUATION REPORT")
    print("=" * 70)

    # ─── Aggregate metrics ────────────────────────────────────────
    total_ref = sum(r["ref_words"] for r in results)
    total_sub = sum(r["substitutions"] for r in results)
    total_ins = sum(r["insertions"] for r in results)
    total_del = sum(r["deletions"] for r in results)
    total_hits = sum(r["hits"] for r in results)

    # Micro-average WER (total errors / total reference words)
    micro_wer = (total_sub + total_ins + total_del) / total_ref if total_ref else 0

    # Macro-average WER (mean of per-call WERs)
    macro_wer = sum(r["wer"] for r in results) / len(results)

    wers = [r["wer"] for r in results]
    min_wer = min(wers)
    max_wer = max(wers)
    median_wer = sorted(wers)[len(wers) // 2]

    print(f"\n  Calls evaluated:     {len(results)}")
    print(f"  Total ref words:     {total_ref:,}")
    print(f"  Total hyp words:     {sum(r['hyp_words'] for r in results):,}")
    print()
    print(f"  Micro-avg WER:       {micro_wer:.2%}  (total errors / total words)")
    print(f"  Macro-avg WER:       {macro_wer:.2%}  (mean of per-call WERs)")
    print(f"  Median WER:          {median_wer:.2%}")
    print(f"  Best call:           {min_wer:.2%}")
    print(f"  Worst call:          {max_wer:.2%}")
    print()
    print(f"  Total substitutions: {total_sub:,}")
    print(f"  Total insertions:    {total_ins:,}")
    print(f"  Total deletions:     {total_del:,}")
    print(f"  Total correct:       {total_hits:,}")

    # ─── Per-department breakdown ─────────────────────────────────
    dept_results = defaultdict(list)
    for r in results:
        dept_results[r["department"]].append(r)

    print(f"\n{'─' * 70}")
    print(f"  WER BY DEPARTMENT")
    print(f"{'─' * 70}")
    print(f"  {'Department':<15} {'Calls':>5} {'Avg WER':>10} {'Min':>8} {'Max':>8}")
    print(f"  {'─'*15} {'─'*5} {'─'*10} {'─'*8} {'─'*8}")

    for dept in sorted(dept_results.keys()):
        dept_wers = [r["wer"] for r in dept_results[dept]]
        print(f"  {dept:<15} {len(dept_wers):>5} {sum(dept_wers)/len(dept_wers):>9.2%} "
              f"{min(dept_wers):>7.2%} {max(dept_wers):>7.2%}")

    # ─── Worst 5 calls ───────────────────────────────────────────
    print(f"\n{'─' * 70}")
    print(f"  TOP 5 WORST CALLS (highest WER)")
    print(f"{'─' * 70}")

    worst = sorted(results, key=lambda r: r["wer"], reverse=True)[:5]
    for r in worst:
        print(f"  WER={r['wer']:.2%}  {r['call_id'][:12]}...  "
              f"({r['department']}) {r['scenario'][:45]}")

    # ─── Best 5 calls ────────────────────────────────────────────
    print(f"\n{'─' * 70}")
    print(f"  TOP 5 BEST CALLS (lowest WER)")
    print(f"{'─' * 70}")

    best = sorted(results, key=lambda r: r["wer"])[:5]
    for r in best:
        print(f"  WER={r['wer']:.2%}  {r['call_id'][:12]}...  "
              f"({r['department']}) {r['scenario'][:45]}")

    # ─── Summary ──────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"  SUMMARY")
    print(f"{'=' * 70}")
    print(f"""
  Pipeline: Ground truth script -> Chirp 3 HD TTS -> WAV audio -> Chirp 3 STT
  WER measures how many words the STT pipeline got wrong.

  Key numbers:
  - {len(results)} calls evaluated, {total_ref:,} total words
  - Micro-average WER: {micro_wer:.2%}
  - This is a TTS->STT round-trip, so WER reflects BOTH synthesis artifacts
    and recognition errors. Real human speech would have different error patterns.
  - Chirp 3 doesn't provide word-level confidence, so WER against ground truth
    is our primary quality metric.
""")


def export_csv(results: list[dict], path: str):
    """Export per-call results to CSV."""
    import csv

    fields = ["call_id", "department", "scenario", "wer", "mer", "wil",
              "ref_words", "hyp_words", "substitutions", "insertions",
              "deletions", "hits", "duration_seconds", "speaker_count"]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    print(f"\nExported {len(results)} rows to {path}")


# ─── CLI ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate Chirp 3 WER against ground truth scripts"
    )
    parser.add_argument("--verbose", action="store_true",
                        help="Show per-call WER during evaluation")
    parser.add_argument("--export", choices=["csv"],
                        help="Export results to file")
    args = parser.parse_args()

    results = run_evaluation(verbose=args.verbose)

    if not results:
        print("No matching calls found. Check ground truth and BigQuery data.")
        sys.exit(1)

    print_report(results)

    if args.export == "csv":
        csv_path = os.path.join(SCRIPT_DIR, "wer_results.csv")
        export_csv(results, csv_path)


if __name__ == "__main__":
    main()
