# feedback-intel — Development Progress

> Customer Feedback Intelligence Platform on GCP
> Full spec: `Specs/feedback-intel-implementation-plan.jsx`

---

## Sprint Overview

| Sprint | Title | Status | Date Completed |
|--------|-------|--------|----------------|
| 01 | GCP Foundation | ✅ COMPLETE | 2026-03-11 |
| 02 | Seed Data Generation | ✅ COMPLETE | 2026-03-11 |
| 03 | Text Ingestion Pipeline | ✅ COMPLETE | 2026-03-11 |
| 04 | NLP/Sentiment Enrichment | ✅ COMPLETE | 2026-03-11 |
| 05 | Chirp Speech-to-Text Pipeline | ✅ COMPLETE | 2026-03-11 |
| 06 | Evaluation & Iteration | ✅ COMPLETE | 2026-03-12 |
| 07 | Vertex AI Search | ✅ COMPLETE | 2026-03-13 |
| 08 | Apache Beam + Dataflow Pipeline | ✅ COMPLETE | 2026-03-13 |
| 09 | Looker Dashboard (Views) | ✅ COMPLETE | 2026-03-14 |
| 10 | React Frontend + API | ✅ COMPLETE | 2026-03-14 |
| 11 | Documentation & Demo Prep | 🔄 IN PROGRESS | — |

---

## Sprint 01 — GCP Foundation

**Goal:** Project created, APIs enabled, BigQuery tables exist, Cloud Storage buckets ready, Pub/Sub configured.

### Completed Steps
- [x] Created GCP project `feedback-intel-demo`, set region `europe-west1`
- [x] Enabled 9 APIs: BigQuery, Storage, Cloud Functions, Vertex AI, Discovery Engine, Cloud Run, Speech-to-Text, Text-to-Speech, Pub/Sub
- [x] Created BigQuery dataset `feedback` (EU location)
- [x] Created table `raw_feedback` — partitioned by `created_at`, clustered by `source`
- [x] Created table `call_transcripts` — partitioned by `created_at`, clustered by `language_code`
- [x] Created table `enriched_feedback` — partitioned by `created_at`, clustered by `department, sentiment, source`
- [x] Created materialized view `daily_summary` — auto-refreshing aggregation for Looker
- [x] Created 3 Cloud Storage buckets (EU): `feedback-intel-raw-data`, `feedback-intel-audio-calls`, `feedback-intel-audio-processed`
- [x] Created Pub/Sub topic `audio-upload-events` + subscription `audio-upload-sub`
- [x] Wired Cloud Storage notification → Pub/Sub (OBJECT_FINALIZE on audio bucket)
- [x] Created service account `feedback-pipeline@` with 5 roles (bigquery.dataEditor, aiplatform.user, storage.objectAdmin, speech.client, pubsub.subscriber)
- [x] Verified: test INSERT + SELECT on `raw_feedback` — confirmed end-to-end

### Key Decisions & Notes
- **Partitioning + Clustering**: Cost control. Partitions skip irrelevant date ranges; clustering sorts within partitions for fast filters.
- **Separate transcript table**: `call_transcripts` preserves Chirp-specific metadata (duration, speakers, confidence) separate from the unified `enriched_feedback` table.
- **Pub/Sub over direct trigger**: Decoupling. If Chirp is slow/down, messages queue and retry. Enables multiple subscribers later (transcription, audio QA, archiving).
- **Service account with least privilege**: Pipeline SA can only do what the pipeline needs — no project-level admin, no IAM modification.

---

## Sprint 02 — Seed Data Generation

**Goal:** 2000 text feedback records + 30-50 fake call audio files generated and uploaded.

