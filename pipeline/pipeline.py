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
    # Local testing (free, runs on your laptop)
    python pipeline/pipeline.py

    # Dataflow deployment (costs money — workers run continuously)
    python pipeline/pipeline.py \
        --runner DataflowRunner \
        --project feedback-intel-demo \
        --region europe-west1 \
        --temp_location gs://feedback-intel-dataflow/temp \
        --staging_location gs://feedback-intel-dataflow/staging
"""

import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions, StandardOptions
import json
import logging

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
            record = json.loads(element.decode("utf-8"))
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
            return  # yields nothing — record is filtered out

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


def run():
    # Pipeline options — streaming mode is the key difference from batch
    options = PipelineOptions(
        # save_main_session=True serializes global state (imports, constants)
        # so remote Dataflow workers can access them
        save_main_session=True,
    )

    # Enable streaming mode — the pipeline runs continuously
    options.view_as(StandardOptions).streaming = True

    with beam.Pipeline(options=options) as p:
        # Read raw bytes from Pub/Sub
        # Note: topic= makes Beam create its own subscription
        # This is different from subscription= which reads an existing one
        messages = (
            p
            | "ReadFromPubSub"
            >> beam.io.ReadFromPubSub(topic=TOPIC)
        )

        # Parse, validate, format, write
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
                # WRITE_APPEND: add rows to existing table (don't overwrite)
                write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND,
                # CREATE_NEVER: table must already exist — fail-fast if schema is wrong
                create_disposition=beam.io.BigQueryDisposition.CREATE_NEVER,
            )
        )

    logger.info("Pipeline finished.")


if __name__ == "__main__":
    run()
