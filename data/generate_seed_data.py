"""
Sprint 02 — Generate 2000 realistic customer feedback records using Gemini Flash.

Outputs: data/seed_feedback.csv
Upload to: gs://feedback-intel-raw-data/seed_feedback.csv

Cost estimate: ~40 Gemini Flash calls x 50 records each ≈ $0.50-1.00
"""

import vertexai
from vertexai.generative_models import GenerativeModel
import json, csv, uuid, time, sys
from datetime import datetime, timedelta
import random

# ── Config ───────────────────────────────────────────────────────────
PROJECT_ID = "feedback-intel-demo"
LOCATION = "europe-west1"
MODEL_NAME = "gemini-2.0-flash-001"
BATCH_SIZE = 50
NUM_BATCHES = 40  # 40 x 50 = 2000 records
OUTPUT_FILE = "data/seed_feedback.csv"

# ── Prompt ───────────────────────────────────────────────────────────
PROMPT = """Generate {n} realistic customer feedback entries for a SaaS platform that sells project management and collaboration software.

Mix of: support tickets, app store reviews, and survey responses.
Each entry MUST be a JSON object with exactly these fields:
- "source": one of "ticket", "review", or "survey"
- "text": realistic customer message (2-5 sentences, varied writing styles)
- "customer_id": random alphanumeric string like "cust_a7b3x9"

Distribution requirements:
- ~30% frustrated/negative — bugs, slow performance, billing issues, data loss, crashes, downtime
- ~40% neutral — feature requests, how-to questions, migration help, integration questions
- ~30% positive — praising specific features, recommending to others, noting improvements

Topic variety (spread across these):
- App crashes, slow loading, UI bugs, mobile issues
- Billing disputes, subscription confusion, refund requests
- Feature requests: dark mode, better search, API access, integrations
- Onboarding confusion, documentation gaps
- Praise for customer support, new features, reliability
- Data export issues, permission problems, team management
- Notification overload, email integration issues

IMPORTANT: Each entry must feel like it was written by a different person with different writing styles. Some short and blunt, some detailed and polite, some frustrated and caps-heavy.

Return ONLY a valid JSON array. No markdown, no explanation, no code fences."""


def generate_batch(model, batch_num, n=BATCH_SIZE):
    """Generate a single batch of feedback records via Gemini."""
    response = model.generate_content(
        PROMPT.format(n=n),
        generation_config={"temperature": 1.0, "max_output_tokens": 8192},
    )
    text = response.text.strip()

    # Strip markdown code fences if Gemini wraps the output
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]

    try:
        records = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  [WARN] Batch {batch_num} JSON parse failed: {e}")
        print(f"  First 200 chars: {text[:200]}")
        return []

    # Validate each record has required fields
    valid = []
    for r in records:
        if all(k in r for k in ("source", "text", "customer_id")):
            if r["source"] in ("ticket", "review", "survey"):
                valid.append(r)

    if len(valid) < len(records):
        print(f"  [WARN] Batch {batch_num}: {len(records) - len(valid)} invalid records dropped")

    return valid


def main():
    print(f"=== Seed Data Generator ===")
    print(f"Target: {NUM_BATCHES * BATCH_SIZE} records in {NUM_BATCHES} batches")
    print(f"Model: {MODEL_NAME} @ {LOCATION}")
    print(f"Output: {OUTPUT_FILE}")
    print()

    vertexai.init(project=PROJECT_ID, location=LOCATION)
    model = GenerativeModel(MODEL_NAME)

    all_records = []
    failed_batches = 0

    for i in range(NUM_BATCHES):
        try:
            batch = generate_batch(model, i + 1)

            if not batch:
                failed_batches += 1
                print(f"  Batch {i+1}/{NUM_BATCHES} — EMPTY (will retry)")
                time.sleep(2)
                batch = generate_batch(model, i + 1)  # one retry

            # Add ID and timestamp to each record
            for record in batch:
                record["id"] = str(uuid.uuid4())
                record["created_at"] = (
                    datetime.now() - timedelta(days=random.randint(0, 90))
                ).isoformat()

            all_records.extend(batch)
            print(f"  Batch {i+1}/{NUM_BATCHES} — got {len(batch)} — total: {len(all_records)}")

            # Small delay to avoid rate limits
            if i < NUM_BATCHES - 1:
                time.sleep(0.5)

        except Exception as e:
            failed_batches += 1
            print(f"  Batch {i+1}/{NUM_BATCHES} — ERROR: {e}")
            time.sleep(3)

    # Write CSV
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["id", "source", "text", "customer_id", "created_at"]
        )
        writer.writeheader()
        writer.writerows(all_records)

    # Summary
    print(f"\n=== Done ===")
    print(f"Total records: {len(all_records)}")
    print(f"Failed batches: {failed_batches}")

    # Source distribution
    from collections import Counter
    source_counts = Counter(r["source"] for r in all_records)
    print(f"Distribution: {dict(source_counts)}")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
