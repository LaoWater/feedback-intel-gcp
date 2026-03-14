# feedback-intel — Documenting Progress

> The story of building a GCP customer feedback intelligence platform.
> High-level decisions, hiccups, and lessons learned across 11 sprints.

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

**Key takeaways:**
- "Chirp 2 has better word-level metrics but no diarization. Chirp 3 adds diarization but drops word confidence. Choose based on whether you need speaker separation."
- "I used streaming inserts for speed but learned about the 30-min DML buffer. In production, batch loads are free and support immediate mutations."
- "Chirp is the model, STT V2 is the API — same pattern as Gemini and Vertex AI."

### Results

**Transcription:** 35/35 files transcribed, 0 failures. Avg 60s audio processed in avg 19s (first file 265s cold start — Chirp provisioning infrastructure). 32 calls detected 2 speakers, 3 calls detected 3 speakers. Diarization cleanly separates agent vs customer speech.

**The confidence_avg = 0.0 catch:** Since Chirp 3 doesn't provide word confidence, every transcript stored `confidence_avg = 0.0`. This silently broke the downstream bridge script (`transcript_to_classification.py`) which filtered `WHERE confidence_avg > 0.6` — rejecting ALL transcripts. Fixed to `(confidence_avg > 0.6 OR confidence_avg = 0.0)` so Chirp 3's "no data" passes through while still filtering genuinely low-confidence Chirp 2 results.

**Classification of call transcripts:** 35 records classified in 41.5s. Call avg confidence 0.91 vs text avg 0.92 — practically identical. Calls skew toward Support (46%) and negative sentiment (51%), which is realistic (people call when they have problems).

**Cold start on batch_recognize:** First API call took 265s (~4.4 min). Subsequent calls: 12-30s. This is the Chirp 3 batch infrastructure warming up — not a bug, just the reality of on-demand ML inference. In production, you'd keep recognizers warm with periodic health checks.

