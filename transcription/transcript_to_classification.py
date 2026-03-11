"""
Sprint 05 — Bridge: feed Chirp transcripts into the classification pipeline.

Inserts successful transcripts from call_transcripts into raw_feedback
as source='call', so the existing Gemini classification pipeline
(classify_feedback.py) picks them up automatically.

Two modes:
  - Full transcript: send entire text (agent + customer)
  - Customer-only: extract only customer's words using diarization data
    (better for classification — agent's scripted responses add noise)

Usage:
    python transcript_to_classification.py                  # Full transcript mode
    python transcript_to_classification.py --customer-only  # Customer words only
"""

import argparse
from google.cloud import bigquery

PROJECT_ID = "feedback-intel-demo"
bq = bigquery.Client(project=PROJECT_ID)


def feed_full_transcripts():
    """
    Insert full transcripts (agent + customer) into raw_feedback.

    Uses LEFT JOIN to skip transcripts already in raw_feedback (idempotent).
    Filters out failed transcriptions (error_message IS NOT NULL).
    Filters out low-confidence transcripts (< 0.6).
    """
    query = """
    INSERT INTO `feedback.raw_feedback` (id, source, text, customer_id, created_at)
    SELECT
      t.id,
      'call' AS source,
      t.transcript_full AS text,
      t.customer_id,
      t.created_at
    FROM `feedback.call_transcripts` t
    LEFT JOIN `feedback.raw_feedback` r ON t.id = r.id
    WHERE r.id IS NULL
      AND t.error_message IS NULL
      AND (t.confidence_avg > 0.6 OR t.confidence_avg = 0.0)
      -- confidence_avg = 0.0 means Chirp 3 (no word confidence support)
      -- confidence_avg > 0.6 filters bad Chirp 2 transcripts if we ever use it
    """
    job = bq.query(query)
    job.result()
    print(f"Fed {job.num_dml_affected_rows} full transcripts into raw_feedback")
    return job.num_dml_affected_rows


def feed_customer_only_transcripts():
    """
    Insert ONLY customer's words into raw_feedback (using diarization data).

    Why: agent's scripted responses ("Thank you for calling, how can I help")
    add noise to classification. The customer's words are what matter for
    department routing and sentiment analysis.

    Assumes speaker '1' is the agent (first speaker in our generated calls).
    In production, you'd use a smarter heuristic or label mapping.
    """
    query = """
    INSERT INTO `feedback.raw_feedback` (id, source, text, customer_id, created_at)
    SELECT
      t.id,
      'call' AS source,
      (SELECT STRING_AGG(seg.word, ' ' ORDER BY CAST(seg.start_time AS FLOAT64))
       FROM UNNEST(JSON_EXTRACT_ARRAY(t.transcript_segments)) AS raw_seg,
       UNNEST([STRUCT(
         JSON_EXTRACT_SCALAR(raw_seg, '$.word') AS word,
         JSON_EXTRACT_SCALAR(raw_seg, '$.speaker') AS speaker,
         JSON_EXTRACT_SCALAR(raw_seg, '$.start') AS start_time
       )]) AS seg
       WHERE seg.speaker != '1'
      ) AS text,
      t.customer_id,
      t.created_at
    FROM `feedback.call_transcripts` t
    LEFT JOIN `feedback.raw_feedback` r ON t.id = r.id
    WHERE r.id IS NULL
      AND t.error_message IS NULL
      AND (t.confidence_avg > 0.6 OR t.confidence_avg = 0.0)
      -- confidence_avg = 0.0 means Chirp 3 (no word confidence support)
      -- confidence_avg > 0.6 filters bad Chirp 2 transcripts if we ever use it
    """
    job = bq.query(query)
    job.result()
    print(f"Fed {job.num_dml_affected_rows} customer-only transcripts into raw_feedback")
    return job.num_dml_affected_rows


def main():
    parser = argparse.ArgumentParser(
        description="Feed Chirp transcripts into classification pipeline"
    )
    parser.add_argument("--customer-only", action="store_true",
                        help="Extract only customer's words (skip agent speech)")
    args = parser.parse_args()

    if args.customer_only:
        n = feed_customer_only_transcripts()
    else:
        n = feed_full_transcripts()

    if n and n > 0:
        print(f"\nNext step: cd ../classification && python classify_feedback.py")
        print("The classifier will pick up the new 'call' source records automatically.")
    else:
        print("No new transcripts to feed.")


if __name__ == "__main__":
    main()