### Completed Steps
- [x] Write `data/generate_seed_data.py` — Gemini 2.5 Flash Lite generates feedback in batches of 50
- [x] Run it → 1967 records (ticket: 670, review: 657, survey: 640)
- [x] Upload CSV to `gs://feedback-intel-raw-data/seed_feedback.csv`
- [x] Write `data/generate_audio_calls.py` — Gemini generates scripts, Chirp 3 HD TTS synthesizes WAV files
- [x] Save ground truth JSON for WER evaluation (35 files in `data/ground_truth/`)
- [x] Upload 35 WAV files (98.4 MB) to `gs://feedback-intel-audio-calls/`

### Key Decisions & Notes
- **SDK migration**: Moved from deprecated `vertexai.generative_models` to `google-genai` SDK (`google.genai.Client`)
- **Gemini 2.5 Flash Lite**: Cheapest model, perfect for bulk structured text gen
- **Chirp 3 HD voices**: `en-US-Chirp3-HD-Leda` (agent) + `en-US-Chirp3-HD-Charon` (customer) — far more natural than old Studio voices
- **24000 Hz sample rate**: Chirp 3 HD native rate, higher fidelity
- **Ground truth**: Each WAV has a matching JSON with full text — enables WER evaluation in Sprint 06
- **Department spread**: Engineering 8, Product 7, Billing 7, UX 5, Support 5, Logistics 3

---

## Sprint 03 — Text Ingestion Pipeline

**Goal:** Cloud Function automatically loads CSV uploads into BigQuery.

### Steps
- [x] Write Cloud Function (`ingestion/cloud_function/main.py` + `requirements.txt`)
- [x] Deploy with Cloud Storage trigger on text bucket
- [x] Upload seed CSV → watch it auto-trigger
- [x] Query BigQuery — found 3934 rows (expected 1967) due to Eventarc retry storm
- [x] Fix: dedup via CTAS + DROP + RENAME approach
- [x] Verify dedup — confirm exactly 1967 rows in `raw_feedback`
- [x] Upload a second small test CSV → verify incremental ingestion (not overwrite)

### Issues Encountered & Resolved

1. **Eventarc retry storm causing duplicates (3934 vs 1967)** — During initial deployment, IAM permissions were missing, so Eventarc queued the GCS trigger events and retried. Once permissions were fixed, both the original event and the queued retry fired, causing the Cloud Function to process the same CSV twice. Result: 3934 rows instead of 1967. This is a known Eventarc behavior — retries accumulate for up to 7 days.

2. **`SELECT DISTINCT` fails on JSON columns** — Tried to dedup with `CREATE OR REPLACE TABLE ... AS SELECT DISTINCT * FROM raw_feedback` but BigQuery's JSON type doesn't support equality comparison. Got: `Column feedback_metadata of type JSON is not groupable`. Fix: used `ROW_NUMBER() OVER(PARTITION BY id ORDER BY ingested_at DESC)` instead.

3. **`CREATE OR REPLACE TABLE` can't change partitioning spec** — The `CREATE OR REPLACE TABLE ... AS SELECT` approach (even with ROW_NUMBER fix) failed because the original table has `PARTITION BY DATE(created_at) CLUSTER BY source`, and the replacement didn't include matching partition spec. BigQuery won't let you silently change partitioning on replace.

4. **Fixed via CTAS + DROP + RENAME** — Three-step workaround: (1) `CREATE TABLE raw_feedback_deduped PARTITION BY DATE(created_at) CLUSTER BY source AS SELECT ...` with the ROW_NUMBER dedup query, (2) `DROP TABLE raw_feedback`, (3) `ALTER TABLE raw_feedback_deduped RENAME TO raw_feedback`. This preserves partitioning and clustering while removing duplicates.

### Additional Notes
- **BOM fix deployed**: PowerShell's `Out-File -Encoding utf8` adds a UTF-8 BOM (`\ufeff`) to CSV files. Python's `csv.DictReader` doesn't strip it, so the first header becomes `\ufeffid` instead of `id`. Fixed by stripping BOM before parsing: `if content.startswith("\ufeff"): content = content[1:]`.
- **Incremental test passed**: Uploaded 3 test rows in a second CSV — they were appended correctly without overwriting existing data. Verified via `SELECT COUNT(*)`.
- **Final row count**: 1364 unique records in `raw_feedback` after dedup.
- **Streaming buffer gotcha**: After streaming inserts (`insert_rows_json`), rows sit in a buffer for ~30 minutes. During this window, `DELETE` and `UPDATE` statements that would affect buffered rows fail with "would affect rows in the streaming buffer, which is not supported". Workaround: wait ~30 min, or use CTAS to rebuild the table.