**Hiccup: Stale error rows survive re-runs.**
The transcription script logs error rows to BigQuery (so we don't retry failed files forever). But when we DROP + CREATE the table and re-run successfully, the old error rows from previous runs don't get cleaned automatically — the idempotency check (`get_already_transcribed()`) only looks at `WHERE error_message IS NULL`, so it re-transcribes error files correctly but doesn't delete the old error row. Result: 36 rows (35 success + 1 stale error). Harmless — all downstream queries filter `WHERE error_message IS NULL` — but worth noting.

**Key takeaway:**
- "Chirp 3 doesn't return word confidence, so any downstream filters on confidence need to handle 0.0 as 'no data available' rather than 'bad transcription.'"
- "The first batch_recognize call takes 4-5 minutes (cold start). Subsequent calls drop to 15-30 seconds. Plan for this in pipeline timeouts."

---

## Sprint 06 — Evaluation & Iteration

**What we built:** WER evaluation for Chirp transcriptions + classification accuracy check for the full call pipeline. Also discovered a taxonomy mismatch between data generation and classification.

### The synthetic data reckoning

The original plan said "manually label 100 test records." We stopped and asked: label them with what? The feedback is synthetic — Gemini wrote it. If a human reads Gemini's text and says "this is Engineering," and the classifier also says "Engineering," that's two readers agreeing on text that was *designed to be classifiable*. It's circular. It proves nothing.

The honest answer: text classification accuracy on synthetic data cannot be meaningfully evaluated. The only real evaluation requires labeled production data with known ground truth (actual department routing, actual customer sentiment from follow-up surveys, etc.).

What we CAN evaluate:
1. **WER** — the original script text went through TTS → audio → Chirp STT. Comparing Chirp's output to the original script is a real, clean metric.
2. **Call classification through STT noise** — the ground truth JSONs have `expected_department` and `expected_sentiment` set at generation time. Since the text went through TTS → STT (introducing real word errors), checking if classification survives that noise tests the full pipeline's signal preservation.

### WER results: 4.02% micro-average

Chirp 3 transcribed 35 calls with 6,047 total words and got 243 wrong. That's a 4.02% WER — well under any reasonable production threshold.

**The error pattern is revealing:** 142 insertions vs 70 substitutions vs 31 deletions. Chirp adds extra words more than it mishears them. On clean TTS audio, the model rarely confuses one word for another — but it sometimes hallucinates filler words or splits compound words.

**Department consistency:** WER ranged from 3.6% to 4.5% across departments. No vocabulary domain is notably harder for Chirp.

**The caveat we documented:** this is TTS→STT round-trip on synthetic audio. Real human speech with accents, background noise, crosstalk, and mumbling would push WER higher. The pipeline works; the exact number is optimistic.

### Call classification: 82.9% department, 89.3% sentiment

This is where it gets interesting. The classifier gets the department right on 29/35 calls that went through the full pipeline (script → TTS → Chirp STT → Gemini classification).

**Engineering: 8/8 perfect.** Bug reports are unambiguous even through STT noise.

**Negative sentiment: 14/14 perfect.** The classifier never misses an angry customer. The 3 sentiment errors were all neutral↔positive confusion — the least consequential type of miss.

### The taxonomy mismatch discovery

During evaluation we found that the ground truth JSONs use 6 departments (Engineering, Product, UX, Support, **Billing**, **Logistics**) but the classifier only knows 4. Ten out of 35 calls have departments the classifier literally cannot output.

We mapped Billing→Support and Logistics→Support for comparison (closest semantic match). Of those 10, 8 were correctly classified as Support.

The 6 department misclassifications are all genuine edge cases:
- "Customer struggles to find billing info" — is that UX (navigation) or Support (billing question)? Both are defensible.
- Two Billing calls about plan upgrades/downgrades → classified as Product. Because subscription tier changes ARE product decisions. The Billing→Support mapping is debatable here.
- A feature report that mentions bugs → Product expected, got Engineering. Reasonable.

**Takeaway:** In production, you'd either expand the classifier's taxonomy to match the business reality (add Billing, Logistics as separate departments) or maintain an explicit mapping with documented trade-offs. The fact that we found this gap in evaluation is exactly why you evaluate.

### What we deliberately skipped

- **V1→V2→V3 prompt comparison on synthetic data.** V1 works well. The prompts are written, the methodology (version tracking via `model_version` field, structured evaluation framework) is in place. Running all three against synthetic data to produce fake improvement metrics would look good on paper but fall apart under scrutiny. "What was your ground truth?" is a question worth answering honestly.
- **100 labeled test records.** Not meaningful on synthetic text. The evaluation framework (`evaluate_call_classification.py`) works — plug in real labeled data and it runs the same way.

**Key takeaways:**
- "WER is the standard metric for STT accuracy. Ours was 4% on synthetic audio — realistic floor, not ceiling."
- "You can't evaluate an LLM classifier on LLM-generated data. The evaluation framework matters more than fake metrics."
- "We found a taxonomy mismatch during evaluation — 6 departments in the data, 4 in the classifier. That's the kind of thing evaluation is for."
- "Insertions dominated our WER errors — Chirp adds words more than it mishears them on clean audio."

---

## Sprint 07 — Vertex AI Search

**What we're building:** A semantic search layer over all classified feedback — text tickets, reviews, surveys, and call transcripts — using Vertex AI Search (Google's managed RAG-as-a-service).

### Understanding Vertex AI Search (the "why" before the "how")

Before this sprint, we had ~1,400 classified records in `enriched_feedback` (BigQuery). A product manager wanting to know "what are customers saying about login problems?" would need SQL:

```sql
SELECT * FROM enriched_feedback WHERE text LIKE '%login%' OR text LIKE '%password%'
```

That's keyword matching. It misses feedback like "I couldn't access my account" because none of the keywords match, even though the *meaning* is identical.

**Vertex AI Search solves this by understanding meaning, not just keywords.** Under the hood, it:
1. Embeds every record into a vector (numerical representation of meaning)
2. When you query, embeds your question the same way
3. Finds records with similar meaning (semantic matching)
4. Generates an AI summary of the matching results with citations

Instead of building this yourself (vector database + embedding pipeline + retrieval logic + summarization), Google packages it all behind one API. That's what "RAG-as-a-service" means — Retrieval-Augmented Generation where the retrieval is managed for you.

### Architecture

```
enriched_feedback (BigQuery, 1400+ records)
    │
    ▼
Vertex AI Search Data Store (indexes everything)
    │
    ▼
Search Engine / App (query interface)
    │
    ▼
search_feedback(query, department, source)  ← Python function
    │
    ▼
Returns: AI summary with citations + top matching records
```

### Three components we create

1. **Data Store** — connected to our BigQuery `enriched_feedback` table. Vertex AI Search reads the table and indexes all records. When we add new classified feedback, it can re-sync.

2. **Search Engine (App)** — sits on top of the data store. This is the query endpoint. It handles embedding queries, matching, ranking, and generating summaries. Enterprise tier includes generative answers (AI summaries) at no extra cost per query.

