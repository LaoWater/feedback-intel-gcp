# Apache Beam + Pub/Sub + Dataflow — Concepts & Lessons

> Sprint 08: Turning local scripts into a managed streaming pipeline.
> This doc captures the WHY, the concepts, the gotchas, and the interview-ready takeaways.

---

## Core Concepts (Learn Before You Code)

### Apache Beam vs Dataflow

This is the most common interview confusion. They are NOT the same thing.

| | Apache Beam | Dataflow |
|---|---|---|
| What it is | Open-source programming model | Google Cloud managed service |
| What you write | Pipeline code (Python/Java/Go) | Nothing — it runs your Beam code |
| Analogy | Docker image | Kubernetes cluster |
| Portable? | Yes — runs on Flink, Spark, Dataflow | No — GCP only |

**You write Beam. You run it on Dataflow.**

If you leave GCP tomorrow, your `pipeline.py` runs on Apache Flink or Spark with a flag change. That's the portability promise.

### The Beam Vocabulary

**Pipeline** — The entire job. A directed acyclic graph (DAG) of data transformations.

**PCollection** — "Parallel Collection." The data flowing through the pipeline. Unlike a Python list, it's distributed — chunks live on different workers. You never index into it. You only transform it.

**DoFn** — "Do Function." A user-defined processing step. Takes one element, yields zero or more outputs. This is where your business logic lives (parsing, validating, transforming).

**Transform** — An operation applied to a PCollection. Built-in transforms include `Map`, `Filter`, `GroupByKey`. Custom transforms use `ParDo(YourDoFn())`.

**The pipe operator `|`** — Beam's syntax for chaining transforms:
```python
pipeline | "StepName" >> beam.ParDo(MyDoFn())
```
This is just syntactic sugar. `"StepName"` is a label (shows up in the Dataflow monitoring UI). `>>` applies the transform.

### Runners: Where Your Code Executes

| Runner | Where | Cost | Use case |
|---|---|---|---|
| `DirectRunner` | Your laptop | Free | Development, testing |
| `DataflowRunner` | GCP managed workers | ~$0.056/hr/vCPU | Production |
| `FlinkRunner` | Apache Flink cluster | Depends | Non-GCP production |
| `SparkRunner` | Apache Spark cluster | Depends | Existing Spark infra |

**Key insight:** The runner is a command-line flag, not a code change. Same `pipeline.py`, different `--runner`.

### Streaming vs Batch

| | Batch | Streaming |
|---|---|---|
| Input | Bounded (file, table) | Unbounded (Pub/Sub, Kafka) |
| Runs | Start → process → finish | Runs continuously |
| Pipeline option | `streaming=False` (default) | `streaming=True` |
| When to use | ETL jobs, backfills | Real-time event processing |

Our pipeline is **streaming** — it reads from Pub/Sub continuously, processing each message as it arrives.

### Why Pub/Sub Sits in Front

Without Pub/Sub:
```
API → Pipeline → BigQuery
```
If the pipeline is down, data is lost. If the API sends faster than the pipeline processes, data is lost.

With Pub/Sub:
```
API → Pub/Sub → Pipeline → BigQuery
```

Pub/Sub provides:
- **Buffering** — handles traffic spikes (messages queue, pipeline catches up)
- **Durability** — messages persist until acknowledged (7-day retention by default)
- **Decoupling** — producers don't need to know about consumers
- **Fan-out** — multiple subscriptions can read the same topic (e.g., pipeline + audit log + monitoring)
- **Replay** — seek back to re-process messages (useful for bug fixes)

**Interview one-liner:** "Pub/Sub is the shock absorber between ingestion and processing. It turns a fragile direct connection into a resilient buffered stream."

### How Pub/Sub Differs from Our Existing Setup

We already have `audio-upload-events` — a Pub/Sub topic that fires when audio files land in GCS. That's a **notification** (metadata about what happened).

