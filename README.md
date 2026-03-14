# feedback-intel

**Customer Feedback Intelligence Platform on Google Cloud**

An end-to-end data + ML pipeline that ingests customer feedback from multiple channels (support tickets, app reviews, surveys, phone calls), transcribes audio with Google Chirp, classifies everything with Gemini, and surfaces insights through dashboards, semantic search, and a React frontend.

Built as an educational project to go deep on GCP's AI/ML stack. Every architectural decision is documented with the reasoning behind it — see [Documenting_Progress.md](Documenting_Progress.md).

---

## Quick Start (Local Development)

> **Prerequisites:** GCP project with billing enabled, `gcloud` CLI authenticated, Python 3.10+, Node.js 18+

### 1. GCP Foundation

```bash
# Sets up APIs, IAM, BigQuery dataset + tables, Cloud Storage buckets, Pub/Sub
bash gcloud_full_steps.sh
```

### 2. Data Pipeline (one-time setup)

```bash
pip install google-genai google-cloud-bigquery google-cloud-speech google-cloud-storage

# Generate seed data → transcribe audio → classify everything
python data/generate_seed_data.py
python data/generate_audio_calls.py
python transcription/transcribe_calls.py --skip-move
python transcription/transcript_to_classification.py
python classification/classify_feedback.py
```

### 3. Run Locally

```bash
# Terminal 1 — API (FastAPI on port 8000)
cd api && pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Terminal 2 — Frontend (Vite on port 5173)
cd frontend && npm install && npm run dev
```