3. **Python query function** — `search_feedback(query, department, source)` wraps the API call. Supports filtering by department and source (so you can search only call transcripts, or only Engineering feedback).

### Cost

~$1.50 per 1,000 queries. For a project this size, this is effectively free. Google also offers a $1,000 Vertex AI Search promo credit for new customers.

The real cost to be aware of is data store indexing — when you connect BigQuery, it indexes your data. For ~1,400 records this is negligible, but on production-scale data (millions of records) it becomes a line item.

### Results

All three test queries returned semantically relevant results with AI-generated summaries:

1. **"what are customers saying about login problems"** — 10 results across tickets AND call transcripts. The AI summary synthesized them into categories: login page refreshing, authentication errors affecting whole teams, mobile app login hanging, session timeout complaints. It cited 5 sources with [1]-[5] references.

2. **"app crashes" filtered to Engineering** — 10 results, all correctly filtered to Engineering. The summary categorized by platform: mobile crashes when updating tasks, iOS crashes on project files, desktop crashes with large files. Keyword search would have found these, but the AI summary grouping them by scenario is the real value.

3. **"billing complaints" filtered to call transcripts** — 5 call results about billing. The key moment: the query "billing complaints" matched transcripts that say "charge on my invoice" and "latest invoice" — zero keyword overlap. That's semantic understanding in action.

### Hiccups: CONTENT_REQUIRED vs NO_CONTENT (the big one)

Created the data store with `content_config=CONTENT_REQUIRED`. All 1,378 imports failed with: "To create document without content, content config must be NO_CONTENT."

The distinction: `CONTENT_REQUIRED` is for **document stores** — PDFs, HTML pages, text blobs where the entire thing is "content." Our data is **structured** — each record has discrete fields (text, department, sentiment, etc.). For structured BigQuery data, you use `NO_CONTENT` because the individual fields ARE the data, not a single content blob.

This isn't obvious from the docs. The naming is confusing: "NO_CONTENT" sounds like "no searchable content," but it actually means "I'm providing structured fields, not a content document."

### Hiccup: BigQuery `_id` field requirement

Discovery Engine's `custom` data schema requires a field literally named `_id` as the document identifier. Our BigQuery table uses `id`. The import silently failed on every record.

Fix: created a BigQuery view `enriched_feedback_search` that simply renames `id → _id` and passes everything else through. Simple, but not documented clearly.

### Hiccup: Fields not filterable by default

After successful import, tried filtering: `--department Engineering`. Got: "Unsupported field 'department' on ':' operator."

Vertex AI Search auto-detects your schema from BigQuery but doesn't know which fields should be filterable (indexed) vs searchable (text-matched) vs retrievable (returned in results). You have to explicitly update the schema with annotations: `indexable`, `searchable`, `retrievable`, `dynamicFacetable`.

### Hiccup: Data store deletion takes 12+ hours

Needed to delete and recreate the data store (to fix `CONTENT_REQUIRED` → `NO_CONTENT`). Google says deletion "could take a couple of hours." Actual time: still pending after 12 hours. Fix: used new IDs (`feedback-store-v2`, `feedback-search-app-v2`) and moved on. Pragmatic.

### Key takeaways

- "Vertex AI Search is RAG-as-a-service — embeddings, indexing, retrieval, and summarization behind one API. No vector database to manage."
- "For structured BigQuery data, use `NO_CONTENT` — not `CONTENT_REQUIRED`. The naming is counterintuitive: NO_CONTENT means 'structured fields,' not 'nothing to search.'"
- "Semantic search matched 'billing complaints' to transcripts saying 'charge on my invoice' — zero keyword overlap. That's the difference between LIKE and embeddings."
- "Every field needs explicit schema annotations: indexable for filters, searchable for text matching, retrievable to appear in results. Auto-detect only gets the types right."
- "Data store deletion can take half a day. Use new IDs and move on."

---

## Sprint 08 — Apache Beam + Dataflow Pipeline

**What we're building:** A real streaming pipeline that replaces local script execution. Feedback events flow through Pub/Sub into an Apache Beam pipeline that parses, validates, and writes to BigQuery — deployable on Google Cloud Dataflow as a continuously running managed job.

**Full reference:** `Apache_Dataflow.MD` has all concepts, commands, costs, and replication steps.

### The "why" — answering the production question

Before this sprint, the honest answer to "how does your pipeline run?" was: "I run Python scripts on my laptop." That's fine for development, but it's not a production story. The Cloud Function (Sprint 03) handles CSV batch uploads, but real-time feedback events had no processing path.

