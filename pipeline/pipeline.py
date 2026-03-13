"""
Sprint 08 — Apache Beam Streaming Pipeline.

Reads feedback messages from Pub/Sub, validates, and writes to BigQuery.

Architecture:
    Pub/Sub (feedback-raw)
        │
        ▼
    ParseMessage (DoFn)     — bytes → JSON dict
        │
        ▼
    ValidateRecord (DoFn)   — checks required fields, routes bad records
        │
        ├─ valid ──────────▶ FormatForBigQuery (DoFn) → WriteToBigQuery
        │
        └─ invalid ────────▶ LogBadRecord (DoFn) → print/log

Usage:
    # Local test (batch mode — proves transforms work, free)
    python pipeline/pipeline.py --local

    # Local test with custom JSON input
    python pipeline/pipeline.py --local --input '{"id":"x","source":"manual","text":"test","created_at":"2026-03-13T12:00:00Z"}'

    # Dataflow deployment (streaming mode — costs money, runs continuously)
    python pipeline/pipeline.py \
        --runner DataflowRunner \
        --project feedback-intel-demo \
        --region europe-west1 \
        --temp_location gs://feedback-intel-dataflow/temp \
        --staging_location gs://feedback-intel-dataflow/staging
"""

import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions, StandardOptions
import argparse
import json
import logging
import uuid
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = "feedback-intel-demo"
TOPIC = f"projects/{PROJECT_ID}/topics/feedback-raw"
TABLE = f"{PROJECT_ID}:feedback.raw_feedback"

# Fields that MUST exist for a record to be valid
REQUIRED_FIELDS = ["id", "source", "text", "created_at"]

# BigQuery schema for raw_feedback — must match exactly
TABLE_SCHEMA = {
    "fields": [
        {"name": "id", "type": "STRING", "mode": "REQUIRED"},
        {"name": "source", "type": "STRING", "mode": "REQUIRED"},
        {"name": "text", "type": "STRING", "mode": "REQUIRED"},
        {"name": "customer_id", "type": "STRING", "mode": "NULLABLE"},
        {"name": "created_at", "type": "TIMESTAMP", "mode": "REQUIRED"},
        {"name": "metadata", "type": "JSON", "mode": "NULLABLE"},
    ]
}


class ParseMessage(beam.DoFn):
    """Decode Pub/Sub message bytes into a Python dict.

    WHY a DoFn and not a simple Map?
    - DoFn lets us yield zero outputs (skip unparseable messages)
    - DoFn gives us access to logging and metrics
    - In production, you'd add dead-letter queue logic here
    """

    def process(self, element):
        try:
            # Handle both bytes (from Pub/Sub) and str (from local test)
            if isinstance(element, bytes):
                record = json.loads(element.decode("utf-8"))
            else:
                record = json.loads(element) if isinstance(element, str) else element
            yield record
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(f"Failed to parse message: {e}")
            # In production: publish to a dead-letter topic instead of dropping


class ValidateRecord(beam.DoFn):
    """Check that required fields exist.

    WHY validate in the pipeline and not in the publisher?
    - Defense in depth. Publishers can be buggy, external, or malicious.
    - The pipeline is the last gate before BigQuery.
    - Bad records should be logged, not silently dropped.
    """

    def process(self, record):
        missing = [f for f in REQUIRED_FIELDS if f not in record or not record[f]]
        if missing:
            logger.warning(
                f"Rejected record {record.get('id', '?')}: missing {missing}"
            )
            # Don't yield — record is filtered out
        else:
            yield record


class FormatForBigQuery(beam.DoFn):
    """Shape the record to match the BigQuery table schema.

    WHY a separate step?
    - Pub/Sub messages may have extra fields (metadata as dict vs JSON string)
    - BigQuery JSON columns need string serialization
    - Keeps validation and formatting concerns separate
    """

    def process(self, record):
        row = {
            "id": record["id"],
            "source": record["source"],
            "text": record["text"],
            "customer_id": record.get("customer_id"),
            "created_at": record["created_at"],
            "metadata": json.dumps(record.get("metadata", {})),
        }
        yield row


