# feedback-intel — Documenting Progress

> The story of building a GCP customer feedback intelligence platform.
> High-level decisions, hiccups, and lessons — the stuff interviews are made of.

---

## Sprint 01 — GCP Foundation

**What we built:** Project, BigQuery dataset with 3 tables + 1 materialized view, 3 Cloud Storage buckets, Pub/Sub topic + subscription, service account with least-privilege roles.

**Architectural decisions:**
- **Partitioning by `DATE(created_at)` + clustering** — Not just "best practice." Partitioning means queries with date filters skip entire blocks of data (cost + speed). Clustering sorts within partitions for fast column filters. On `enriched_feedback` we cluster by `department, sentiment, source` because those are the dashboard filter columns.
- **Separate `call_transcripts` table** — One audio file → one transcript, but it feeds into the same classification pipeline as text. The transcript table preserves audio-specific metadata (duration, speakers, Chirp confidence) that text sources don't have. The `enriched_feedback` table unifies everything for dashboards.
- **Pub/Sub over direct Cloud Function trigger for audio** — Decoupling. If the transcription service is slow or down, messages queue and retry automatically. Also enables multiple subscribers later (transcription, audio QA, archiving) without changing the event source.
- **Service account with least privilege** — The pipeline SA can read/write BigQuery, access Vertex AI, manage Storage objects, use Speech-to-Text, and subscribe to Pub/Sub. It cannot modify IAM, create resources, or access other projects.

---

## Sprint 02 — Seed Data Generation

**What we built:** 1967 text feedback records (CSV) + 35 synthetic call audio files (WAV) with ground truth transcripts.

**Hiccup: SDK deprecation caught early.**
Started with `vertexai.generative_models` (the old Vertex AI SDK). Noticed deprecation warnings — this SDK is removed June 2026. Migrated everything to the `google-genai` SDK (`google.genai.Client`) before generating any data. The new SDK is cleaner: one client, explicit config objects, works for both Vertex AI and direct API.

**Key choice: Gemini 2.5 Flash Lite for generation.**
Cheapest model, perfect for bulk structured text. We're generating fake data, not doing complex reasoning. Saved significant cost vs using Pro or even standard Flash.

**Key choice: Chirp 3 HD voices for TTS.**
Used `en-US-Chirp3-HD-Leda` (agent) and `en-US-Chirp3-HD-Charon` (customer) at 24000 Hz. Far more natural than older Studio voices. Ground truth JSON saved alongside each WAV for WER evaluation later.

---

## Sprint 03 — Text Ingestion Pipeline

**What we built:** A Gen2 Cloud Function triggered by GCS uploads that validates CSV rows and streams them into BigQuery.

### Hiccup: The IAM Permission Chain (4 separate fixes)

Deploying a Gen2 Cloud Function with a GCS trigger requires a chain of 4 IAM grants that aren't obvious from the docs:

1. **Eventarc SA needs `storage.admin`** on the bucket — so it can watch for object events.
2. **Pipeline SA needs `eventarc.eventReceiver`** — so it can receive the routed events.
3. **GCS service agent needs `pubsub.publisher`** — because under the hood, GCS notifications go through Pub/Sub, and the GCS service agent (not your SA) publishes them.
4. **Pipeline SA needs `run.invoker`** — because Gen2 functions ARE Cloud Run services, and Eventarc needs to invoke them authenticated.

Each one surfaced as a separate deploy/invocation failure. The lesson: Gen2 Cloud Functions are Cloud Run + Eventarc + Pub/Sub stitched together. You're debugging 3 systems, not 1.

### Hiccup: Eventarc Retry Storm (duplicates)

While we were fixing IAM permissions (attempts 1-4 above), Eventarc was queuing every failed delivery and retrying. Once permissions were finally correct, ALL queued retries fired at once. Result: 3934 rows instead of 1967 (exact 2x).

**Lesson:** Eventarc retries are persistent (up to 7 days). First deployment of an event-driven function should always be followed by a dedup check. Better yet: build idempotency into the function (check-before-insert).

### Hiccup: Dedup on JSON columns