Now we have two ingestion patterns:
1. **Batch:** CSV upload → Cloud Function → BigQuery (event-driven, file-level)
2. **Streaming:** API/webhook → Pub/Sub → Beam pipeline → BigQuery (continuous, message-level)

Both feed the same `raw_feedback` table. Different patterns, same destination.

### Key architectural choice: Beam over Cloud Functions for streaming

Why not just deploy another Cloud Function that subscribes to Pub/Sub?

| | Cloud Function | Beam on Dataflow |
|---|---|---|
| Scaling | Per-invocation (one function per message) | Distributed workers (batch internally) |
| State | Stateless (each invocation independent) | Can maintain state across messages (windows, aggregations) |
| Cost model | Per invocation ($0.40/million) | Per worker-hour (~$0.056/hr/vCPU) |
| Best for | Low-volume, simple transforms | High-volume, complex multi-step processing |
| Portability | GCP-only | Beam runs on Flink, Spark, Dataflow |

For our demo volume, either works. But Beam demonstrates production-grade data engineering: distributed processing, windowing capability, runner portability, and managed auto-scaling.

### The Beam pipeline design

Three separate DoFns, each doing one thing:

1. **ParseMessage** — bytes → JSON. Handles decode errors without crashing.
2. **ValidateRecord** — checks required fields. Bad records are logged, not dropped silently.
3. **FormatForBigQuery** — shapes the dict to match BQ schema. Serializes metadata to JSON string.

Why not one big function? Each step shows up separately in the Dataflow monitoring UI. If validation is rejecting 50% of messages, you see it immediately. If BigQuery writes are slow, you see the bottleneck. Single Responsibility isn't just clean code — it's observability.

### Hiccups

1. **`yield` + bare `return` in DoFn.** Beam warned about mixing yield and return in `ValidateRecord.process()`. Python treats a function with `yield` as a generator — a bare `return` becomes `StopIteration`, which is fine syntactically but confuses Beam's DoFn runner. Fix: use `if/else` to either yield or not. Never mix.

2. **DirectRunner + Pub/Sub streaming = gRPC hang.** Running the pipeline in streaming mode locally hung with "Waiting for grpc channel to be ready at localhost:XXXXX." DirectRunner's portable runner framework can't start the local gRPC server reliably (especially Windows). Fix: `--local` flag with `beam.Create()` for testing. Use DataflowRunner for real streaming.

3. **FILE_LOADS needs GCS, STREAMING_INSERTS doesn't.** Local batch mode defaulted to FILE_LOADS (write to GCS temp, then bulk load). Failed with "Invalid GCS location: None." Fix: explicitly set `method=STREAMING_INSERTS` in local mode — bypasses GCS entirely. In streaming mode on Dataflow, Beam uses STREAMING_INSERTS automatically.

---

## Sprint 09 — Looker Studio Dashboard

**What we're building:** A BI dashboard that makes 1,402 classified feedback records explorable. Stakeholders pick a department, see sentiment breakdown, top issues, call vs text comparison — all without writing SQL.

### The "why" — data without a dashboard is a report nobody reads

We have enriched data, materialized views, even semantic search. But none of that is self-serve. A product manager shouldn't need to write SQL to see "what are customers complaining about this week?" Looker Studio is Google's free BI tool — it connects directly to BigQuery with zero data movement.

### The real work: BigQuery views, not the dashboard itself

Looker Studio is drag-and-drop UI. The engineering work is preparing the data so the UI can consume it. Three problems Looker can't solve on its own:

**1. ARRAY columns (key_issues)**
`enriched_feedback.key_issues` is a `REPEATED STRING` — an array. Looker Studio can't query arrays directly. You can't make a bar chart of "top issues" when each row contains multiple issues in an array.

Solution: `dashboard_view` uses `CROSS JOIN UNNEST(key_issues) AS issue` — explodes each array into separate rows. A record with 3 issues becomes 3 rows. The view went from 1,402 rows to ~4,200. This is the standard pattern for denormalizing arrays for BI tools.

**2. Aggregating call pipeline health**
`call_transcripts` has per-call metrics (duration, confidence, processing time). Looker can aggregate these, but you'd need calculated fields for success rate, average confidence by date, etc. Easier to pre-compute.

Solution: `call_analytics` view aggregates by date — calls transcribed, success rate, average Chirp confidence, negative/positive sentiment split. One row per day, ready for time-series charts.

