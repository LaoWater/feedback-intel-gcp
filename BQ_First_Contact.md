# BigQuery First Contact

> A hands-on guide for developers coming from PostgreSQL/MySQL/Oracle.
> Built around the **feedback-intel-demo** project on GCP.

---

## 1. Why BigQuery Feels Alien (And Why That's The Point)

If you've spent years with PostgreSQL, MySQL, or Oracle, BigQuery will feel wrong at first. No server to SSH into. No `pg_dump`. No connection string with a port number. That's by design.

### Traditional Databases vs BigQuery — The Mental Model Shift

**PostgreSQL / MySQL / Oracle** are like owning a car. You pick the engine size (CPU/RAM), you maintain it (vacuuming, index rebuilding, replication), you pay whether it's parked or driving. You get full control: triggers, stored procedures, cron jobs via `pg_cron`, foreign keys enforced at write time, row-level locks, sequences, custom extensions. The database is a *living process* running on a machine you (or your cloud provider) manage.

**BigQuery** is like calling a taxi fleet. You don't own anything. You describe what you want (SQL), Google throws thousands of machines at it for 2-30 seconds, gives you results, and the machines vanish. You pay per query (bytes scanned) + storage. There is no server. There is no connection pool. There is no `max_connections` to tune.

### What You Lose (and what replaces it)

| Feature | PostgreSQL/MySQL/Oracle | BigQuery |
|---|---|---|
| **Triggers** | `CREATE TRIGGER` fires on INSERT/UPDATE/DELETE | Doesn't exist. Use **Pub/Sub + Cloud Functions** instead — decouple the event from the reaction |
| **Cron jobs** | `pg_cron`, MySQL Event Scheduler, Oracle DBMS_SCHEDULER | **Cloud Scheduler** → hits a Cloud Function or **Scheduled Queries** (built into BQ) |
| **Stored procedures** | PL/pgSQL, PL/SQL, full procedural logic | BigQuery has **scripting** (IF/ELSE, LOOP, DECLARE) and **procedures**, but they're for ETL orchestration, not application logic |
| **Row-level updates** | `UPDATE users SET name='x' WHERE id=5` — instant, single row | Technically works but *extremely* inefficient. BQ rewrites the entire partition. Design for append-only patterns |
| **Indexes** | B-tree, GIN, GiST — you create them manually | Don't exist. **Partitioning + clustering** replace them (more on this below) |
| **Foreign keys** | Enforced referential integrity | Not enforced. You declare them as hints for the query optimizer, but BQ won't reject bad data |
| **Sequences / AUTO_INCREMENT** | `SERIAL`, `AUTO_INCREMENT`, Oracle sequences | Use `GENERATE_UUID()` or bring your own IDs |
| **Transactions** | Full ACID with `BEGIN/COMMIT/ROLLBACK` | Multi-statement transactions exist but with limits. Not designed for OLTP workloads |
| **Connection pooling** | PgBouncer, ProxySQL, Oracle Connection Cache | No connections. It's HTTP API calls. Every query is stateless |
| **Edge Functions / Supabase-style** | Supabase wraps PostgreSQL with realtime + auth + edge functions | Not a thing. BQ is pure analytics. Your "edge" layer is Cloud Functions/Cloud Run hitting the BQ API |
| **Data types** | `TEXT`, `VARCHAR(n)`, `CHAR(n)` | Just `STRING`. No length variants. No `TEXT` type at all |

### What You Gain

- **Scan 1 TB in ~5 seconds** without provisioning anything
- **Auto-scaling** — 1 query or 1,000 concurrent queries, same experience
- **Zero maintenance** — no vacuuming, no index rebuilding, no replica lag, no disk full at 3am
- **Separation of storage and compute** — store 10 TB for ~$200/month, only pay for queries you actually run
- **Columnar storage** — a `SELECT sentiment, COUNT(*) FROM enriched_feedback GROUP BY sentiment` on a 100M row table only reads the `sentiment` column, not the entire row
- **Materialized views** that auto-refresh without you setting up cron

