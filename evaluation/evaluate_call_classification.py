"""
Sprint 06 — Call classification accuracy check.

Compares Gemini's classification of call transcripts (from enriched_feedback)
against the ground truth labels set at generation time (from ground_truth/ JSONs).

Why this works despite synthetic data:
  The ground truth labels (expected_department, expected_sentiment) were set
  BEFORE the script text was generated. The text then went through:
    script -> TTS -> audio -> Chirp STT -> transcription -> Gemini classification
  The STT step introduces real noise (word errors, punctuation changes, disfluencies).
  This test checks whether the full pipeline preserves the intended signal.

Known taxonomy mismatch:
  Generation used 6 departments: Engineering, Product, UX, Support, Billing, Logistics
  Classifier uses 4 departments:  Engineering, Product, UX, Support
  Billing and Logistics (10/35 calls) get mapped to Support for comparison.
  This mismatch is a real-world finding — documented, not hidden.

  Generation used 4 sentiments: positive, negative, neutral, mixed
  Classifier uses 3 sentiments:  positive, negative, neutral
  "mixed" calls (7/35) are excluded from sentiment accuracy.

Usage:
    python evaluate_call_classification.py            # Full report
    python evaluate_call_classification.py --verbose   # Show per-call comparisons
"""

import argparse
import json
import os
import sys
from collections import defaultdict

from google.cloud import bigquery

# ─── Config ─────────────────────────────────────────────────────────

PROJECT_ID = "feedback-intel-demo"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GROUND_TRUTH_DIR = os.path.join(SCRIPT_DIR, "..", "data", "ground_truth")

# Taxonomy mapping: generation labels -> classifier labels
# The generator used 6 departments, the classifier only knows 4.
# Billing and Logistics both route to Support (closest match).
DEPARTMENT_MAP = {
    "Engineering": "Engineering",
    "Product": "Product",
    "UX": "UX",
    "Support": "Support",
    "Billing": "Support",      # billing questions -> Support
    "Logistics": "Support",    # shipping/delivery -> Support
}

bq = bigquery.Client(project=PROJECT_ID)


# ─── Data loading ───────────────────────────────────────────────────

def load_ground_truth() -> dict:
    """Load all ground truth JSONs. Returns dict: call_id -> data."""
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


def load_classifications(call_ids: list[str]) -> dict:
    """
    Query enriched_feedback for call classifications.

    Returns dict: call_id -> {department, sentiment, tone, confidence, ...}
    """
    placeholders = ", ".join(f"'{cid}'" for cid in call_ids)
    query = f"""
    SELECT id, department, sentiment, tone, confidence, model_version
    FROM `feedback.enriched_feedback`
    WHERE id IN ({placeholders})
      AND source = 'call'
    """
    rows = bq.query(query).result()
    return {row.id: dict(row) for row in rows}


# ─── Evaluation ─────────────────────────────────────────────────────

def evaluate(verbose: bool = False) -> dict:
    """
    Compare call classifications against ground truth labels.

    Returns evaluation results dict.
    """
    print("Loading ground truth...")
    ground_truth = load_ground_truth()
    print(f"  Found {len(ground_truth)} ground truth files\n")

    print("Querying BigQuery for call classifications...")
    classifications = load_classifications(list(ground_truth.keys()))
    print(f"  Found {len(classifications)} classified calls\n")

    matched_ids = set(ground_truth.keys()) & set(classifications.keys())
    missing = set(ground_truth.keys()) - set(classifications.keys())

    if missing:
        print(f"  WARNING: {len(missing)} calls have ground truth but no classification")
        print()

    # ─── Department accuracy ──────────────────────────────────────
    dept_correct = 0
    dept_total = 0
    dept_confusion = defaultdict(lambda: defaultdict(int))  # expected -> predicted -> count
    dept_details = []

    # Track which calls had their department mapped
    mapped_calls = []

    for call_id in sorted(matched_ids):
        gt = ground_truth[call_id]
        cl = classifications[call_id]

        expected_dept_raw = gt.get("expected_department", "Unknown")
        expected_dept = DEPARTMENT_MAP.get(expected_dept_raw, "Support")
        predicted_dept = cl["department"]

        was_mapped = expected_dept_raw != expected_dept
        correct = expected_dept == predicted_dept

        dept_confusion[expected_dept][predicted_dept] += 1
        dept_total += 1
        if correct:
            dept_correct += 1

        if was_mapped:
            mapped_calls.append({
                "call_id": call_id,
                "original_dept": expected_dept_raw,
                "mapped_to": expected_dept,
                "predicted": predicted_dept,
                "correct": correct,
            })

        dept_details.append({
            "call_id": call_id,
            "expected_raw": expected_dept_raw,
            "expected_mapped": expected_dept,
            "predicted": predicted_dept,
            "correct": correct,
            "scenario": gt.get("scenario", ""),
        })

        if verbose:
            marker = "OK" if correct else "MISS"
            mapped_note = f" (mapped from {expected_dept_raw})" if was_mapped else ""
            print(f"  [{marker}] {call_id[:8]}...  "
                  f"expected={expected_dept}{mapped_note}  "
                  f"predicted={predicted_dept}  "
                  f"— {gt.get('scenario', '')[:40]}")

    # ─── Sentiment accuracy (exclude "mixed") ────────────────────
    sent_correct = 0
    sent_total = 0
    sent_skipped = 0
    sent_confusion = defaultdict(lambda: defaultdict(int))

    for call_id in sorted(matched_ids):
        gt = ground_truth[call_id]
        cl = classifications[call_id]

        expected_sent = gt.get("expected_sentiment", "neutral")
        predicted_sent = cl["sentiment"]

        if expected_sent == "mixed":
            sent_skipped += 1
            continue

        sent_confusion[expected_sent][predicted_sent] += 1
        sent_total += 1
        if expected_sent == predicted_sent:
            sent_correct += 1

    return {
        "dept_correct": dept_correct,
        "dept_total": dept_total,
        "dept_accuracy": dept_correct / dept_total if dept_total else 0,
        "dept_confusion": dict(dept_confusion),
        "dept_details": dept_details,
        "mapped_calls": mapped_calls,
        "sent_correct": sent_correct,
        "sent_total": sent_total,
        "sent_skipped": sent_skipped,
        "sent_accuracy": sent_correct / sent_total if sent_total else 0,
        "sent_confusion": dict(sent_confusion),
        "total_matched": len(matched_ids),
    }


