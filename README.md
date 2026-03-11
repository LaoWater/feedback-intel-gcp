# feedback-intel

**Customer Feedback Intelligence Platform on Google Cloud**

An end-to-end ML pipeline that ingests customer feedback from multiple channels (support tickets, reviews, surveys, phone calls), transcribes audio using Google Chirp, classifies everything with Gemini, and surfaces insights through dashboards and semantic search.

Built as a learning project to go deep on GCP's AI/ML stack — every architectural decision is documented with the reasoning behind it.

---

## Architecture

```
                          Cloud Storage (EU)
                    ┌──────────┴──────────┐
                    │                     │
              raw-data bucket        audio-calls bucket
              (CSV uploads)          (WAV files)
                    │                     │
                    ▼                     ▼
            ┌──────────────┐    ┌──────────────────┐
            │ Cloud Function│    │  Chirp 3 (STT V2) │
            │ (Gen2 + GCS  │    │  batch_recognize   │
            │  trigger)    │    │  + diarization     │
            └──────┬───────┘    └────────┬───────────┘
                   │                     │
                   ▼                     ▼
            ┌────────────┐       ┌───────────────┐
            │raw_feedback│◄──────│call_transcripts│
            │  (BigQuery) │       │   (BigQuery)   │
            └──────┬─────┘       └───────────────┘
                   │
                   ▼
         ┌─────────────────┐
         │  Gemini 2.5     │
         │  Flash Lite     │
         │  (structured    │
         │   JSON output)  │
         └────────┬────────┘
                  │
                  ▼
         ┌─────────────────┐
         │enriched_feedback │──► Looker Dashboard
         │   (BigQuery)     │──► Vertex AI Search
         │   partitioned +  │──► React Frontend
         │   clustered      │
         └─────────────────┘
```

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Speech-to-Text** | Chirp 3 via Cloud STT V2 | Speaker diarization, EU multi-region, latest accuracy |
| **Text Classification** | Gemini 2.5 Flash Lite | Cheapest model, structured JSON output, near-deterministic |
| **Data Warehouse** | BigQuery | Serverless, partitioned by date, clustered for fast filters |
| **Ingestion** | Cloud Functions Gen2 | Event-driven (GCS trigger via Eventarc), auto-scaling |
| **Event Bus** | Pub/Sub | Decouples audio upload events from transcription processing |
| **Object Storage** | Cloud Storage (EU) | Three buckets: raw data, audio calls, processed audio |
| **Search** | Vertex AI Search | Semantic search over classified feedback with AI summaries |
| **Dashboard** | Looker Studio | Connected to BigQuery materialized views |
| **Frontend** | React + FastAPI on Cloud Run | Pipeline dashboard, transcript viewer, search UI |
| **SDK** | google-genai | Current SDK (replaces deprecated vertexai.generative_models) |

## Project Structure

```
feedback-intel/
├── data/                          # Seed data generation
│   ├── generate_seed_data.py      #   Gemini generates 1967 feedback records
│   ├── generate_audio_calls.py    #   Gemini scripts + Chirp 3 HD TTS → 35 WAV files
│   ├── ground_truth/              #   Ground truth transcripts for WER evaluation
│   └── calls/                     #   Generated audio files (local copies)
│
├── ingestion/                     # Text ingestion pipeline
│   └── cloud_function/
│       └── main.py                #   GCS-triggered function → validates CSV → streams to BQ
│
├── transcription/                 # Speech-to-text pipeline
│   ├── transcribe_calls.py        #   Chirp 3 batch transcription with diarization
│   └── transcript_to_classification.py  # Bridges transcripts into classification pipeline
│
├── classification/                # AI classification pipeline
│   ├── classify_feedback.py       #   Gemini classifies: department, sentiment, tone, issues
│   └── prompts.py                 #   V1/V2/V3 system prompts (baseline → few-shot → transcript)
│
├── Specs/                         # Implementation plan (interactive React spec)
├── Development_Progress.md        # Sprint-by-sprint checklist with metrics
├── Documenting_Progress.md        # Architectural decisions, hiccups, lessons learned
└── BQ_First_Contact.md            # BigQuery guide for developers from PostgreSQL/MySQL
```

## What's in BigQuery

