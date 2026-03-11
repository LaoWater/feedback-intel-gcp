"""
Sprint 04 — Gemini classification pipeline.

Pulls unclassified records from raw_feedback, sends each to Gemini
for structured classification, and writes results to enriched_feedback.

Usage:
    python classify_feedback.py               # Run V1 on all unclassified
    python classify_feedback.py --version v2  # Run V2 prompt
    python classify_feedback.py --version v1 --limit 100  # Classify 100 with V1
    python classify_feedback.py --reset       # Wipe enriched_feedback and re-run
"""

import argparse
import json
import time
import sys
from datetime import datetime, timezone

from google import genai
from google.genai import types
from google.cloud import bigquery

from prompts import PROMPT_VERSIONS

# ─── Config ─────────────────────────────────────────────────────────

PROJECT_ID = "feedback-intel-demo"
LOCATION = "europe-west1"
MODEL = "gemini-2.5-flash-lite"
TABLE_ENRICHED = f"{PROJECT_ID}.feedback.enriched_feedback"

BATCH_SIZE = 50          # Records per BQ streaming insert batch
RATE_LIMIT_DELAY = 0.05  # Seconds between Gemini calls (20 RPS ceiling)
MAX_RETRIES = 3          # Retries per record on transient errors

VALID_DEPARTMENTS = {"Product", "Engineering", "UX", "Support"}
VALID_SENTIMENTS = {"positive", "negative", "neutral"}
VALID_TONES = {"frustrated", "satisfied", "confused", "urgent", "casual"}


# ─── Clients ────────────────────────────────────────────────────────

gemini = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
bq = bigquery.Client(project=PROJECT_ID)


# ─── Single-record classification ───────────────────────────────────

def classify_single(text: str, system_prompt: str) -> dict:
    """Send one feedback text to Gemini, return parsed JSON classification."""
    response = gemini.models.generate_content(
        model=MODEL,
        contents=text,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            temperature=0.1,
            max_output_tokens=512,
        ),
    )
    result = json.loads(response.text)

    # Validate and clamp fields
    result["department"] = result.get("department", "Support")
    if result["department"] not in VALID_DEPARTMENTS:
        result["department"] = "Support"

    result["sentiment"] = result.get("sentiment", "neutral")
    if result["sentiment"] not in VALID_SENTIMENTS:
        result["sentiment"] = "neutral"

    result["tone"] = result.get("tone", "casual")
    if result["tone"] not in VALID_TONES:
        result["tone"] = "casual"

    result["key_issues"] = result.get("key_issues", [])[:3]
    result["confidence"] = max(0.0, min(1.0, float(result.get("confidence", 0.5))))

    return result


# ─── Batch processing ───────────────────────────────────────────────

def get_unclassified(limit: int) -> list:
    """Pull records from raw_feedback that aren't yet in enriched_feedback."""
    query = """
    SELECT r.id, r.source, r.text, r.customer_id, r.created_at
    FROM `feedback.raw_feedback` r
    LEFT JOIN `feedback.enriched_feedback` e ON r.id = e.id
    WHERE e.id IS NULL
    LIMIT @limit
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("limit", "INT64", limit)
        ]
    )
    return list(bq.query(query, job_config=job_config).result())


def classify_batch(version: str = "v1", limit: int = 0) -> int:
    """
    Classify unclassified feedback in batches.

    Args:
        version: Prompt version key (v1, v2, v3)
        limit:   Max records to classify (0 = all)

    Returns:
        Total number of records classified.
    """
    system_prompt = PROMPT_VERSIONS[version]
    model_version = f"{MODEL}-{version}"
    fetch_limit = limit if limit > 0 else 10_000

    total_classified = 0
    total_errors = 0

    while True:
        rows = get_unclassified(min(BATCH_SIZE, fetch_limit - total_classified)
                                 if limit > 0 else BATCH_SIZE)
        if not rows:
            break

        enriched = []
        for i, row in enumerate(rows):
            for attempt in range(MAX_RETRIES):
                try:
                    cls = classify_single(row.text, system_prompt)
                    enriched.append({
                        "id": row.id,
                        "source": row.source,
                        "text": row.text,
                        "customer_id": row.customer_id,
                        "created_at": row.created_at.isoformat(),
                        "department": cls["department"],
                        "sentiment": cls["sentiment"],
                        "tone": cls["tone"],
                        "key_issues": cls["key_issues"],
                        "confidence": cls["confidence"],
                        "model_version": model_version,
                    })
                    break
                except Exception as e:
                    if attempt < MAX_RETRIES - 1:
                        wait = 2 ** attempt
                        print(f"  Retry {attempt+1} for {row.id}: {e} (waiting {wait}s)")
                        time.sleep(wait)
                    else:
                        print(f"  FAILED {row.id} after {MAX_RETRIES} attempts: {e}")
                        total_errors += 1

            time.sleep(RATE_LIMIT_DELAY)

            # Progress indicator every 10 records
            if (total_classified + len(enriched)) % 10 == 0:
                print(f"  ... classified {total_classified + len(enriched)} so far")

        # Stream insert to BigQuery
        if enriched:
            errors = bq.insert_rows_json(TABLE_ENRICHED, enriched)
            if errors:
                print(f"  BQ insert errors: {errors[:3]}")
                total_errors += len(errors)
            else:
                total_classified += len(enriched)
                print(f"  Batch done: +{len(enriched)} → {total_classified} total")

        if limit > 0 and total_classified >= limit:
            break

    return total_classified


def reset_enriched():
    """Delete all rows from enriched_feedback (for re-classification)."""
    query = "DELETE FROM `feedback.enriched_feedback` WHERE TRUE"
    bq.query(query).result()
    print("Wiped enriched_feedback table.")


# ─── Main ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Classify feedback with Gemini")
    parser.add_argument("--version", default="v1", choices=["v1", "v2", "v3"],
                        help="Prompt version to use (default: v1)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max records to classify (0 = all)")
    parser.add_argument("--reset", action="store_true",
                        help="Wipe enriched_feedback before classifying")
    args = parser.parse_args()

    print(f"═══ Feedback Classification Pipeline ═══")
    print(f"  Model:   {MODEL}")
    print(f"  Prompt:  {args.version}")
    print(f"  Limit:   {'all' if args.limit == 0 else args.limit}")
    print()

    if args.reset:
        confirm = input("This will DELETE all enriched data. Type 'yes' to confirm: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            return
        reset_enriched()
        print()

    start = time.time()
    total = classify_batch(version=args.version, limit=args.limit)
    elapsed = time.time() - start

    print()
    print(f"═══ Done ═══")
    print(f"  Classified: {total} records")
    print(f"  Time:       {elapsed:.1f}s ({elapsed/max(total,1):.2f}s per record)")
    print(f"  Version:    {MODEL}-{args.version}")


if __name__ == "__main__":
    main()