Tried `SELECT DISTINCT *` to dedup — failed because BigQuery's JSON type doesn't support equality comparison. Tried `CREATE OR REPLACE TABLE ... AS SELECT` with `ROW_NUMBER()` — failed because it would change the partitioning spec (the original table has `PARTITION BY DATE(created_at) CLUSTER BY source`).

**Fix:** Three-step swap: (1) CTAS to a new table with matching partition spec, (2) DROP original, (3) ALTER TABLE RENAME. This is the standard BigQuery pattern when you need to rebuild a partitioned table.

**Side discovery:** The original seed CSV had duplicate IDs across Gemini generation batches (1967 rows but only 1364 unique IDs). The dedup collapsed those too. 1364 records is still plenty for the demo.

### Hiccup: PowerShell BOM in CSV

Tested incremental upload with a CSV created by PowerShell's `Out-File -Encoding utf8`. The function triggered but logged "No valid rows found." Root cause: PowerShell adds a UTF-8 BOM (`\ufeff`) at the start of the file. Python's `csv.DictReader` doesn't strip it, so the first header becomes `\ufeffid` instead of `id` — failing our required fields check silently.

**Fix:** Strip BOM before parsing: `if content.startswith("\ufeff"): content = content[1:]`. This is a production-grade fix — Excel exports do the same thing.

### Hiccup: Streaming buffer blocks DML

After the incremental test (3 rows via streaming insert), tried to `DELETE` the test rows. BigQuery refused: "would affect rows in the streaming buffer." Streaming inserts sit in a buffer for ~30 minutes where DML can't touch them.

**Lesson:** If you need immediate DML access to freshly loaded data, use batch loads (`load_table_from_*`) instead of streaming inserts. Streaming is for real-time pipelines where you don't need to modify data immediately after insertion.

### What's under the hood: Gen2 Cloud Functions

Those auto-created `gcf-v2-sources-*` and `gcf-v2-uploads-*` buckets? Gen2 functions are secretly Cloud Run services. The deploy pipeline is: your code → zip → upload bucket → Cloud Build → Docker image → Artifact Registry → Cloud Run. The `146841362083` in the bucket names is the project number (not project ID).

---

## Sprint 04 — NLP/Sentiment Enrichment

**What we're building:** A Gemini-powered classification pipeline that reads all feedback from `raw_feedback`, classifies each record (department, sentiment, tone, key issues, confidence), and writes structured results to `enriched_feedback`.

### Architecture

```
raw_feedback (1364 rows)
    │
    ▼
classify_feedback.py
    │  ← Gemini 2.5 Flash Lite (structured JSON output)
    │  ← LEFT JOIN enriched_feedback WHERE NULL (idempotent)
    │  ← Retry logic + validation clamping
    ▼
enriched_feedback (partitioned, clustered)
    │
    ▼
daily_summary (materialized view, auto-refreshes)
```

### Design decisions

- **Structured JSON output** (`response_mime_type="application/json"`) — Forces Gemini to return valid JSON. No regex parsing, no markdown stripping. Production pipelines need this.
- **`temperature=0.1`** — Near-deterministic. Classification should be consistent, not creative.
- **Validation clamping** — If Gemini returns an unexpected department or sentiment, we fall back to defaults instead of crashing. Defensive coding for LLM outputs.
- **model_version tracking** — Every row records `gemini-2.5-flash-lite-v1` (or v2, v3). Enables prompt version comparison later.
- **Prompt iteration strategy** — V1 (baseline rules), V2 (few-shot examples for edge cases), V3 (transcript-specific handling for disfluencies and ASR errors). Each version run against a test set for comparison.

*(Results and hiccups will be added after classification run)*

---

## Sprint 05 — Chirp Speech-to-Text Pipeline

**What we're building:** Transcribe 35 synthetic call WAV files using Chirp 3 via Cloud Speech-to-Text V2 API with speaker diarization. Store in `call_transcripts`, then feed into classification pipeline.

**Hiccup: Chirp 2 doesn't support diarization.**
Our first attempt used Chirp 2 (`chirp_2` model, `europe-west4` region). Deployment worked but the API rejected our config: "Recognizer does not support feature: speaker_diarization". Research revealed that Chirp 2 supports word-level timestamps and confidence but NOT speaker diarization. Diarization was added in Chirp 3.