| Table | Rows | Description |
|-------|------|-------------|
| `raw_feedback` | 1,402 | All feedback — tickets, reviews, surveys, call transcripts |
| `call_transcripts` | 35 | Chirp 3 transcriptions with diarization segments |
| `enriched_feedback` | 1,402 | Gemini-classified: department, sentiment, tone, confidence |
| `daily_summary` | (view) | Auto-refreshing materialized view for dashboards |

**Partitioning**: All tables partitioned by `DATE(created_at)` — queries with date filters skip irrelevant blocks (cost + speed).

**Clustering**: `enriched_feedback` clustered by `department, sentiment, source` — the exact columns used in dashboard filters.

## Key Design Decisions

**Chirp 3 over Chirp 2** — Chirp 2 has better word-level metrics but doesn't support speaker diarization. Chirp 3 adds diarization (critical for separating agent vs customer speech) but drops word-level confidence. We chose speaker separation over per-word metrics because diarization enables cleaner downstream classification.

**Structured JSON output from Gemini** — Using `response_mime_type="application/json"` forces the model to return valid JSON. No regex parsing, no markdown stripping. Combined with `temperature=0.1` for near-deterministic classification. Every response is validated and clamped to known values.

**Pub/Sub for audio events** — GCS notifications go through Pub/Sub, not direct function triggers. If transcription is slow or down, messages queue and retry. Also enables multiple subscribers later (transcription, audio QA, archiving) without changing the event source.

**Streaming inserts vs batch loads** — Learned the hard way that streaming inserts block DML for ~30 minutes (buffer). Batch loads are free and support immediate mutations. For ETL pipelines, batch is almost always the right choice.

**Gen2 Cloud Functions** — These are Cloud Run + Eventarc + Pub/Sub stitched together. Deploying one requires an IAM chain across all three services. Documented the full 4-step permission chain after debugging each failure separately.

## Development Sprints

| Sprint | What | Status |
|--------|------|--------|
| 01 | GCP Foundation — project, BigQuery, Storage, Pub/Sub, IAM | Done |
| 02 | Seed Data — 1,967 text records + 35 synthetic call recordings | Done |
| 03 | Text Ingestion — GCS-triggered Cloud Function → BigQuery | Done |
| 04 | NLP Classification — Gemini structured output, prompt V1 | Done |
| 05 | Speech-to-Text — Chirp 3 batch transcription + diarization | Done |
| 06 | Evaluation — WER metrics, classification accuracy, prompt iteration | Next |
| 07 | Vertex AI Search — semantic search over all classified feedback | Planned |
| 08 | Looker Dashboard — 4-view BI dashboard on BigQuery views | Planned |
| 09 | React Frontend — FastAPI + React on Cloud Run | Planned |
| 10 | Polish — README, architecture diagram, demo recording | Planned |

## Lessons Learned (So Far)

Detailed writeups in [`Documenting_Progress.md`](Documenting_Progress.md). Highlights:

- **IAM is always the problem.** Every GCP service interaction requires the right service account with the right role. Error messages are vague. Document every grant.
- **BigQuery has opinions.** Partitioning specs are immutable on replace. JSON columns can't be compared with DISTINCT. Streaming buffers block DML. Learn the constraints upfront.
- **Model feature matrices matter.** Chirp 2 vs 3, Gemini Flash vs Flash Lite — each model has specific feature support. Don't assume a newer model supports everything the older one did.
- **LLM SDKs move fast.** The Vertex AI SDK we started with was already deprecated. Always check the latest docs before writing production code.

## Setup

### Prerequisites
- GCP project with billing enabled
- `gcloud` CLI authenticated
- Python 3.10+

### Quick Start

```bash
# Clone
git clone https://github.com/your-username/feedback-intel-gcp.git
cd feedback-intel-gcp

# Install dependencies (per module)
pip install -r data/requirements.txt
pip install -r classification/requirements.txt
pip install -r transcription/requirements.txt

# GCP foundation (APIs, BigQuery, Storage, Pub/Sub)
# See gcloud_full_steps.sh or Development_Progress.md Sprint 01

# Generate seed data
python data/generate_seed_data.py
python data/generate_audio_calls.py

# Transcribe audio
python transcription/transcribe_calls.py --skip-move

# Bridge transcripts → classification pipeline
python transcription/transcript_to_classification.py

# Classify all feedback
python classification/classify_feedback.py
```

## License

MIT