The new `feedback-raw` topic carries **actual feedback content** (the full message payload). Different purpose:

| | `audio-upload-events` | `feedback-raw` |
|---|---|---|
| Trigger | GCS OBJECT_FINALIZE | Application publishes |
| Payload | File metadata (bucket, name) | Full feedback record (JSON) |
| Consumer | Could trigger transcription | Beam pipeline → BigQuery |
| Pattern | Event notification | Data transport |

---

## GCP Resources Created

| Resource | Name | Purpose |
|---|---|---|
| Pub/Sub Topic | `feedback-raw` | Carries feedback JSON messages |
| Pub/Sub Subscription | `feedback-raw-sub` | Pipeline reads from this |
| GCS Bucket | `gs://feedback-intel-dataflow` | Dataflow temp/staging files (europe-west1) |

Commands used:
```bash
gcloud pubsub topics create feedback-raw
gcloud pubsub subscriptions create feedback-raw-sub --topic=feedback-raw
gcloud storage buckets create gs://feedback-intel-dataflow --location=europe-west1
```

**Note:** The subscription `feedback-raw-sub` is for manual testing/inspection. The Beam pipeline reads from the **topic** directly (it creates its own internal subscription). This is a Beam-specific behavior — it uses `ReadFromPubSub(topic=...)`, not `ReadFromPubSub(subscription=...)`.

---

## Setup & Replication Guide

### Prerequisites

```bash
# Ensure you're authenticated and project is set
gcloud auth login
gcloud config set project feedback-intel-demo
```

### Step 1: Enable Required APIs

```bash
# Dataflow API (if not already enabled)
gcloud services enable dataflow.googleapis.com --project=feedback-intel-demo
```
**Cost:** Free to enable. Dataflow charges only when jobs run.

### Step 2: Create Pub/Sub Resources

```bash
# Topic — the channel where feedback messages are published
gcloud pubsub topics create feedback-raw

# Subscription — for manual inspection/testing (pipeline creates its own)
gcloud pubsub subscriptions create feedback-raw-sub --topic=feedback-raw
```
**Cost:** ~$0.04 per 10 GB of messages. For a demo with <1000 messages: effectively $0.00.

**Verify:**
```bash
gcloud pubsub topics list --filter="name:feedback-raw"
gcloud pubsub subscriptions list --filter="name:feedback-raw-sub"
```

### Step 3: Create Dataflow Staging Bucket

```bash
# Dataflow needs a GCS bucket for temp files and staged pipeline code
gcloud storage buckets create gs://feedback-intel-dataflow --location=europe-west1
```
**Cost:** Storage is ~$0.02/GB/month. Dataflow temp files are cleaned up automatically. Effectively $0.00 for a demo.

**Why europe-west1?** Matches our BigQuery dataset and other buckets. Cross-region data transfer costs money and adds latency.

### Step 4: Grant Dataflow Permissions to Service Account

```bash
# The pipeline SA needs Dataflow Worker role to launch jobs
gcloud projects add-iam-policy-binding feedback-intel-demo --member="serviceAccount:feedback-pipeline@feedback-intel-demo.iam.gserviceaccount.com" --role="roles/dataflow.worker"


# And Dataflow Admin to create/manage jobs
gcloud projects add-iam-policy-binding feedback-intel-demo --member="serviceAccount:feedback-pipeline@feedback-intel-demo.iam.gserviceaccount.com" --role="roles/dataflow.admin"
```
**Note:** Our SA already has BigQuery, Storage, and Pub/Sub roles from Sprint 01. These two are the Dataflow-specific additions.

### Step 5: Install Dependencies

```bash
# In your virtual environment
pip install "apache-beam[gcp]>=2.60.0" "google-cloud-pubsub>=2.23.0"

# Or from the requirements file
pip install -r pipeline/requirements.txt
```
**Note:** `apache-beam[gcp]` is a large install (~200+ MB) — it bundles GCP I/O connectors for Pub/Sub, BigQuery, GCS, etc.