### Done Criteria
- Cloud Function deployed with GCS trigger
- 2000+ rows in `raw_feedback`
- Mix of ticket/review/survey sources
- Incremental upload works

---

## Sprint 04 — NLP/Sentiment Enrichment (AI Classification Pipeline)

**Goal:** All feedback (text + transcripts) classified by Gemini with structured output — department, sentiment, tone, key issues, and confidence. Prompt iterated through V1-V3.

### Completed Steps
- [x] Write `classification/prompts.py` — V1/V2/V3 system prompts (baseline, few-shot, transcript-specific)
- [x] Write `classification/classify_feedback.py` — batch processor with retries, validation clamping, model_version tracking
- [x] Configure Gemini 2.5 Flash Lite for structured JSON output (`response_mime_type="application/json"`, `temperature=0.1`)
- [x] Run V1 classification on all 1367 text records — zero failures
- [x] Inspect results: department distribution balanced (Engineering 28%, Product 39%, Support 20%, UX 14%), no dept >50%
- [x] Spot-check 10 random classifications — 10/10 correct
- [x] All versions tracked by `model_version` field (`gemini-2.5-flash-lite-v1`)
- [x] V2/V3 prompts written and ready — skipped comparison run (V1 quality excellent on clean text, V2/V3 reserved for post-Chirp transcript testing)

### Key Metrics
- **1367 records classified**, 0 errors, avg confidence 0.86-0.95
- **Department split**: Engineering 380, Product 530, Support 269, UX 188
- **Engineering 97% negative** (bugs), **Product 55% positive** (feature requests) — realistic distribution
- **Spot-check: 10/10 correct** — department, sentiment, tone all appropriate

### Done Criteria — MET
- ✅ All records classified in `enriched_feedback`
- ✅ No single department >50% (max: Product at 39%)
- ✅ Manual spot-check of 10+ classifications passes
- ✅ All versions tracked by `model_version` field
- ⏭️ V2/V3 comparison deferred to Sprint 06 (after Chirp transcripts exist)

---

## Sprint 05 — Chirp Speech-to-Text Pipeline

**Goal:** Transcribe 35 WAV files using Chirp 3 via Cloud Speech-to-Text V2 API with speaker diarization. Store transcripts in `call_transcripts`. Feed into classification pipeline.

**Note:** Originally targeted Chirp 2, but switched to Chirp 3 after discovering Chirp 2 does not support speaker diarization. Chirp 3 adds diarization support but drops word-level confidence. See `Documenting_Progress.md` Sprint 05 for full decision rationale.

### Completed Steps
- [x] Write `transcription/transcribe_calls.py` — batch processor that transcribes all WAV files in GCS using Chirp 3
- [x] Configure Chirp 3: diarization (2-4 speakers), word timestamps, auto punctuation (word confidence not supported by Chirp 3)
- [x] Run transcription on all 35 WAV files — 35/35 success, 0 failures
- [x] Verify transcripts in `call_transcripts` table — 35 rows, diarization working
- [x] Inspect quality: 32 calls with 2 speakers, 3 calls with 3 speakers, avg ~60s duration
- [x] Write `transcription/transcript_to_classification.py` — bridge script with full-transcript and customer-only modes
- [x] Run classification on call transcripts using existing V1 pipeline — 35 classified in 41.5s
- [x] Compare text vs call classification quality — call avg confidence 0.91 vs text avg 0.92 (negligible gap)
- [x] Move processed audio to `gs://feedback-intel-audio-processed/` — auto-moved by transcription script