**Decision: Chirp 3 over Chirp 2 — and why.**

| Feature | Chirp 2 | Chirp 3 |
|---|---|---|
| Speaker diarization | :x: | :white_check_mark: (BatchRecognize + Recognize) |
| Word-level timestamps | :white_check_mark: Solid | :warning: Some degradation |
| Word-level confidence | :white_check_mark: Reliable | :x: Not supported |
| Auto punctuation | :white_check_mark: | :white_check_mark: |
| Max audio (batch) | 8 hours | 1 hour |
| Regions (GA) | us-central1, europe-west4, asia-southeast1 | us, eu (multi-region) |

We chose Chirp 3 because:
1. Diarization lets us separate agent vs customer speech → cleaner classification
2. `eu` multi-region GA matches our bucket location
3. Word confidence loss isn't critical — we have ground truth for WER evaluation
4. Our calls are 1-3 min, well within the 1 hour limit

**Hiccup: Chirp 3 doesn't support `enable_word_confidence`.**
After switching to Chirp 3, got: "Recognizer does not support feature: word_level_confidence". Makes sense — the Chirp 3 docs explicitly list word-level confidence as unsupported. Removed the flag.

**Hiccup: Streaming buffer blocks cleanup (again).**
Error rows from the failed Chirp 2 attempt were inserted via streaming (`insert_rows_json`). Couldn't DELETE them due to the ~30 min streaming buffer. Fix: DROP TABLE + CREATE TABLE (nuclear but effective when there's no good data to preserve).

**Lesson learned: Streaming vs Batch inserts.**

| | Streaming (`insert_rows_json`) | Batch Load (`load_table_from_*`) |
|---|---|---|
| Speed | Rows visible in seconds | 30s-2min |
| Cost | $0.01 per 200 MB | Free |
| DML after insert | :x: Blocked ~30 min | :white_check_mark: Immediate |
| Best for | Real-time events | ETL, bulk imports |

We used streaming for convenience, but batch loads would have been smarter for ETL pipelines — free, immediate DML, and dedup support via write dispositions.

**Key concepts:**
- Google Chirp is the MODEL. Cloud Speech-to-Text V2 is the API. Same pattern as Gemini/Vertex AI.
- `batch_recognize` (not `recognize`) for files > 60 seconds — async, reads directly from GCS.
- The wildcard recognizer `projects/{project}/locations/{location}/recognizers/_` avoids needing to pre-create a recognizer resource.
- `AutoDetectDecodingConfig` handles any sample rate automatically (our TTS was 24kHz, Chirp handles it).

**Interview one-liners:**
- "Chirp 2 has better word-level metrics but no diarization. Chirp 3 adds diarization but drops word confidence. Choose based on whether you need speaker separation."
- "I used streaming inserts for speed but learned about the 30-min DML buffer. In production, batch loads are free and support immediate mutations."
- "Chirp is the model, STT V2 is the API — same pattern as Gemini and Vertex AI."

*(Results pending — transcription running)*

---

## Running Themes

### Things that keep coming up
- **IAM is always the problem.** Every GCP service interaction requires the right SA with the right role. The error messages are vague. Document every grant.
- **BigQuery has opinions.** Partitioning specs are immutable on replace. JSON columns can't be compared. Streaming buffers block DML. Learn the constraints or waste hours.
- **LLM SDKs move fast.** The Vertex AI SDK we started with was already deprecated. Always check the latest docs before writing production code.
- **PowerShell vs Linux assumptions.** BOM in files, backtick escaping eaten by PowerShell, `gsutil` deprecated in favor of `gcloud storage`. Small things that waste big time.
- **Model feature matrices matter.** Chirp 2 vs 3, Gemini Flash vs Flash Lite — each model has specific feature support. Always check the docs before writing code. Don't assume a newer model supports everything the older one did.

### Interview-ready one-liners
- "Gen2 Cloud Functions are Cloud Run + Eventarc + Pub/Sub. You're debugging three systems."
- "Eventarc retries are persistent — if you fix IAM after failed deliveries, every queued retry fires at once."
- "BigQuery streaming inserts are append-only for 30 minutes. Design around it or use batch loads."
- "Always validate LLM output structure — temperature=0 doesn't mean the schema is guaranteed."