### Step 6: Test the Publisher (Pub/Sub only, no pipeline needed)

```bash
# Publish a single test message
python pipeline/publish_feedback.py --test

# Verify it landed in Pub/Sub (pull from the manual subscription)
gcloud pubsub subscriptions pull feedback-raw-sub --auto-ack --limit=5
```
**Cost:** Free (Pub/Sub free tier covers first 10 GB/month).

### Step 7: Test Locally (DirectRunner, batch mode)

```bash
# Runs 3 test messages (2 valid + 1 invalid) through the full transform chain
# Same DoFns as production — just fed from beam.Create() instead of Pub/Sub
python pipeline/pipeline.py --local
```

You'll see logs showing which messages passed validation and which were rejected. Valid records are written to BigQuery.

```bash
# Or test with a specific JSON message
python pipeline/pipeline.py --local --input '{"id":"custom-test","source":"manual","text":"Testing a custom message","created_at":"2026-03-13T12:00:00Z"}'
```

**Verify in BigQuery:**
```sql
SELECT * FROM feedback.raw_feedback
WHERE id LIKE 'beam-local-%'
ORDER BY created_at DESC
LIMIT 5;
```

**Cost:** $0.00 — DirectRunner is local-only. BigQuery writes are free (streaming inserts).

**Why not streaming locally?** DirectRunner + streaming Pub/Sub I/O has known gRPC issues (see Implementation Notes). The production pattern: test transforms locally in batch, test streaming on Dataflow.

### Step 8: Deploy to Dataflow (Production Runner)

```bash
python pipeline/pipeline.py \
    --runner DataflowRunner \
    --project feedback-intel-demo \
    --region europe-west1 \
    --temp_location gs://feedback-intel-dataflow/temp \
    --staging_location gs://feedback-intel-dataflow/staging \
    --job_name feedback-streaming-pipeline
```

**What happens:**
1. Beam packages your code into a Docker container
2. Uploads it to the staging bucket
3. Dataflow launches worker VMs
4. Workers continuously read from Pub/Sub and write to BigQuery
5. Auto-scales based on message backlog

**Cost:** ~$0.056/hr per vCPU (default: 1 worker, 1 vCPU = ~$1.34/day). **Tear down after testing.**

### Step 9: Verify on Dataflow

```bash
# Check job status
gcloud dataflow jobs list --region=europe-west1 --status=active

# Publish a test message while the job is running
python pipeline/publish_feedback.py --test

# Verify in BigQuery (same query as Step 7)
```

**Monitor in Console:** https://console.cloud.google.com/dataflow/jobs?project=feedback-intel-demo

### Step 10: Tear Down the Dataflow Job

```bash
# List active jobs
gcloud dataflow jobs list --region=europe-west1 --status=active

# Cancel the job (replace JOB_ID with actual ID from above)
gcloud dataflow jobs cancel JOB_ID --region=europe-west1
```

**Important:** Streaming Dataflow jobs run **indefinitely** until cancelled. If you forget to cancel, it charges ~$1.34/day.

### Cleanup (Optional — if you want to remove everything)

```bash
# Delete Pub/Sub resources
gcloud pubsub subscriptions delete feedback-raw-sub
gcloud pubsub topics delete feedback-raw

# Delete staging bucket (and its contents)
gcloud storage rm -r gs://feedback-intel-dataflow

# Remove IAM bindings
gcloud projects remove-iam-policy-binding feedback-intel-demo \
    --member="serviceAccount:feedback-pipeline@feedback-intel-demo.iam.gserviceaccount.com" \
    --role="roles/dataflow.worker"
gcloud projects remove-iam-policy-binding feedback-intel-demo \
    --member="serviceAccount:feedback-pipeline@feedback-intel-demo.iam.gserviceaccount.com" \
    --role="roles/dataflow.admin"
```

---

## Cost Summary