def print_report(results: dict):
    """Print a formatted classification evaluation report."""
    print("\n" + "=" * 70)
    print("  CALL CLASSIFICATION EVALUATION REPORT")
    print("=" * 70)

    # ─── Department accuracy ──────────────────────────────────────
    print(f"\n  DEPARTMENT CLASSIFICATION")
    print(f"  {'─' * 50}")
    print(f"  Calls evaluated:   {results['dept_total']}")
    print(f"  Correct:           {results['dept_correct']}")
    print(f"  Accuracy:          {results['dept_accuracy']:.1%}")

    # Taxonomy mismatch info
    mapped = results["mapped_calls"]
    if mapped:
        mapped_correct = sum(1 for m in mapped if m["correct"])
        print(f"\n  Taxonomy mismatch: {len(mapped)} calls had departments the")
        print(f"  classifier doesn't know (Billing, Logistics -> Support)")
        print(f"  Of those, {mapped_correct}/{len(mapped)} correctly classified as Support")

    # Confusion matrix
    print(f"\n  Confusion Matrix (rows=expected, cols=predicted):")
    all_depts = sorted(set(
        list(results["dept_confusion"].keys()) +
        [d for row in results["dept_confusion"].values() for d in row.keys()]
    ))

    print(f"  {'':>15}", end="")
    for d in all_depts:
        print(f" {d:>12}", end="")
    print()

    for expected in all_depts:
        print(f"  {expected:>15}", end="")
        for predicted in all_depts:
            count = results["dept_confusion"].get(expected, {}).get(predicted, 0)
            cell = str(count) if count > 0 else "."
            print(f" {cell:>12}", end="")
        print()

    # ─── Sentiment accuracy ───────────────────────────────────────
    print(f"\n  SENTIMENT CLASSIFICATION")
    print(f"  {'─' * 50}")
    print(f"  Calls evaluated:   {results['sent_total']}")
    print(f"  Skipped ('mixed'): {results['sent_skipped']}")
    print(f"  Correct:           {results['sent_correct']}")
    print(f"  Accuracy:          {results['sent_accuracy']:.1%}")

    # Sentiment confusion matrix
    print(f"\n  Confusion Matrix (rows=expected, cols=predicted):")
    all_sents = sorted(set(
        list(results["sent_confusion"].keys()) +
        [s for row in results["sent_confusion"].values() for s in row.keys()]
    ))

    print(f"  {'':>15}", end="")
    for s in all_sents:
        print(f" {s:>12}", end="")
    print()

    for expected in all_sents:
        print(f"  {expected:>15}", end="")
        for predicted in all_sents:
            count = results["sent_confusion"].get(expected, {}).get(predicted, 0)
            cell = str(count) if count > 0 else "."
            print(f" {cell:>12}", end="")
        print()

    # ─── Misclassifications detail ────────────────────────────────
    misses = [d for d in results["dept_details"] if not d["correct"]]
    if misses:
        print(f"\n  DEPARTMENT MISCLASSIFICATIONS ({len(misses)})")
        print(f"  {'─' * 50}")
        for m in misses:
            mapped_note = ""
            if m["expected_raw"] != m["expected_mapped"]:
                mapped_note = f" (originally '{m['expected_raw']}')"
            print(f"  {m['call_id'][:12]}...  "
                  f"expected={m['expected_mapped']}{mapped_note}  "
                  f"got={m['predicted']}  "
                  f"— {m['scenario'][:40]}")

    # ─── Interview summary ────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"  INTERVIEW SUMMARY")
    print(f"{'=' * 70}")
    print(f"""
  Pipeline tested: script -> TTS -> Chirp STT -> Gemini classification
  This checks whether signal survives the full pipeline, not just the classifier.

  Key findings:
  - Department accuracy: {results['dept_accuracy']:.1%} ({results['dept_correct']}/{results['dept_total']})
  - Sentiment accuracy: {results['sent_accuracy']:.1%} ({results['sent_correct']}/{results['sent_total']}, excluding 'mixed')

  Taxonomy mismatch (realistic finding):
  - Data was generated with 6 departments (Engineering, Product, UX, Support, Billing, Logistics)
  - Classifier only knows 4 (Billing -> Support, Logistics -> Support)
  - In production: either expand classifier taxonomy or maintain explicit mapping

  Limitations:
  - Synthetic data: scripts were designed to be classifiable
  - TTS audio is cleaner than real human speech (no background noise, accents)
  - Real evaluation requires labeled production data
  - Text feedback classification can't be meaningfully evaluated (circular)
""")


# ─── CLI ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate call classification accuracy against ground truth"
    )
    parser.add_argument("--verbose", action="store_true",
                        help="Show per-call comparison during evaluation")
    args = parser.parse_args()

    results = evaluate(verbose=args.verbose)

    if results["total_matched"] == 0:
        print("No matching calls found. Check ground truth and BigQuery data.")
        sys.exit(1)

    print_report(results)


if __name__ == "__main__":
    main()