def build_test_messages():
    """Generate test messages for local pipeline runs."""
    return [
        json.dumps({
            "id": f"beam-local-{uuid.uuid4().hex[:8]}",
            "source": "manual",
            "text": "The checkout page throws a 500 error when applying discount codes.",
            "customer_id": "cust_test_001",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {"test": True, "sprint": "08-beam-pipeline"},
        }),
        json.dumps({
            "id": f"beam-local-{uuid.uuid4().hex[:8]}",
            "source": "review",
            "text": "Love the new dashboard design, much faster than before!",
            "customer_id": "cust_test_002",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {"test": True},
        }),
        # Invalid record — missing 'text' field, should be rejected
        json.dumps({
            "id": f"beam-local-{uuid.uuid4().hex[:8]}",
            "source": "survey",
            "customer_id": "cust_test_003",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }),
    ]


def run():
    # Parse our custom args separately from Beam's pipeline args
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--local", action="store_true",
                        help="Run locally in batch mode (bypasses Pub/Sub)")
    parser.add_argument("--input", type=str,
                        help="JSON string to process in local mode")
    known_args, pipeline_args = parser.parse_known_args()

    options = PipelineOptions(
        pipeline_args,
        save_main_session=True,
    )

    if known_args.local:
        # ============================================================
        # LOCAL MODE — batch, no Pub/Sub, no streaming
        # ============================================================
        # Tests that your DoFns work correctly.
        # Same transforms, different source (in-memory vs Pub/Sub).
        # This is the standard pattern: test transforms locally,
        # deploy the full pipeline on Dataflow.
        # ============================================================
        logger.info("Running in LOCAL mode (batch, DirectRunner)")

        if known_args.input:
            test_data = [known_args.input]
        else:
            test_data = build_test_messages()

        logger.info(f"Processing {len(test_data)} test messages...")

        with beam.Pipeline(options=options) as p:
            results = (
                p
                | "CreateTestData"
                >> beam.Create(test_data)

                | "ParseJSON"
                >> beam.ParDo(ParseMessage())

                | "ValidateRecord"
                >> beam.ParDo(ValidateRecord())

                | "FormatForBigQuery"
                >> beam.ParDo(FormatForBigQuery())
            )

            # Write to BigQuery (same as production)
            # NOTE: In batch mode, Beam defaults to FILE_LOADS (write to GCS,
            # then bulk load). That requires a GCS temp bucket. We force
            # STREAMING_INSERTS here to avoid needing a temp location for
            # local testing. In streaming mode (Dataflow), Beam uses
            # STREAMING_INSERTS automatically.
            results | "WriteToBigQuery" >> beam.io.WriteToBigQuery(
                table=TABLE,
                schema=TABLE_SCHEMA,
                write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND,
                create_disposition=beam.io.BigQueryDisposition.CREATE_NEVER,
                method=beam.io.WriteToBigQuery.Method.STREAMING_INSERTS,
            )

            # Also log to console so you can see what's happening
            results | "LogResults" >> beam.Map(
                lambda row: logger.info(f"  → BQ: {row['id']} ({row['source']}) - {row['text'][:60]}...")
            )

        logger.info("Local pipeline finished. Check BigQuery for results.")

    else:
        # ============================================================
        # STREAMING MODE — reads from Pub/Sub continuously
        # ============================================================
        # This is the production path. Runs on DirectRunner (dev) or
        # DataflowRunner (prod). Processes messages as they arrive.
        #
        # NOTE: DirectRunner streaming with Pub/Sub has known issues
        # (gRPC channel timeouts). Use DataflowRunner for real streaming.
        # ============================================================
        options.view_as(StandardOptions).streaming = True
        logger.info("Running in STREAMING mode (Pub/Sub → BigQuery)")

        with beam.Pipeline(options=options) as p:
            messages = (
                p
                | "ReadFromPubSub"
                >> beam.io.ReadFromPubSub(topic=TOPIC)
            )

            (
                messages
                | "ParseJSON"
                >> beam.ParDo(ParseMessage())

                | "ValidateRecord"
                >> beam.ParDo(ValidateRecord())

                | "FormatForBigQuery"
                >> beam.ParDo(FormatForBigQuery())

                | "WriteToBigQuery"
                >> beam.io.WriteToBigQuery(
                    table=TABLE,
                    schema=TABLE_SCHEMA,
                    write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND,
                    create_disposition=beam.io.BigQueryDisposition.CREATE_NEVER,
                )
            )

        logger.info("Pipeline finished.")


if __name__ == "__main__":
    run()