| Resource | Cost | Demo Impact |
|---|---|---|
| Pub/Sub messages | ~$0.04/10 GB | $0.00 (free tier) |
| GCS staging bucket | ~$0.02/GB/month | $0.00 (temp files, cleaned up) |
| Dataflow (streaming) | ~$0.056/hr/vCPU | ~$0.06 for 1 hour of testing |
| BigQuery inserts | Free (streaming inserts) | $0.00 |
| **Total for a demo run** | | **~$0.06** |

**Rule of thumb:** Deploy Dataflow, send a few test messages, verify in BigQuery, tear down. Total cost: pennies.

---

## Pipeline Architecture

```
External Sources (API, Zendesk, surveys)
        │
        ▼
   publish_feedback.py          ← Simulates ingestion service
   (or Cloud Run API)
        │
        ▼
   Pub/Sub: feedback-raw        ← Buffer + decouple
        │
        ▼
   pipeline.py (Apache Beam)    ← Parse → Validate → Format
        │
   ┌────┴────┐
   │         │
   ▼         ▼
BigQuery   Logs                  ← Valid records → BQ, bad → logged
```

### File Structure

```
pipeline/
├── pipeline.py              # Beam streaming pipeline (the core)
├── publish_feedback.py       # Pub/Sub publisher (test + ingestion sim)
└── requirements.txt          # apache-beam[gcp], google-cloud-pubsub
```

---

## Design Decisions (The "Why" Behind the Code)

### Why `CREATE_NEVER` for BigQuery write disposition?
Fail-fast. If the table doesn't exist or the schema changed, we want an immediate error — not a silent table creation with wrong schema. The table was created in Sprint 01 with specific partitioning and clustering. `CREATE_IF_NEEDED` would create a flat table without those optimizations.

### Why `save_main_session=True`?
Dataflow workers are separate VMs. They don't have your local Python environment. This flag serializes your main module (imports, constants like `REQUIRED_FIELDS`) and ships it to workers. Without it: `NameError: name 'REQUIRED_FIELDS' is not defined` on the worker.

### Why separate ParseMessage, ValidateRecord, FormatForBigQuery?
Single Responsibility. Each DoFn does one thing. This makes the pipeline:
- **Testable** — unit test each step independently
- **Debuggable** — Dataflow UI shows throughput per step (bottleneck is visible)
- **Extensible** — add a new step (e.g., PII redaction) without touching others

### Why `topic=` instead of `subscription=` in ReadFromPubSub?
When you pass `topic=`, Beam creates a **temporary subscription** that's cleaned up when the pipeline stops. This avoids subscription management headaches. The `feedback-raw-sub` subscription we created is for manual `gcloud pubsub subscriptions pull` during debugging — it's independent of the pipeline.

### Why not reuse the Cloud Function approach?
The Cloud Function (`ingestion/cloud_function/main.py`) handles **batch CSV uploads** — a file lands, function triggers, rows are inserted. That's event-driven batch processing.

The Beam pipeline handles **real-time individual messages** — each feedback event is processed independently as it arrives. Different patterns for different use cases. In production, you'd have both:
- Cloud Function for bulk imports (CSV uploads, database migrations)
- Beam pipeline for real-time event streams (API webhooks, live feedback)

---

## IAM in Production vs Our Approach

We grant IAM roles one `gcloud` command at a time. That's fine for learning, but terrible at scale. Here's how real teams handle it:

| Approach | Tool | When to use |
|---|---|---|
| Manual CLI | `gcloud projects add-iam-policy-binding` | Learning, one-off exploration |
| Bash script | `gcloud_full_steps.sh` (what we have) | Portfolio projects, small teams |
| Infrastructure-as-code | Terraform / OpenTofu | Production — any team >2 people |
| Policy-as-code | Google Cloud Organization Policies | Enterprise — enforce guardrails org-wide |