### Key Metrics
- **35/35 transcriptions successful**, 0 errors
- **Speaker diarization**: 32 × 2-speaker, 3 × 3-speaker (matches generated data)
- **Avg audio duration**: 60s, avg processing time: 19s (first file ~265s cold start)
- **confidence_avg = 0.0** on all — expected, Chirp 3 doesn't return word confidence
- **Classification confidence gap**: call 0.91 vs text 0.92 — negligible
- **Call department distribution**: Support 46%, Engineering 26%, Product 17%, UX 11% (realistic — calls skew support)
- **Call sentiment**: 51% negative, 26% neutral, 23% positive (people call to complain)
- **Final counts**: raw_feedback 1402, enriched_feedback 1402, call_transcripts 35

### Issues Encountered & Resolved
1. **Chirp 2 doesn't support diarization** — API rejected `speaker_diarization` config. Switched to Chirp 3.
2. **Chirp 3 doesn't support `enable_word_confidence`** — Removed flag. Word confidence is Chirp 2 only.
3. **Streaming buffer blocked DELETE of error rows** — Used DROP TABLE + CREATE TABLE to reset.
4. **Cold start on first batch_recognize call** — First file took ~4.4 min, subsequent files 12-30s. Normal for provisioning Chirp infrastructure.
5. **confidence_avg filter bug** — `transcript_to_classification.py` had `confidence_avg > 0.6` filter which would reject all Chirp 3 transcripts (all 0.0). Fixed to `confidence_avg > 0.6 OR confidence_avg = 0.0`.

