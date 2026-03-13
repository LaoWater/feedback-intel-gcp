# Sprint 08 — Apache Beam + Pub/Sub + Dataflow

## The "Why" (Interview Story)

Right now, everything runs locally or via a Cloud Function that triggers on CSV upload. If someone asks "how does your pipeline run in production?" — we don't have a great answer. This sprint adds a **real streaming pipeline** that runs continuously on managed infrastructure.

The shift: **Cloud Function (event → batch insert)** → **Beam on Dataflow (continuous stream processing)**

## What We're Building

1. **New Pub/Sub topic** `feedback-raw` — the event bus for all feedback
2. **A publisher script** `pipeline/publish_feedback.py` — simulates ingestion (publishes messages)
3. **Apache Beam pipeline** `pipeline/pipeline.py` — reads Pub/Sub, parses, validates, writes to BigQuery
4. **Educational doc** `Apache_Dataflow.MD` — lessons, concepts, gotchas (separate from other MDs)
5. **Local testing** with DirectRunner (free)
6. **Dataflow deployment** (brief — prove it works, then tear down)

## Step-by-Step Plan

### Step 1: Concepts in Apache_Dataflow.MD (before any code)

Start the educational doc with core concepts we'll need:
- Apache Beam vs Dataflow (code vs runtime — like Docker vs Kubernetes)
- PCollection, DoFn, Pipeline — the Beam vocabulary
- DirectRunner vs DataflowRunner
- Streaming vs Batch mode
- Why Pub/Sub sits in front (decoupling, backpressure, replay)

Write this FIRST so we learn before we code.

### Step 2: Create GCP Resources

```
gcloud pubsub topics create feedback-raw
gcloud pubsub subscriptions create feedback-raw-sub --topic=feedback-raw
```

Note: We already have `audio-upload-events` (GCS notifications for audio files). `feedback-raw` is different — it carries actual feedback *content* for stream processing. Document this distinction.

**Cost:** Pub/Sub is ~$0.04/10GB. For a demo, essentially free.

### Step 3: Install Apache Beam

```
pip install apache-beam[gcp]
```

This pulls in Beam + GCP I/O connectors (Pub/Sub, BigQuery).

### Step 4: Write `pipeline/publish_feedback.py`

A small publisher script that:
- Takes a JSON message or reads from a file
- Publishes to `feedback-raw` topic
- Used for testing the pipeline end-to-end

This simulates what a Cloud Run ingestion service would do in production.

### Step 5: Write `pipeline/pipeline.py`

The Beam pipeline with these steps:
1. **ReadFromPubSub** — reads from `feedback-raw` topic
2. **ParseMessage** (DoFn) — decodes bytes → JSON
3. **ValidateRecord** (DoFn) — checks required fields, logs bad records
4. **FormatForBQ** (DoFn) — ensures schema matches `raw_feedback` table
5. **WriteToBigQuery** — appends to `feedback.raw_feedback`

Key design decisions to document:
- `streaming=True` — continuous processing, not batch
- `save_main_session=True` — serializes main module for workers
- `CREATE_NEVER` disposition — table must exist (fail-fast if schema is wrong)
- Dead letter pattern — bad messages logged, not dropped silently

### Step 6: Test Locally with DirectRunner

```bash
# Terminal 1: Run the pipeline locally
python pipeline/pipeline.py --runner DirectRunner

# Terminal 2: Publish a test message
python pipeline/publish_feedback.py --message '{"id":"beam-test-1","source":"manual","text":"Testing beam pipeline","customer_id":"cust_test","created_at":"2026-03-12T12:00:00Z"}'
```

Verify: query BigQuery, see the record. Document any hiccups.

### Step 7: Deploy to Dataflow (brief)

```bash
python pipeline/pipeline.py \
    --runner DataflowRunner \
    --project feedback-intel-demo \
    --region europe-west1 \
    --temp_location gs://feedback-intel-dataflow/temp \
    --staging_location gs://feedback-intel-dataflow/staging \
    --streaming
```

**Cost warning:** Dataflow workers cost ~$0.056/hr per vCPU. Default is 1 worker with 1 vCPU. Budget ~$1-2/hr. Plan to:
1. Deploy
2. Publish a test message
3. Verify in BigQuery
4. Tear down the job immediately

Need to create the staging bucket first:
```
gcloud storage buckets create gs://feedback-intel-dataflow --location=europe-west1
```

### Step 8: Document Everything in Apache_Dataflow.MD

After each step, add lessons to the doc:
- What worked, what didn't
- Gotchas encountered
- Interview one-liners
- The "before vs after" story (Cloud Function → Beam pipeline)

### Step 9: Update Progress Docs

- Add Sprint 08 to `Development_Progress.md` (checklist style)
- Add Sprint 08 to `Documenting_Progress.md` (narrative + hiccups)
- Renumber Sprints 08-10 → 09-11 in both docs

## File Structure After This Sprint

```
pipeline/
├── pipeline.py              # Apache Beam streaming pipeline
├── publish_feedback.py       # Pub/Sub publisher (test/ingestion simulator)
└── requirements.txt          # apache-beam[gcp] pinned
Apache_Dataflow.MD            # Educational doc — concepts + lessons
```

## What This Gives Us for Interviews

**Before:** "We have a Cloud Function that triggers on file upload."
**After:** "We have a streaming pipeline on Dataflow that continuously processes feedback from Pub/Sub. The Cloud Function handles batch CSV ingestion, the Beam pipeline handles real-time events. Both feed into the same BigQuery tables."

Key talking points:
- Beam is portable (DirectRunner locally, DataflowRunner in prod, Flink/Spark if you leave GCP)
- Pub/Sub decouples producers from consumers (multiple subscribers, replay, backpressure)
- Dataflow auto-scales workers based on message backlog
- Streaming vs batch is a pipeline option, not a code rewrite