### When To Use What

- **PostgreSQL/MySQL**: Your app's transactional database. Users logging in, placing orders, updating profiles. Low-latency, row-level, ACID.
- **BigQuery**: Your analytics warehouse. "Show me sentiment trends across 2M support tickets grouped by department and month." Batch processing, aggregations, joins across massive datasets.
- **The pattern**: App writes to PostgreSQL → events/ETL push to BigQuery → dashboards and ML read from BigQuery.

---

## 2. GCP Hierarchy: Projects, Datasets, Tables

```
GCP Organization (optional, for companies)
  └── Project: feedback-intel-demo        ← billing unit, permission boundary
        ├── BigQuery
        │     └── Dataset: feedback       ← like a PostgreSQL schema
        │           ├── Table: raw_feedback
        │           ├── Table: call_transcripts
        │           ├── Table: enriched_feedback
        │           └── Materialized View: daily_summary
        ├── Cloud Storage
        │     ├── Bucket: feedback-intel-raw-data
        │     ├── Bucket: feedback-intel-audio-calls
        │     └── Bucket: feedback-intel-audio-processed
        ├── Pub/Sub
        │     └── Topic: audio-upload-events
        └── IAM
              └── Service Account: feedback-pipeline@...
```

**Project** = the billing + permissions boundary. Everything lives inside a project. Globally unique ID.

**Dataset** = a namespace for tables. Equivalent to a PostgreSQL schema. Has a **location** (EU, US, etc.) that's permanent once set.

**Table** = where data lives. But unlike PostgreSQL, there's no server "holding" it — it's files in Google's distributed storage (Colossus), organized in a columnar format called Capacitor.

---

## 3. Execution Order

The steps below are ordered by dependency. Each step only uses resources that already exist.

```
Step 1: Project + config          (nothing depends on yet)
Step 2: Enable APIs               (needed before any service calls)
Step 3: Service Account + IAM     (needed before bucket notifications)
Step 4: BigQuery dataset          (needed before tables)
Step 5: BigQuery tables + view    (needs dataset)
Step 6: Cloud Storage buckets     (needs storage API)
Step 7: Pub/Sub topic + sub       (needs pubsub API)
Step 8: Bucket notification       (needs: bucket + topic + GCS service agent SA)
Step 9: Verify everything
Step 10: Test insert + query
```

---

## 4. Step 1 — Project + Config

```powershell
gcloud projects create feedback-intel-demo --name="Feedback Intel"
gcloud config set project feedback-intel-demo
gcloud config set compute/region europe-west1
```

`gcloud config set project` is like `cd` for GCP — all subsequent commands target this project unless you pass `--project` explicitly. The project ID is globally unique; if `feedback-intel-demo` is taken, pick a different one.

---

## 5. Step 2 — Enable APIs

GCP gates every service behind an API toggle. Enabling is free — you only pay when you actually use them.

```powershell
gcloud services enable bigquery.googleapis.com storage.googleapis.com cloudfunctions.googleapis.com aiplatform.googleapis.com discoveryengine.googleapis.com run.googleapis.com speech.googleapis.com texttospeech.googleapis.com pubsub.googleapis.com
```

---

## 6. Step 3 — Service Account + IAM

We create this **before** buckets and Pub/Sub because the bucket notification in Step 8 requires that GCP's internal GCS service agent exists and has Pub/Sub publish permissions. Creating the SA and roles early ensures everything is ready when we wire things together.

```powershell
gcloud iam service-accounts create feedback-pipeline --display-name="Feedback Pipeline SA"
```

Assign roles (PowerShell loop):

```powershell
$SA = "feedback-pipeline@feedback-intel-demo.iam.gserviceaccount.com"
foreach ($role in @("roles/bigquery.dataEditor", "roles/aiplatform.user", "roles/storage.objectAdmin", "roles/speech.client", "roles/pubsub.subscriber")) { gcloud projects add-iam-policy-binding feedback-intel-demo --member="serviceAccount:$SA" --role="$role" }
```

