# feedback-intel — Development Progress

> Customer Feedback Intelligence Platform on GCP
> Full spec: `Specs/feedback-intel-implementation-plan.jsx`

---

## Sprint Overview

| Sprint | Title | Status | Date Completed |
|--------|-------|--------|----------------|
| 01 | GCP Foundation | ✅ COMPLETE | 2026-03-11 |
| 02 | Seed Data Generation | 🔄 IN PROGRESS | — |
| 03 | Text Ingestion Pipeline | ⬚ Not Started | — |
| 04 | Chirp Speech-to-Text Pipeline | ⬚ Not Started | — |
| 05 | AI Classification Pipeline | ⬚ Not Started | — |
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

### Steps
- [ ] Write `data/generate_seed_data.py` — Gemini Flash generates realistic feedback in batches of 50
- [ ] Run it, verify CSV output (mix of sources, sentiments, realistic text)
- [ ] Upload CSV to `gs://feedback-intel-raw-data/`
- [ ] Write `data/generate_audio_calls.py` — Gemini creates dialogue scripts, Google TTS synthesizes WAV files
- [ ] Save ground truth JSON (for WER evaluation in Sprint 06)
- [ ] Upload WAV files to `gs://feedback-intel-audio-calls/`

### Done Criteria
- CSV with 2000 records in text bucket
- 30-50 WAV files in audio bucket
- Ground truth JSON saved locally (matches audio 1:1)
- Spot-check: 10 text entries look realistic, 2-3 WAV files sound like support calls

### Cost Estimate
- Gemini Flash for 2000 records: ~$0.50-1.00
- Google TTS for 30-50 calls: ~$1-2
- Total: ~$2-4 (covered by $300 free trial credits)

---

## Sprint 03 — Text Ingestion Pipeline

**Goal:** Cloud Function automatically loads CSV uploads into BigQuery.

### Steps
- [ ] Write Cloud Function (`ingestion/cloud_function/main.py` + `requirements.txt`)
- [ ] Deploy with Cloud Storage trigger on text bucket
- [ ] Upload seed CSV → watch it auto-trigger
- [ ] Query BigQuery to verify 2000 rows landed
- [ ] Upload a second small test CSV → verify incremental ingestion (not overwrite)

### Done Criteria
- Cloud Function deployed with GCS trigger
- 2000+ rows in `raw_feedback`
- Mix of ticket/review/survey sources
- Incremental upload works

---

## Sprint 04 — Chirp Speech-to-Text Pipeline

**Goal:** Audio files automatically transcribed via Chirp, stored in BigQuery. *Most critical sprint — JD emphasizes this heavily.*

### Steps
- [ ] Write `transcription/chirp_config.py` — Chirp 2 model, diarization (2-4 speakers), word timestamps, confidence
- [ ] Write transcription Cloud Function — Pub/Sub trigger, async batch recognition, BQ insert, error handling, move-to-processed
- [ ] Write `transcription/transcript_parser.py` — extract full text, speaker segments, word-level data, confidence
- [ ] Deploy with 540s timeout
- [ ] Test: single WAV file end-to-end trace
- [ ] Process all audio files
- [ ] Write transcript → classification bridge (feeds transcripts into `raw_feedback` as `source='call'`)

### Done Criteria
- All audio files transcribed with diarization + confidence
- `call_transcripts` table populated
- Processed audio archived in `feedback-intel-audio-processed`
- Transcripts bridged to classification pipeline
- Error handling: non-audio files skipped gracefully

---

## Sprint 05 — AI Classification Pipeline

**Goal:** All feedback (text + transcripts) classified by Gemini with structured output.

### Steps
- [ ] Write `classification/prompts.py` — V1 system prompt with classification rules
- [ ] Write `classification/classify_feedback.py` — batch processor, calls Gemini, writes enriched data
- [ ] Run classification on all records (2000 text + call transcripts)
- [ ] Inspect results: department distribution, confidence spread, text vs call quality

### Done Criteria
- All records classified in `enriched_feedback`
- Reasonable department distribution
- Materialized view `daily_summary` auto-refreshed
- Manual spot-check of 10 classifications

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