**3. Source comparison (text vs calls)**
Comparing feedback sources requires a GROUP BY across source × department with derived metrics (negative rate, average confidence). Doable in Looker but fragile to set up.

Solution: `source_comparison` view pre-computes the pivot — 16 rows (8 departments × 2 sources), each with count, avg confidence, and negative rate.

### Views vs direct table queries — the trade-off

| | Direct table | View | Materialized view |
|---|---|---|---|
| Storage cost | — | Free (no data stored) | Stores result set |
| Query cost | Full scan | Full scan (view is just saved SQL) | Reads cached result |
| Freshness | Real-time | Real-time | Refresh interval |
| Best for | Ad-hoc queries | BI tools, denormalization | Time-series aggregations |

We use regular views for `dashboard_view`, `call_analytics`, and `source_comparison` — our data is small (1,402 rows), so scan cost is effectively $0.00. The existing `daily_summary` is a materialized view because it aggregates by date/department/sentiment, and that pattern benefits from caching as data grows.

**Rule of thumb:** Regular views for small or frequently-changing data. Materialized views for expensive aggregations on large, append-mostly tables.

### Key takeaways

- "Looker Studio can't UNNEST arrays — you need a BigQuery view that CROSS JOINs the array into rows. Standard BI denormalization pattern."
- "Regular views are free but re-scan every query. Materialized views cache results but cost storage. At 1,400 rows, regular views are the right call."
- "The dashboard engineering isn't the charts — it's preparing BigQuery views so a drag-and-drop tool can consume complex data structures."

---

## Sprint 10 — React Frontend + API

**What we're building:** A FastAPI backend exposing BigQuery data as REST endpoints, and a React frontend that makes the entire pipeline explorable — dashboards, transcript viewer, classification explorer, and semantic search.

### The "why" — the ML engineering layer

Looker covers BI stakeholders. The frontend covers the ML engineering story: "here's the pipeline health, here are the transcripts, here's how the classifier performed, here's semantic search in action." Opening a polished dashboard with real data is more convincing than describing it.

### API design: thin layer over BigQuery

The FastAPI backend is intentionally thin — 8 endpoints, no ORM, no database migrations. Each endpoint is a parameterized BigQuery query. Why?

1. **BigQuery IS the database.** Adding Postgres or SQLite in front of it would be redundant. The data is in BigQuery, the queries run in BigQuery, the API just formats results as JSON.
2. **Parameterized queries.** The spec example used f-string interpolation (`f"department = '{department}'"`) — classic SQL injection. We use `@param` bindings: BigQuery handles escaping. This is standard practice — always parameterize.
3. **No caching layer.** Our data is static (1,402 records). BigQuery queries over this volume cost effectively $0 and return in <1s. Adding Redis would be over-engineering.

### Frontend architecture: 4 pages, dark theme, Recharts

| Page | Data Source | Purpose |
|---|---|---|
| Dashboard | `/stats` + `/chirp-stats` + `/departments` | Pipeline health overview, sentiment donut, department bars |
| Transcripts | `/transcripts` + `/transcript/{id}` | Browse calls, click for full transcript + classification |
| Explorer | `/feedback` + `/departments` | Filter by department/sentiment/source, click for detail |
| Search | `/search` | Vertex AI Search with AI summary + results |

Vite proxies `/api/*` to the FastAPI server in development — no CORS issues, no URL hardcoding.

### Key takeaways

- "The API is a thin layer over BigQuery — parameterized queries, no ORM, no caching. BigQuery IS the database at this scale."
- "The spec had SQL injection in the feedback endpoint. I caught it and switched to @param bindings. That's the kind of thing code reviewers look for."
- "FastAPI + React is the standard stack for ML engineering dashboards. The alternative is Streamlit, but that doesn't demonstrate frontend engineering."

---

## Sprint 11 — Documentation & Demo Prep

**What we're building:** Nothing new. This sprint packages everything into clear, reproducible documentation.

### The real work in Sprint 11

The code is done. The engineering is done. Sprint 11 is about communication — documenting what was built, why it was built that way, and how someone else can reproduce it.

Three deliverables:

1. **README.md rewrite** — The original README was a work-in-progress snapshot. The final version has the full architecture (batch + streaming paths), every technology with justification, complete project structure, and a working setup guide.

2. **Stakeholder_Demo_Guide.md** — A 5-minute walkthrough script for demoing the platform. Plus 12 Q&A covering architecture, AI/ML, GCP specifics, and production considerations.