A service account is a non-human identity. Your Cloud Functions authenticate as this SA instead of your personal Google account. Each role grants specific permissions:

- `bigquery.dataEditor` — read/write BQ tables
- `aiplatform.user` — call Vertex AI (Gemini) for classification
- `storage.objectAdmin` — read/write/delete in GCS buckets
- `speech.client` — call Chirp STT
- `pubsub.subscriber` — pull messages from Pub/Sub

This is the principle of least privilege. The SA can't create new projects, can't modify IAM, can't delete datasets — only what the pipeline needs.

---

## 7. Step 4 — BigQuery Dataset

```powershell
bq mk --location=EU feedback-intel-demo:feedback
```

`--location=EU` means data physically resides in EU multi-region. Once set, it **cannot be changed** — you'd have to recreate the dataset. Match this with your bucket locations.

Verify:

```powershell
bq show feedback-intel-demo:feedback
```

---

## 8. Step 5 — BigQuery Tables + Materialized View

### The PowerShell Problem

Backticks (`` ` ``) are PowerShell's escape character. When you write `` `feedback-intel-demo.feedback.raw_feedback` `` in a PowerShell string, PowerShell eats the backticks before `bq` ever sees them. Multi-line here-strings also don't always pass cleanly.

**Solution**: Use one-liner commands without backtick-quoted table names. Since your default project is set via `gcloud config`, BQ infers `feedback-intel-demo` from `feedback.tablename` (dataset.table).

> **BQ type gotcha**: There is no `TEXT` type in BigQuery. Use `STRING` for everything — it has no length limit.

Run each one separately (`bq query` doesn't support multiple statements per call):

### Table 1: raw_feedback

Stores text-based feedback — support tickets, reviews, surveys.

```powershell
bq query --use_legacy_sql=false "CREATE TABLE feedback.raw_feedback (id STRING NOT NULL, source STRING NOT NULL, text STRING NOT NULL, customer_id STRING, created_at TIMESTAMP NOT NULL, metadata JSON, ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()) PARTITION BY DATE(created_at) CLUSTER BY source"
```

**PARTITION BY DATE(created_at)** — physically splits data into daily chunks. A query with `WHERE created_at > '2025-01-01'` only scans January+ partitions, not the entire table. This is the #1 cost control mechanism in BigQuery.

**CLUSTER BY source** — within each partition, data is sorted by `source`. Filtering by source skips irrelevant blocks. Think of it as a poor man's index that works at the storage layer.

**JSON column** — BigQuery's JSON type lets you store flexible data without schema changes. You can query into it: `JSON_VALUE(metadata, '$.priority')`. Useful for source-specific fields (a ticket has priority, a review has star_rating, a survey has question_id).

### Table 2: call_transcripts

Stores Chirp STT (Speech-to-Text) output for call recordings.

```powershell
bq query --use_legacy_sql=false "CREATE TABLE feedback.call_transcripts (id STRING NOT NULL, audio_file_uri STRING NOT NULL, transcript_full STRING NOT NULL, transcript_segments JSON, speaker_count INT64, duration_seconds FLOAT64, language_code STRING, chirp_model STRING, confidence_avg FLOAT64, customer_id STRING, created_at TIMESTAMP NOT NULL, transcribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(), processing_time_ms INT64, error_message STRING) PARTITION BY DATE(created_at) CLUSTER BY language_code"
```

### Table 3: enriched_feedback

The unified table after AI classification. Both text feedback and transcribed calls end up here with sentiment, department routing, and issue extraction.

```powershell
bq query --use_legacy_sql=false "CREATE TABLE feedback.enriched_feedback (id STRING NOT NULL, source STRING NOT NULL, text STRING NOT NULL, customer_id STRING, created_at TIMESTAMP NOT NULL, audio_file_uri STRING, call_duration_seconds FLOAT64, speaker_count INT64, department STRING, sentiment STRING, tone STRING, key_issues ARRAY<STRING>, confidence FLOAT64, model_version STRING, classified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()) PARTITION BY DATE(created_at) CLUSTER BY department, sentiment, source"
```

**ARRAY\<STRING\>** — BigQuery natively supports arrays. No junction tables needed. `key_issues` holds multiple tags per feedback item. You query it with `UNNEST`: `SELECT issue, COUNT(*) FROM enriched_feedback, UNNEST(key_issues) AS issue GROUP BY issue`.

**Multi-column clustering** — `CLUSTER BY department, sentiment, source` sorts by department first, then sentiment within each department, then source. Optimizes the most common dashboard filters.

### Materialized View: daily_summary

Pre-computed aggregation that BigQuery auto-refreshes when underlying data changes.

```powershell
bq query --use_legacy_sql=false "CREATE MATERIALIZED VIEW feedback.daily_summary AS SELECT DATE(created_at) AS date, department, sentiment, source, COUNT(*) AS count, AVG(confidence) AS avg_confidence, COUNTIF(confidence < 0.7) AS low_confidence_count FROM feedback.enriched_feedback GROUP BY date, department, sentiment, source"
```

In PostgreSQL you'd create a materialized view and then set up a cron job to `REFRESH MATERIALIZED VIEW` periodically. In BigQuery, it just happens automatically.

Each command should return `Created feedback-intel-demo.feedback.<name>`.

---

## 9. Step 6 — Cloud Storage Buckets

Three buckets, all EU-located to match the BigQuery dataset:

```powershell
gcloud storage buckets create gs://feedback-intel-raw-data --location=EU
gcloud storage buckets create gs://feedback-intel-audio-calls --location=EU
gcloud storage buckets create gs://feedback-intel-audio-processed --location=EU
```

Bucket names are globally unique across all of GCP. If any name is taken, pick a different one (e.g. add your initials).

The separation is intentional: raw text data lands in one bucket, audio files for STT land in another, and processed audio moves to the third. This lets you set different lifecycle policies (auto-delete processed audio after 90 days, keep raw data forever, etc.).

> **Note**: `gsutil` still works but is deprecated. Google is consolidating everything under `gcloud storage`.

---

## 10. Step 7 — Pub/Sub Topic + Subscription

```powershell
gcloud pubsub topics create audio-upload-events
gcloud pubsub subscriptions create audio-upload-sub --topic=audio-upload-events
```

---

## 11. Step 8 — Bucket Notification → Pub/Sub

This wires the audio bucket to Pub/Sub: whenever a file lands in `gs://feedback-intel-audio-calls/`, GCS publishes a JSON message to the topic containing the bucket name, file path, size, etc. Your transcription Cloud Function subscribes and processes new audio files automatically.

First, ensure the GCS service agent exists and can publish to Pub/Sub:

```powershell
gcloud storage service-agent --project=feedback-intel-demo
```

This returns something like `service-146841362083@gs-project-accounts.iam.gserviceaccount.com`. Grant it publish rights:

```powershell
$GCS_SA = (gcloud storage service-agent --project=feedback-intel-demo)
gcloud pubsub topics add-iam-policy-binding audio-upload-events --member="serviceAccount:$GCS_SA" --role="roles/pubsub.publisher"
```

Now create the notification:

```powershell
gcloud storage buckets notifications create gs://feedback-intel-audio-calls --topic=audio-upload-events --event-types=OBJECT_FINALIZE --payload-format=json
```

This is the BigQuery-world replacement for a PostgreSQL trigger. Instead of `AFTER INSERT ON audio_files EXECUTE FUNCTION transcribe()`, you get a fully decoupled event system with built-in retries, dead-letter queues, and no single point of failure.

---

## 12. Step 9 — Verify Everything

```powershell
bq show feedback-intel-demo:feedback.raw_feedback
bq show feedback-intel-demo:feedback.call_transcripts
bq show feedback-intel-demo:feedback.enriched_feedback
bq show feedback-intel-demo:feedback.daily_summary
gcloud storage ls
gcloud pubsub topics list
gcloud pubsub subscriptions list
gcloud iam service-accounts list --filter="email:feedback-pipeline"
```

---

## 13. Step 10 — Test Insert + Query

Prove the pipeline works end-to-end with a test record:

```powershell
bq query --use_legacy_sql=false "INSERT INTO feedback.raw_feedback (id, source, text, customer_id, created_at) VALUES ('test-001', 'ticket', 'The app crashes when I try to upload photos', 'cust-abc', CURRENT_TIMESTAMP())"
```

Query it back:

```powershell
bq query --use_legacy_sql=false "SELECT * FROM feedback.raw_feedback WHERE id = 'test-001'"
```

You should see your test row with an auto-populated `ingested_at` timestamp.

---

## 14. Quick Reference — BQ SQL Differences From PostgreSQL

| PostgreSQL | BigQuery | Notes |
|---|---|---|
| `TEXT` / `VARCHAR(n)` / `CHAR(n)` | `STRING` | No length variants. Just `STRING`, always |
| `SERIAL` / `BIGSERIAL` | `GENERATE_UUID()` | No auto-increment. UUIDs or app-generated IDs |
| `JSONB` | `JSON` | Similar querying, use `JSON_VALUE()` / `JSON_QUERY()` |
| `TEXT[]` | `ARRAY<STRING>` | Use `UNNEST()` to flatten in queries |
| `NOW()` | `CURRENT_TIMESTAMP()` | Same idea |
| `CREATE INDEX` | Doesn't exist | Use `PARTITION BY` + `CLUSTER BY` instead |
| `UPDATE ... WHERE id = x` | Works but slow | BQ rewrites entire partition. Design for append-only |
| `DELETE ... WHERE` | Works but slow | Same — full partition rewrite |
| `\d tablename` | `bq show dataset.table` | Describe table |
| `\dt` | `bq ls dataset` | List tables |
| `pg_dump` | `bq extract` to GCS | Export to CSV/JSON/Avro/Parquet |
| `psql` | `bq query` or Console UI | No persistent connection — each query is a job |

---

## 15. What's `--use_legacy_sql=false`?

BigQuery originally shipped with a non-standard SQL dialect ("legacy SQL") that had quirks like `[project:dataset.table]` bracket syntax, no `WITH` clauses, no `ARRAY` support, no subqueries in `SELECT`, and other oddities. Google later added standard SQL but — for backwards compatibility — kept legacy as the **default** in the `bq` CLI.

So `--use_legacy_sql=false` just means "use normal SQL." You'll want to set it globally so you never have to type it again:

```powershell
echo "[query]`nuse_legacy_sql = false" | Out-File -Encoding ascii ~/.bigqueryrc
```

After that, every `bq query` uses standard SQL by default.

> **Note on gsutil**: You'll see `gsutil` in older docs and Stack Overflow answers everywhere. It still works but is deprecated — Google is folding everything into `gcloud storage` (same underlying API, same auth, just unified CLI). If you see `gsutil` in a tutorial, mentally replace `gsutil mb` → `gcloud storage buckets create`, `gsutil cp` → `gcloud storage cp`, etc. The one place `gsutil` still has an edge is `gsutil -m` for multi-threaded parallel uploads of many files, though `gcloud storage` is catching up.

---

## 16. Cost Mental Model

In PostgreSQL, you pay for the server whether it's idle or processing 10,000 queries. In BigQuery:

- **Storage**: ~$0.02/GB/month (long-term even cheaper). 100GB of feedback data = ~$2/month.
- **Queries**: $5 per TB scanned. A well-partitioned + clustered query on 100GB that only touches 1GB of data = $0.005.
- **Free tier**: First 1 TB of queries per month is free. First 10 GB of storage is free.
- **Materialized views**: Refreshes count as queries (billed by bytes scanned), but they scan incrementally — only new/changed data.
- **Streaming inserts**: $0.01 per 200 MB. Batch loading from GCS is free.

The partitioning and clustering we set up aren't just for performance — they're directly tied to cost. Every column you exclude from `SELECT *`, every partition you skip with a date filter, saves money.
