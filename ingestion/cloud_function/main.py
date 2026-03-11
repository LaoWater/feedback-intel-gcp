"""
Sprint 03 — Cloud Function: CSV upload → BigQuery ingestion.

Triggers on OBJECT_FINALIZE in gs://feedback-intel-raw-data/.
Reads the uploaded CSV, validates rows, and streams them into
feedback.raw_feedback via BigQuery streaming inserts.

Deployment:
  gcloud functions deploy process-feedback-upload ...
  (see Sprint 03 in Development_Progress.md for full command)
"""

import functions_framework
from google.cloud import bigquery, storage
from cloudevents.http import CloudEvent
import csv, io, json, logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = "feedback-intel-demo"
TABLE_ID = f"{PROJECT_ID}.feedback.raw_feedback"
REQUIRED_FIELDS = {"id", "source", "text", "customer_id", "created_at"}
VALID_SOURCES = {"ticket", "review", "survey"}
# BigQuery streaming insert limit is 10,000 rows per request
INSERT_BATCH_SIZE = 500


@functions_framework.cloud_event
def process_upload(cloud_event: CloudEvent):
    """Triggered when a file is uploaded to the feedback-intel-raw-data bucket."""
    data = cloud_event.data
    bucket_name = data["bucket"]
    file_name = data["name"]

    # Only process CSV files
    if not file_name.lower().endswith(".csv"):
        logger.info(f"Skipping non-CSV file: {file_name}")
        return

    logger.info(f"Processing {file_name} from {bucket_name}")

    # Download file content
    storage_client = storage.Client()
    blob = storage_client.bucket(bucket_name).blob(file_name)
    content = blob.download_as_text(encoding="utf-8")

    # Strip BOM if present (common with Excel / PowerShell-generated CSVs)
    if content.startswith("\ufeff"):
        content = content[1:]

    # Parse CSV
    reader = csv.DictReader(io.StringIO(content))
    rows = []
    skipped = 0

    for line_num, row in enumerate(reader, start=2):  # start=2 because line 1 is header
        # Validate required fields exist and aren't empty
        if not all(row.get(f) for f in ("id", "source", "text", "created_at")):
            skipped += 1
            continue

        # Validate source is one of the expected values
        if row["source"] not in VALID_SOURCES:
            skipped += 1
            continue

        rows.append({
            "id": row["id"],
            "source": row["source"],
            "text": row["text"],
            "customer_id": row.get("customer_id") or None,
            "created_at": row["created_at"],
            "metadata": json.dumps({"source_file": file_name}),
        })

    if not rows:
        logger.warning(f"No valid rows found in {file_name}")
        return

    # Insert into BigQuery in batches
    bq_client = bigquery.Client(project=PROJECT_ID)
    total_errors = []

    for i in range(0, len(rows), INSERT_BATCH_SIZE):
        batch = rows[i : i + INSERT_BATCH_SIZE]
        errors = bq_client.insert_rows_json(TABLE_ID, batch)
        if errors:
            total_errors.extend(errors)
            logger.error(f"Batch {i // INSERT_BATCH_SIZE + 1} errors: {errors[:3]}")

    if total_errors:
        logger.error(
            f"Completed with {len(total_errors)} errors out of {len(rows)} rows"
        )
        raise RuntimeError(
            f"BigQuery insert had {len(total_errors)} errors. First: {total_errors[0]}"
        )

    logger.info(
        f"Loaded {len(rows)} rows from {file_name} "
        f"(skipped {skipped} invalid rows)"
    )
