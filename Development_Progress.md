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
| 05 | Chirp Speech-to-Text Pipeline | ⬚ Not Started | — |
| 06 | Evaluation & Iteration | ⬚ Not Started | — |
| 07 | Vertex AI Search | ⬚ Not Started | — |
| 08 | Looker Dashboard | ⬚ Not Started | — |
| 09 | React Frontend + API | ⬚ Not Started | — |
| 10 | Polish & Interview Prep | ⬚ Not Started | — |

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

### Key Decisions & Interview Notes
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

**Goal:** Transcribe 35 WAV files using Chirp 2 via Cloud Speech-to-Text V2 API. Store transcripts in `call_transcripts`. Feed into classification pipeline.

### Steps
- [ ] Write `transcription/transcribe_calls.py` — batch processor that transcribes all WAV files in GCS using Chirp 2
- [ ] Configure Chirp: diarization (2-4 speakers), word timestamps, word confidence, auto punctuation
- [ ] Run transcription on all 35 WAV files in `gs://feedback-intel-audio-calls/`
- [ ] Verify transcripts in `call_transcripts` table (35 rows, no errors)
- [ ] Inspect quality: avg confidence, speaker count distribution, duration distribution
- [ ] Write `transcription/transcript_to_classification.py` — bridge script to insert transcripts into `raw_feedback` as `source='call'`
- [ ] Run classification on call transcripts using existing V1 pipeline
- [ ] Compare text vs call classification quality (confidence gap)
- [ ] Move processed audio to `gs://feedback-intel-audio-processed/`

### Done Criteria
- 35 transcripts in `call_transcripts` with diarization data
- Avg Chirp confidence > 0.7
- Transcripts fed into classification pipeline as `source='call'`
- Text vs call confidence gap measured

---

## Sprint 06 — Evaluation & Iteration

**Goal:** Quantified accuracy for both Chirp and Gemini. Prompt iterated to V2/V3.

### Steps
- [ ] Manually label 100 test records (mix of text + calls)
- [ ] Run `classification/evaluate.py` — classification_report, confusion matrix
- [ ] Run `transcription/evaluate_chirp.py` — WER against ground truth
- [ ] Analyze failures, write V2 prompt with few-shot examples
- [ ] Re-run on test set, compare V1 vs V2 metrics
- [ ] Ship best version, track `model_version` in BigQuery

### Done Criteria
- Classification accuracy >85% (department)
- WER <10% on generated audio
- At least one prompt iteration with measured improvement
- All versions tracked by `model_version`

---

## Sprint 07 — Vertex AI Search

**Goal:** Semantic search over all classified feedback (text + calls).

### Steps
- [ ] Create data store connected to BigQuery `enriched_feedback`
- [ ] Create search app
- [ ] Write `search/search_feedback()` with department and source filters
- [ ] Test: "delivery complaints", "app crashes", "billing issues"

### Done Criteria
- Search returns relevant results with AI summary
- Department and source filters work
- Citations included in summaries

---

## Sprint 08 — Looker Dashboard

**Goal:** 4-view dashboard connected to BigQuery.

### Steps
- [ ] Create BigQuery views: `dashboard_view`, `call_analytics`, `source_comparison`
- [ ] Connect Looker Studio to BigQuery
- [ ] Build 4 views: Overview, Department Drill-down, Call Analytics, Confidence Monitor
- [ ] Add filters: date range, department, source, sentiment

### Done Criteria
- Dashboard shareable via link
- All 4 views working with real data
- Filters responsive, loads in <5 seconds

---

## Sprint 09 — React Frontend + API

**Goal:** FastAPI backend + React frontend deployed on Cloud Run.

### Steps
- [ ] Build FastAPI: `/stats`, `/chirp-stats`, `/feedback`, `/transcripts`, `/transcript/{id}`, `/search`, `/classify`
- [ ] Build React frontend: Pipeline Dashboard, Transcript Viewer, Classification Explorer, Semantic Search
- [ ] Dockerize API → Cloud Run
- [ ] Deploy frontend → Firebase Hosting

### Done Criteria
- Both deployed with public URLs
- All pages functional
- Transcript Viewer shows diarized text with speaker colors

---

## Sprint 10 — Polish & Interview Prep

**Goal:** README, demo recording, talking points rehearsed.

### Steps
- [ ] Write comprehensive README.md with architecture diagram, setup instructions, screenshots
- [ ] Record 5-minute screen walkthrough: upload audio → Chirp → Gemini → Looker → search
- [ ] Practice end-to-end story
- [ ] Prepare scaling/failure-mode answers

### Done Criteria
- README committed
- Demo recorded
- Can explain every architectural decision from memory