3. **Documentation audit** — Every sprint has a section in this file with the "why," the hiccups, and the key takeaways. Running Themes captures patterns across sprints.

### What makes this a strong project

| Strong | Weak |
|---|---|
| Documents WHY, not just what | README says "I used BigQuery" |
| Shows prompt iteration (V1→V3) | Shows final prompt only |
| Admits evaluation limits on synthetic data | Claims 85% accuracy without caveats |
| Fixes spec bugs (SQL injection) | Copy-pastes spec code |
| Has a reproducible setup script | "It works on my machine" |
| Explains trade-offs (Chirp 2 vs 3) | Uses whatever tutorial said |

---

## Running Themes

### Things that keep coming up
- **IAM is always the problem.** Every GCP service interaction requires the right SA with the right role. The error messages are vague. Document every grant.
- **BigQuery has opinions.** Partitioning specs are immutable on replace. JSON columns can't be compared. Streaming buffers block DML. Learn the constraints or waste hours.
- **LLM SDKs move fast.** The Vertex AI SDK we started with was already deprecated. Always check the latest docs before writing production code.
- **PowerShell vs Linux assumptions.** BOM in files, backtick escaping eaten by PowerShell, `gsutil` deprecated in favor of `gcloud storage`. Small things that waste big time.
- **Model feature matrices matter.** Chirp 2 vs 3, Gemini Flash vs Flash Lite — each model has specific feature support. Always check the docs before writing code. Don't assume a newer model supports everything the older one did.
- **Synthetic data has hard evaluation limits.** You can evaluate the pipeline (does signal survive TTS→STT→classification?) but you can't evaluate the classifier itself without real labeled data. Know the difference. Build the framework, don't fake the metrics.
- **Taxonomy mismatches surface in evaluation.** Your data and your classifier might use different categories. Evaluation is when you find out. Document it, don't hide it.
- **Beam is the code, Dataflow is the runtime.** Same pipeline.py runs locally (DirectRunner) or on managed workers (DataflowRunner). The runner is a CLI flag, not a code change. This is the portability promise.
- **GCP naming is counterintuitive.** `NO_CONTENT` means "structured fields" not "nothing to search." `CONTENT_REQUIRED` means "document blob" not "must have content." Read the enum values, not the names.
- **GCP deletions are slow.** Data store deletion took 12+ hours. Don't wait — use new IDs and move on. This pattern applies to many GCP resources.
- **BI tools can't handle raw data structures.** Arrays, nested fields, cross-table aggregations — all need pre-computed views. The engineering is in the views, not the charts.
- **Spec code isn't production code.** The implementation plan had f-string SQL interpolation — textbook SQL injection. Always review spec code before shipping it.

### Key one-liners
- "Gen2 Cloud Functions are Cloud Run + Eventarc + Pub/Sub. You're debugging three systems."
- "Eventarc retries are persistent — if you fix IAM after failed deliveries, every queued retry fires at once."
- "BigQuery streaming inserts are append-only for 30 minutes. Design around it or use batch loads."
- "Always validate LLM output structure — temperature=0 doesn't mean the schema is guaranteed."
- "WER is the standard metric for STT accuracy. Ours was 4% on synthetic audio — realistic floor, not ceiling."
- "You can't evaluate an LLM classifier on LLM-generated data. The evaluation framework matters more than fake metrics."
- "We found a taxonomy mismatch during evaluation — 6 departments in the data, 4 in the classifier. That's the kind of thing evaluation is for."
- "Apache Beam is the code, Dataflow is the runtime — like Docker and Kubernetes."
- "Cloud Function for batch file uploads, Beam pipeline for real-time event streams. Same BigQuery destination, different patterns."
- "Pub/Sub is the shock absorber between ingestion and processing. Decouples producers from consumers."
- "Vertex AI Search is RAG-as-a-service — embeddings, indexing, retrieval, and summarization behind one API."
- "Semantic search matched 'billing complaints' to 'charge on my invoice' — zero keyword overlap. That's embeddings vs LIKE."
- "For structured BigQuery data use NO_CONTENT, not CONTENT_REQUIRED. The naming is backwards."
- "Looker can't query REPEATED fields — CROSS JOIN UNNEST into a view. Standard BI denormalization."
- "Regular views for small data, materialized views for expensive aggregations. Know the trade-off."
- "The API is a thin BigQuery wrapper — parameterized queries, no ORM, no cache. At 1,400 rows, anything more is over-engineering."
- "Caught SQL injection in the spec — switched to @param bindings. Always parameterize."