Open [http://localhost:5173](http://localhost:5173) — dashboard, transcript viewer, explorer, and semantic search.

### 4. Streaming Pipeline (optional)

```bash
# Local test (batch mode — no Pub/Sub needed)
cd pipeline && pip install -r requirements.txt
python pipeline.py --local

# Production (Dataflow)
python pipeline.py --runner DataflowRunner --project feedback-intel-demo --region europe-west1
```

---

## Architecture

```
         CSV uploads              Audio files (WAV)
              │                         │
              ▼                         ▼
    ┌──────────────────┐    ┌────────────────────────┐
    │  Cloud Function   │    │  Chirp 3 (STT V2)       │
    │  (Gen2, GCS       │    │  batch_recognize +       │
    │   trigger)        │    │  speaker diarization     │
    └────────┬─────────┘    └──────────┬─────────────┘
             │                         │
             ▼                         ▼
      ┌────────────┐          ┌────────────────┐
      │raw_feedback │          │call_transcripts │
      │ (BigQuery)  │          │  (BigQuery)     │
      └──────┬─────┘          └───────┬────────┘
             │                        │
             └───────────┬────────────┘
                         ▼
              ┌─────────────────────┐
              │  Gemini 2.5 Flash   │
              │  Lite — structured  │
              │  JSON classification│
              └──────────┬──────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │ enriched_feedback    │
              │ (BigQuery)          │
              │ partitioned +       │
              │ clustered           │
              └──────────┬──────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
   Looker Studio   Vertex AI      React + FastAPI
   (BI dashboard)  Search (RAG)   (frontend + API)
```

### Streaming Path (Apache Beam)

```
  API/webhook → Pub/Sub → Beam Pipeline → BigQuery
                          (parse → validate → write)
                          DirectRunner (local) or
                          DataflowRunner (production)
```

Two ingestion patterns feed the same `raw_feedback` table:
- **Batch:** CSV upload → Cloud Function → BigQuery (event-driven, file-level)
- **Streaming:** Pub/Sub → Apache Beam → BigQuery (continuous, message-level)

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Speech-to-Text** | Chirp 3 via Cloud STT V2 | Speaker diarization, EU multi-region |
| **Classification** | Gemini 2.5 Flash Lite | Cheapest model, structured JSON output |
| **Data Warehouse** | BigQuery | Serverless, partitioned + clustered |
| **Batch Ingestion** | Cloud Functions Gen2 | Event-driven GCS trigger via Eventarc |
| **Stream Ingestion** | Apache Beam (Dataflow) | Distributed processing, runner portability |
| **Event Bus** | Pub/Sub | Decouples producers from consumers |
| **Object Storage** | Cloud Storage (EU) | Raw data, audio calls, processed audio |
| **Semantic Search** | Vertex AI Search | RAG-as-a-service with AI summaries |
| **BI Dashboard** | Looker Studio | BigQuery views, drag-and-drop |
| **Frontend** | React + Vite + Recharts | Pipeline dashboard, transcript viewer |
| **API** | FastAPI | Thin BigQuery wrapper, parameterized queries |

---

## What's in BigQuery

| Table/View | Rows | Description |
|------------|------|-------------|
| `raw_feedback` | 1,402 | All feedback: tickets, reviews, surveys, call transcripts |
| `call_transcripts` | 36 | Chirp 3 transcriptions with diarization + confidence |
| `enriched_feedback` | 1,402 | Classified: department, sentiment, tone, key issues |
| `daily_summary` | (mat. view) | Auto-refreshing aggregation for dashboards |
| `dashboard_view` | ~4,200 | UNNESTs key_issues array for Looker |
| `call_analytics` | (view) | Chirp pipeline health: success rate, avg confidence |
| `source_comparison` | 16 | Text vs calls by department |

**Partitioning**: `DATE(created_at)` on all tables.
**Clustering**: `enriched_feedback` by `department, sentiment, source`.

---

## Project Structure

```
feedback-intel/
├── api/                              # FastAPI backend (Sprint 10)
│   ├── main.py                       #   8 endpoints: stats, chirp, feedback, search
│   ├── Dockerfile                    #   Cloud Run deployment
│   └── requirements.txt
│
├── frontend/                         # React frontend (Sprint 10)
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx         #   Pipeline overview + charts
│   │   │   ├── Transcripts.jsx       #   Call transcript viewer
│   │   │   ├── Explorer.jsx          #   Filtered classification table
│   │   │   └── Search.jsx            #   Vertex AI semantic search
│   │   ├── components/Layout.jsx     #   Sidebar navigation
│   │   ├── api.js                    #   API client
│   │   └── index.css                 #   Dark theme
│   ├── package.json
│   └── vite.config.js
│
├── pipeline/                         # Apache Beam streaming (Sprint 08)
│   ├── pipeline.py                   #   Beam pipeline: parse → validate → BQ
│   ├── publish_feedback.py           #   Pub/Sub publisher for testing
│   └── requirements.txt
│
├── data/                             # Seed data generation (Sprint 02)
│   ├── generate_seed_data.py         #   Gemini → 1,967 feedback records
│   ├── generate_audio_calls.py       #   Gemini scripts + Chirp TTS → 35 WAVs
│   └── ground_truth/                 #   Ground truth for WER evaluation
│
├── ingestion/                        # Batch ingestion (Sprint 03)
│   └── cloud_function/main.py        #   GCS trigger → validate CSV → BigQuery
│
├── transcription/                    # Speech-to-text (Sprint 05)
│   ├── transcribe_calls.py           #   Chirp 3 batch + diarization
│   └── transcript_to_classification.py
│
├── classification/                   # AI classification (Sprint 04)
│   ├── classify_feedback.py          #   Gemini structured JSON output
│   └── prompts.py                    #   V1 → V2 → V3 prompt evolution
│
├── evaluation/                       # Pipeline evaluation (Sprint 06)
│   ├── evaluate_chirp.py             #   WER metrics
│   └── evaluate_classification.py    #   Accuracy, confidence analysis
│
├── search/                           # Semantic search (Sprint 07)
│   └── search_feedback.py            #   Vertex AI Search setup + query
│
├── gcloud_full_steps.sh              # Complete GCP setup script
├── Development_Progress.md           # Sprint checklist with metrics
├── Documenting_Progress.md           # Architectural decisions & lessons
├── Stakeholder_Demo_Guide.md         # 5-min walkthrough + Q&A reference
├── Apache_Dataflow.MD                # Beam/Dataflow educational reference
└── BQ_First_Contact.md               # BigQuery guide for SQL developers
```

---

## Key Design Decisions

**Chirp 3 over Chirp 2** — Chirp 2 has better word-level confidence but no speaker diarization. Chirp 3 adds diarization (critical for separating agent vs customer speech) at the cost of per-word metrics. Speaker separation enables cleaner downstream classification.

**Structured JSON from Gemini** — `response_mime_type="application/json"` forces valid JSON output. No regex parsing. Combined with `temperature=0.1` for near-deterministic classification.

**Pub/Sub for audio events** — GCS notifications route through Pub/Sub instead of direct triggers. If transcription is slow, messages queue and retry. Enables multiple subscribers without changing the event source.

**Beam over Cloud Functions for streaming** — Cloud Functions work for low-volume file uploads. Beam demonstrates distributed processing, windowing, and runner portability (DirectRunner locally, DataflowRunner in production).

**Parameterized SQL** — API uses BigQuery `@param` bindings, not f-string interpolation. Prevents SQL injection in the feedback endpoint.

**Regular views over materialized** — At 1,402 rows, query cost is effectively $0. Materialized views add storage cost and refresh complexity that isn't justified until the data grows.

---

## Development Timeline

| Sprint | What | Days |
|--------|------|------|
| 01 | GCP Foundation — project, BigQuery, Storage, Pub/Sub, IAM | Day 1 |
| 02 | Seed Data — 1,967 text records + 35 synthetic call recordings | Day 1 |
| 03 | Text Ingestion — GCS-triggered Cloud Function → BigQuery | Day 1 |
| 04 | NLP Classification — Gemini structured output, prompt V1-V3 | Day 1 |
| 05 | Speech-to-Text — Chirp 3 batch transcription + diarization | Day 1 |
| 06 | Evaluation — WER metrics, classification accuracy, prompt iteration | Day 2 |
| 07 | Vertex AI Search — semantic search with AI summaries | Day 3 |
| 08 | Apache Beam — streaming pipeline (Pub/Sub → Beam → BigQuery) | Day 3 |
| 09 | Looker Dashboard — BigQuery views for BI | Day 4 |
| 10 | React Frontend — FastAPI + React dashboard | Day 4 |
| 11 | Polish — README, documentation, demo guide | Day 4 |

---

## Lessons Learned

Detailed writeups in [Documenting_Progress.md](Documenting_Progress.md). Highlights:

- **IAM is always the problem.** Every GCP service requires the right SA with the right role. Error messages are vague. Document every grant.
- **BigQuery has opinions.** Partitioning specs are immutable. Streaming buffers block DML for 30 minutes. Learn the constraints upfront.
- **Beam is the code, Dataflow is the runtime.** Same `pipeline.py` runs locally (DirectRunner) or managed (DataflowRunner). The runner is a CLI flag.
- **GCP naming is counterintuitive.** `NO_CONTENT` means "structured fields," not "nothing to search." Read enum values, not names.
- **Spec code isn't production code.** The implementation plan had SQL injection. Always review before shipping.
- **Synthetic data has evaluation limits.** You can evaluate the pipeline (signal survival TTS→STT→classification) but not the classifier itself. Build the framework, don't fake metrics.

---

## License

MIT