**Our approach:** `gcloud_full_steps.sh` captures every IAM grant across all sprints. One script recreates the entire project from scratch. It's version-controlled (git), reviewable, and replicable. Not Terraform-grade, but honest and complete.

**What Terraform adds:** State tracking (knows what exists vs what's declared), drift detection (alerts if someone changes IAM manually), plan/apply workflow (shows what will change before it changes), and modules (reusable infrastructure patterns).

**Interview one-liner:** "For this project, IAM is captured in a single bash script — replicable from scratch. In production, I'd use Terraform for state tracking, drift detection, and PR-reviewed infrastructure changes."

---

## Notebooks — What They Are and When (Not) to Use Them

**What people mean by "notebooks" in GCP:** Vertex AI Workbench — managed Jupyter notebooks running on GCP VMs.

| | Notebooks (Jupyter) | Pipelines (Beam/Dataflow) |
|---|---|---|
| Purpose | Exploration, prototyping, ad-hoc analysis | Production data processing |
| Runs | Interactively (you click cells) | Continuously or on schedule |
| State | In the notebook (lost if VM dies) | Managed by Dataflow (fault-tolerant) |
| Cost model | VM runs while notebook is open | Workers scale with load |
| Versioning | Painful (JSON diffs, output noise) | Normal Python files in git |
| Best for | "Let me explore this data" | "Process every message reliably" |

**Where notebooks fit in our project:**
- Writing and testing the classification prompt? Notebook.
- Exploring WER results and plotting error distributions? Notebook.
- Running the streaming pipeline 24/7? **Never a notebook.**

**The CI/CD confusion:** "Do you use notebooks in your pipeline?" They might mean:
1. **Notebook-based pipelines** (e.g., Papermill, Databricks notebooks) — runs notebooks as pipeline steps. Common in data science teams. Not what we're doing.
2. **Notebooks for development** — write/test pipeline code in a notebook, then extract to `.py` for production. Reasonable workflow.
3. **Notebooks as documentation** — a notebook showing pipeline results with visualizations. Good for stakeholder demos.

**Our answer:** "We develop in Python files directly, not notebooks. The pipeline is a standard `.py` file deployable on Dataflow. If I needed to explore data or prototype a transform, I'd use a Vertex AI Workbench notebook, then move the logic to `pipeline.py` once it works."

**One-liner:** "Notebooks are for exploration, not production. Prototype in notebooks, promote to Python files, deploy on Dataflow. The notebook never runs in prod."

---

## Implementation Notes

### Hiccup: `yield` + `return` in a DoFn

**Warning:** `Using yield and return in the process method of ValidateRecord can lead to unexpected behavior`

Our `ValidateRecord.process()` used `yield record` for valid records and `return` for invalid ones. Beam flags this because `process()` is a Python generator — mixing `yield` and bare `return` in a generator can cause `StopIteration` to fire unexpectedly, silently dropping elements.

**Fix:** Replace `return` with `if/else` — either yield or don't. Never use bare `return` in a DoFn that yields.

```python
# BAD — mixing yield and return
def process(self, record):
    if bad:
        return          # StopIteration risk
    yield record

# GOOD — if/else, no bare return
def process(self, record):
    if bad:
        pass            # don't yield = record filtered out
    else:
        yield record
```

**Lesson:** DoFn.process() is a generator. Treat it like one — control flow with `yield` only, never `return`.

### Hiccup: DirectRunner + Streaming Pub/Sub = gRPC timeout

Running `python pipeline/pipeline.py` (streaming mode with DirectRunner) hangs with:
```
WARNING:root:Waiting for grpc channel to be ready at localhost:XXXXX
```

**Why:** DirectRunner uses the "portable" runner framework for streaming Pub/Sub I/O. This requires spinning up a local gRPC server (the SDK harness). On Windows especially, this often fails to initialize — it's a known limitation.

**The real lesson:** DirectRunner is designed for **batch** testing. Streaming Pub/Sub I/O is built for **DataflowRunner**. This isn't a bug — it's a design boundary.

**The production pattern:**
1. **Test transforms locally** — `--local` flag, uses `beam.Create()` to feed test data through the same DoFns, writes to real BigQuery. Proves your business logic works.
2. **Test streaming on Dataflow** — deploy with `--runner DataflowRunner`, publish via Pub/Sub, verify end-to-end. This is where streaming actually runs.

This is how real teams work: unit test transforms locally, integration test on Dataflow. You don't run a streaming pipeline on your laptop in production.

**Fix:** Added `--local` mode to `pipeline.py`:
```bash
# Local batch test (free, fast, proves transforms work)
python pipeline/pipeline.py --local

# Production streaming (Dataflow workers, costs money)
python pipeline/pipeline.py --runner DataflowRunner ...
```

**Interview one-liner:** "DirectRunner is for batch testing transforms. Streaming Pub/Sub runs on Dataflow. We test locally with beam.Create(), deploy streaming to Dataflow — same DoFns, different source."

### Hiccup: FILE_LOADS vs STREAMING_INSERTS in batch mode

Running `python pipeline/pipeline.py --local` failed with:
```
ValueError: Invalid GCS location: None.
Writing to BigQuery with FILE_LOADS method requires a GCS location...
```

**Why:** Beam has two BigQuery write methods:
| Method | How it works | When Beam uses it |
|---|---|---|
| `FILE_LOADS` | Writes to GCS temp files → bulk loads into BQ | **Default in batch mode** |
| `STREAMING_INSERTS` | Sends rows directly to BQ streaming API | **Default in streaming mode** |

Our local mode is batch (no Pub/Sub), so Beam defaulted to FILE_LOADS — which needs a GCS bucket for temp files. We didn't provide one because we're running locally.

**Fix:** Explicitly set `method=beam.io.WriteToBigQuery.Method.STREAMING_INSERTS` in local mode. This sends rows directly to BigQuery without needing GCS.

**The deeper lesson:** Beam's BigQuery I/O behaves differently in batch vs streaming. In production (Dataflow streaming), it auto-selects STREAMING_INSERTS. In batch, it prefers FILE_LOADS for efficiency (bulk loads are free, streaming inserts cost $0.01/200MB). For local testing, streaming inserts are simpler — no temp bucket needed.

**Interview one-liner:** "Beam's BigQuery write defaults to FILE_LOADS in batch (needs GCS) and STREAMING_INSERTS in streaming. Know which mode you're in."

### Note: `crcmod` warning

`crcmod package not found` — harmless. It's an optional CRC checksum library for GCS transfers. Only matters for large file I/O, not Pub/Sub messages. Ignore it or `pip install crcmod` to silence.

---

## Take-away One-Liners

- "Apache Beam is the code. Dataflow is the runtime. Like Docker and Kubernetes."
- "Pub/Sub is the shock absorber between ingestion and processing."
- "The runner is a CLI flag, not a code change. Same pipeline runs locally or on 100 Dataflow workers."
- "Streaming vs batch is a pipeline option, not an architecture rewrite."
- "We use CREATE_NEVER in BigQuery — fail-fast if the schema is wrong, don't silently create a bad table."
- "save_main_session=True ships your Python globals to Dataflow workers. Without it, remote workers can't see your constants."
- "Cloud Function for batch file uploads, Beam pipeline for real-time event streams. Different tools, same BigQuery destination."
- "ReadFromPubSub with topic= creates a temp subscription. With subscription= you manage it yourself. We use topic= for simplicity."
- "IAM grants are captured in a single bash script — replicable from scratch. In production, Terraform for state tracking and drift detection."
- "Notebooks are for exploration, not production. Prototype in notebooks, promote to .py, deploy on Dataflow."
- "DirectRunner is for batch testing transforms. Streaming Pub/Sub runs on Dataflow. Test locally with beam.Create(), deploy streaming to Dataflow."