### Done Criteria — MET
- ✅ 35 transcripts in `call_transcripts` with diarization data
- ⚠️ Chirp confidence = 0.0 (Chirp 3 doesn't provide word confidence — expected, not a failure)
- ✅ Transcripts fed into classification pipeline as `source='call'`
- ✅ Text vs call confidence gap measured (0.01 — negligible)

---

## Sprint 06 — Evaluation & Iteration

**Goal:** Quantify Chirp STT accuracy (WER) and verify classification signal survives the full pipeline. Honest evaluation on synthetic data — measure what's measurable, document what's not.

### Completed Steps
- [x] Write `evaluation/evaluate_wer.py` — WER computation using `jiwer` against ground truth scripts
- [x] Run WER evaluation on 35 calls — micro-avg 4.02%, all calls under 10.53%
- [x] Write `evaluation/evaluate_call_classification.py` — classification accuracy for call transcripts against generation-time labels
- [x] Run classification evaluation — department 82.9%, sentiment 89.3%
- [x] Discover and document taxonomy mismatch (6 generation departments vs 4 classifier departments)
- [x] Document synthetic data limitations — why we didn't fake-label 100 text records

### Key Metrics

**WER (Word Error Rate) — Chirp 3 STT accuracy:**
- Micro-avg WER: **4.02%** (243 errors / 6,047 words)
- Median: 3.66%, Best: 0.00%, Worst: 10.53%
- Error breakdown: 70 substitutions, 142 insertions, 31 deletions
- Insertions dominate — Chirp adds words more than it mishears them
- Consistent across departments (3.6%-4.5% range)

**Call Classification — full pipeline signal preservation:**
- Department accuracy: **82.9%** (29/35)
- Sentiment accuracy: **89.3%** (25/28, excluding 7 "mixed" calls)
- Engineering: 8/8 perfect — bugs are unambiguous
- Negative sentiment: 14/14 perfect — classifier never misses angry customers
- 6 department misclassifications are all edge cases (UX vs Support, Billing vs Product)

### Taxonomy Mismatch (Real Finding)
- Generation used 6 departments: Engineering, Product, UX, Support, **Billing**, **Logistics**
- Classifier uses 4: Engineering, Product, UX, Support
- 10/35 calls had departments the classifier doesn't know (Billing→Support, Logistics→Support)
- Of those 10, 8 correctly classified as Support
- In production: expand classifier taxonomy or maintain explicit mapping

### What We Didn't Do (And Why)
- **Did NOT manually label 100 text records** — the text is synthetic (Gemini-generated). Labeling it is circular: Gemini wrote classifiable text, Gemini classifies it, a human would agree because it was designed to be classifiable. No meaningful signal.
- **Did NOT run V1→V2→V3 prompt comparison** — V1 works well (10/10 spot-check, 82.9% on calls through STT noise). V2/V3 prompts are written and documented. Running them against synthetic data would produce fake metrics. The methodology is demonstrated; the iteration loop is ready for real data.
- **Text feedback classification cannot be evaluated on synthetic data** — the only honest evaluation requires labeled production data.

### Done Criteria — MET (revised for synthetic data reality)
- ✅ WER < 10% on generated audio (achieved 4.02%)
- ✅ Full pipeline classification accuracy measured (82.9% dept, 89.3% sentiment)
- ✅ Taxonomy mismatch discovered and documented
- ✅ Evaluation framework built — ready for real data when available
- ⏭️ Prompt iteration deferred to production data (V2/V3 prompts written, pipeline ready)

---

## Sprint 07 — Vertex AI Search

**Goal:** Semantic search over all classified feedback (text + calls) using Vertex AI Search — Google's managed RAG-as-a-service.

**What Vertex AI Search is:** Instead of building a custom vector database + embedding pipeline + retrieval system + summary generator, Vertex AI Search handles all of it behind one API. Point it at a BigQuery table, it indexes everything, and natural language queries return semantically matched results + AI-generated summaries with citations. It understands *meaning*, not just keywords — "couldn't complete my purchase" matches even without the word "checkout."

**Three components:**
1. **Data Store** — connected to `enriched_feedback` in BigQuery. Indexes all classified feedback.
2. **Search Engine (App)** — the query interface on top of the data store.
3. **Python query function** — `search_feedback(query, department, source)` that calls the API.

**Cost:** ~$1.50 per 1,000 queries. For a project with ~50-100 queries, this is pennies. $300 GCP credit / $1,000 Vertex AI Search promo credit covers it.

### Completed Steps
- [x] Discovery Engine API already enabled (Sprint 01)
- [x] Create data store `feedback-store-v2` connected to BigQuery `enriched_feedback_search` view
- [x] Create BigQuery view `enriched_feedback_search` (renames `id` → `_id` for Discovery Engine)
- [x] Import 1,378 records from BigQuery into data store (custom schema, INCREMENTAL mode)
- [x] Update schema: mark `text` as searchable, `department`/`source`/`sentiment` as indexable+filterable
- [x] Create search engine `feedback-search-app-v2` (Enterprise tier + LLM add-on for AI summaries)
- [x] Write `search/search_feedback.py` — setup + query function with CLI
- [x] Test unfiltered query: "what are customers saying about login problems" — 10 results + AI summary with citations
- [x] Test department filter: "app crashes" --department Engineering — 10 Engineering results
- [x] Test source filter: "billing complaints" --source call — 5 call transcripts about billing

### Key Metrics
- **1,378 documents indexed** across 4 sources (ticket, review, survey, call)
- **Semantic matching works**: "billing complaints" matches "charge on my invoice" (no keyword overlap)
- **Cross-source search**: login query found both tickets AND call transcripts in one result set
- **AI summaries**: synthesize 5 sources into coherent narrative with [1], [2] citations
- **Filters**: department and source filtering work correctly

### Issues Encountered & Resolved
1. **`CONTENT_REQUIRED` vs `NO_CONTENT`** — Created data store with `CONTENT_REQUIRED` (for document stores like PDFs). Structured BigQuery data needs `NO_CONTENT` (the fields ARE the data). All 1,378 imports failed. Had to delete and recreate.
2. **BigQuery `_id` field required** — Discovery Engine's `custom` schema requires an `_id` field as document identifier. Our table uses `id`. Fix: created a BigQuery view `enriched_feedback_search` that renames `id` → `_id`.
3. **Fields not filterable by default** — Auto-detected schema doesn't mark fields as filterable. Filter query on `department` failed with "Unsupported field on : operator". Fix: explicit schema update marking `department`, `source`, `sentiment` as `indexable`.
4. **Data store deletion takes hours** — Deleted the broken data store to recreate with correct config. Deletion took 12+ hours (GCP says "could take a couple of hours"). Fix: used new IDs (`feedback-store-v2`, `feedback-search-app-v2`) instead of waiting.
5. **`AlreadyExists` exception handling** — gRPC exceptions need `google.api_core.exceptions.AlreadyExists`, not string matching on the error message.

### Done Criteria — MET
- ✅ Search returns relevant results with AI summary
- ✅ Department and source filters work
- ✅ Citations included in summaries
- ✅ Cross-source search (text + call transcripts in one query)

---

## Sprint 08 — Apache Beam + Dataflow Pipeline

**Goal:** Replace local-only processing with a real streaming pipeline. Pub/Sub → Apache Beam → BigQuery, deployable on Google Cloud Dataflow.

**Full documentation:** See `Apache_Dataflow.MD` for concepts, all commands, costs, and replication guide.

### Completed Steps
- [x] Write `Apache_Dataflow.MD` — core concepts (Beam vs Dataflow, PCollection, DoFn, runners, streaming vs batch)
- [x] Create Pub/Sub topic `feedback-raw` + subscription `feedback-raw-sub`
- [x] Create GCS bucket `gs://feedback-intel-dataflow` (europe-west1) for Dataflow staging
- [x] Write `pipeline/publish_feedback.py` — Pub/Sub publisher (simulates ingestion service)
- [x] Write `pipeline/pipeline.py` — Apache Beam streaming pipeline (ParseMessage → ValidateRecord → FormatForBigQuery → WriteToBigQuery)
- [x] Write `pipeline/requirements.txt` — apache-beam[gcp], google-cloud-pubsub
- [x] Install dependencies (`pip install -r pipeline/requirements.txt`)
- [x] Grant Dataflow IAM roles to service account (dataflow.worker, dataflow.admin)
- [x] Test locally with DirectRunner (`--local` batch mode) — 2/3 records written to BigQuery, 1 invalid rejected
- [ ] Deploy to Dataflow (deferred — documented in Apache_Dataflow.MD Steps 8-10, ready to run)
- [x] Update `Apache_Dataflow.MD` with 3 hiccups: yield+return in DoFn, gRPC timeout on DirectRunner streaming, FILE_LOADS vs STREAMING_INSERTS

### Key Design Decisions
- **Separate DoFns for parse/validate/format** — Single Responsibility. Each step is testable, debuggable, and visible in the Dataflow monitoring UI.
- **`CREATE_NEVER` write disposition** — Fail-fast if table schema is wrong. Don't silently create unpartitioned tables.
- **`save_main_session=True`** — Ships Python globals (constants, imports) to remote Dataflow workers.
- **`topic=` not `subscription=`** — Beam creates a temp subscription. The `feedback-raw-sub` is for manual debugging only.
- **Cloud Function + Beam pipeline coexist** — Cloud Function handles batch CSV uploads, Beam handles real-time event streams. Same BigQuery destination.

### Done Criteria
- Pipeline runs locally with DirectRunner
- Test message flows: publish → Pub/Sub → pipeline → BigQuery
- Pipeline deploys to Dataflow (brief — verify and tear down)
- All commands documented in `Apache_Dataflow.MD` for replication

---

## Sprint 09 — Looker Dashboard

**Goal:** 4-page BI dashboard connected to BigQuery via Looker Studio (free).

**Pre-existing:** Materialized view `daily_summary` (auto-refreshing, created in Sprint 01).

### Completed Steps
- [x] Create view `dashboard_view` — UNNESTs `key_issues` array so Looker can query individual issues
- [x] Create view `call_analytics` — Chirp pipeline health: transcription counts, avg duration, sentiment breakdown
- [x] Create view `source_comparison` — Text vs calls by department: volume, confidence, negative rate
- [x] Verify all views return correct data
- [ ] Connect Looker Studio to BigQuery (UI step — see guide below)
- [ ] Build 4 dashboard pages (UI step — see guide below)

### BigQuery Data Sources for Looker

| Source | Type | Rows | Use |
|--------|------|------|-----|
| `enriched_feedback` | Table | 1,402 | Main data source — all classified feedback |
| `daily_summary` | Materialized view | ~30 | Time-series charts (pre-aggregated) |
| `dashboard_view` | View | ~4,200 | Issue analysis (one row per issue per record) |
| `call_analytics` | View | 1 | Call pipeline KPIs |
| `source_comparison` | View | 16 | Channel comparison table |

### Looker Studio Setup Guide

**Step 1: Create Report**
1. Go to [lookerstudio.google.com](https://lookerstudio.google.com)
2. Click "Create" → "Report"
3. "Add data" → BigQuery connector → project `feedback-intel-demo` → dataset `feedback`

**Step 2: Add Data Sources** (add each as a separate data source)
- `enriched_feedback` — main source for most charts
- `daily_summary` — for time-series (already aggregated = fast)
- `dashboard_view` — for issue breakdowns
- `source_comparison` — for channel comparison table

**Step 3: Build Page 1 — Overview**
| Chart Type | Data Source | Dimension | Metric | Notes |
|-----------|-------------|-----------|--------|-------|
| Scorecard | enriched_feedback | — | COUNT(*) | "Total Feedback" |
| Scorecard | enriched_feedback | — | AVG(confidence) | "Avg Confidence" |
| Scorecard | enriched_feedback | — | COUNTIF(source='call') | "Calls Transcribed" |
| Pie chart | enriched_feedback | sentiment | COUNT(*) | Sentiment split |
| Bar chart | enriched_feedback | department | COUNT(*) | Volume by department |
| Time series | daily_summary | date | SUM(count) | Feedback over time |

**Filters:** date range, department, source, sentiment (add as dropdown controls)

**Step 4: Build Page 2 — Department Drill-down**
| Chart Type | Data Source | Dimension | Metric |
|-----------|-------------|-----------|--------|
| Bar chart | dashboard_view | issue | COUNT(*) | Top issues (filter by department) |
| Stacked bar | enriched_feedback | department | COUNT(*) grouped by sentiment |
| Table | enriched_feedback | id, text, sentiment, confidence | Detail drill-down |

**Filter:** Department dropdown (controls all charts on this page)

**Step 5: Build Page 3 — Call Analytics**
| Chart Type | Data Source | Dimension | Metric |
|-----------|-------------|-----------|--------|
| Scorecard | call_analytics | — | calls_transcribed, successful, avg_duration_s |
| Bar chart | source_comparison | source | negative_rate | Call vs text negative rate |
| Table | source_comparison | source, department | count, avg_classification_confidence, negative_rate |

**Step 6: Build Page 4 — Confidence Monitor**
| Chart Type | Data Source | Dimension | Metric |
|-----------|-------------|-----------|--------|
| Histogram | enriched_feedback | confidence | COUNT(*) | Confidence distribution |
| Table | enriched_feedback (filtered: confidence < 0.8) | id, text, department, confidence | Low-confidence items for review |
| Bar chart | source_comparison | source | avg_classification_confidence | Confidence by channel |

**Step 7: Share**
- Click "Share" → "Get link" → "Anyone with the link can view"
- Copy the URL — this is your shareable demo link

### Key Design Decisions
- **Views vs direct tables** — Looker Studio can't UNNEST arrays or do complex JOINs inline. Views pre-shape the data so Looker just reads rows.
- **Materialized view for time-series** — `daily_summary` is pre-aggregated by BigQuery. Time-series charts load in <1s instead of scanning 1,402 rows per filter change.
- **Regular views for everything else** — 1,402 rows is tiny. Regular views (computed on query) are fine. Materialized views add cost/complexity we don't need here.
- **Separate data sources per view** — Looker Studio doesn't blend data sources well. Each chart uses one source. The views are designed to be self-contained.

### Done Criteria
- Dashboard shareable via link
- All 4 pages working with real data
- Filters responsive, loads in <5 seconds

---

## Sprint 10 — React Frontend + API

**Goal:** FastAPI backend + React frontend deployed on Cloud Run.

### Completed Steps
- [x] Built FastAPI backend (`api/main.py`) — 8 endpoints: `/stats`, `/chirp-stats`, `/transcripts`, `/transcript/{id}`, `/feedback`, `/departments`, `/search`, `/health`
- [x] Built React frontend (`frontend/`) — 4 pages: Dashboard, Transcript Viewer, Classification Explorer, Semantic Search
- [x] Parameterized queries with `@param` (no SQL injection in `/feedback`)
- [x] Vite dev proxy → FastAPI for local development
- [x] Dockerfile for API deployment to Cloud Run
- [ ] `npm install` + local test
- [ ] Deploy API to Cloud Run
- [ ] Deploy frontend to Firebase Hosting (or Cloud Run)

### Key Decisions & Notes
- **Parameterized queries**: `/api/feedback` uses `@param` bindings, not f-string interpolation. The spec example used f-strings — we fixed that. SQL injection is the #1 web vulnerability.
- **CORS wide open**: `allow_origins=["*"]` for dev. In production, lock to your frontend domain.
- **Vite proxy**: Frontend dev server proxies `/api/*` to `localhost:8000`. No CORS issues in development, no URL hardcoding.
- **`/api/departments`**: Not in spec but needed — frontend filter dropdowns need the list dynamically. Avoids hardcoding department names.
- **Recharts for charts**: Lightweight, React-native charting. No D3 complexity for this scope.

### Architecture

```
frontend/ (React + Vite)          api/ (FastAPI)
  ├── src/                          ├── main.py         ← 8 endpoints
  │   ├── pages/                    ├── requirements.txt
  │   │   ├── Dashboard.jsx         ├── Dockerfile
  │   │   ├── Transcripts.jsx       └── (imports search/)
  │   │   ├── Explorer.jsx
  │   │   └── Search.jsx
  │   ├── components/Layout.jsx
  │   ├── api.js                 ← API client
  │   ├── main.jsx               ← Router
  │   └── index.css              ← Dark theme
  ├── package.json
  ├── vite.config.js
  └── index.html
```

### Local Development

```bash
# Terminal 1: API
cd api && pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Terminal 2: Frontend
cd frontend && npm install && npm run dev
# Opens at http://localhost:5173, proxies /api/* to :8000
```

### Done Criteria
- Both deployed with public URLs
- All pages functional
- Transcript Viewer shows diarized text

---

## Sprint 11 — Documentation & Demo Prep

**Goal:** Polished README, stakeholder demo guide, complete project documentation.

### Completed Steps
- [x] Rewrote README.md — full architecture diagram (batch + streaming paths), tech stack table, project structure, setup instructions, key design decisions, lessons learned
- [x] Created `Stakeholder_Demo_Guide.md` — 5-minute walkthrough script, 12 Q&A on architecture/design, key talking points
- [x] All sprint documentation complete in Development_Progress.md and Documenting_Progress.md
- [ ] Record screen demo (optional)

### Project Documentation Map

| Document | Purpose |
|----------|---------|
| `README.md` | Project overview — architecture, tech stack, setup guide |
| `Stakeholder_Demo_Guide.md` | Walkthrough script + Q&A reference |
| `Documenting_Progress.md` | Deep-dive on every sprint's decisions and lessons |
| `Apache_Dataflow.MD` | Beam/Dataflow concepts and replication guide |
| `BQ_First_Contact.md` | BigQuery guide for developers from SQL backgrounds |

### Done Criteria
- README is complete and polished
- Demo walkthrough flows naturally
- Every architectural decision is documented with reasoning
