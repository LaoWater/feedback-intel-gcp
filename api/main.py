"""
Sprint 10 — FastAPI backend for Feedback Intel.

7 endpoints exposing BigQuery data + Vertex AI Search.
Designed for the React frontend (Pipeline Dashboard, Transcript Viewer,
Classification Explorer, Semantic Search).

Run locally:
    cd api && uvicorn main:app --reload --port 8000

Deploy:
    See Dockerfile + Cloud Run instructions in Development_Progress.md
"""

import os
import sys

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import bigquery

# Add project root to path so we can import search module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

app = FastAPI(
    title="Feedback Intel API",
    description="Customer Feedback Intelligence — GCP Portfolio Project",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

bq = bigquery.Client()

PROJECT = "feedback-intel-demo"
DATASET = "feedback"


# ─── 1. Overview Stats ────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats():
    """Pipeline overview — total records, sentiment split, confidence."""
    query = f"""
    SELECT
      COUNT(*) as total,
      COUNTIF(sentiment = 'negative') as negative,
      COUNTIF(sentiment = 'positive') as positive,
      COUNTIF(sentiment = 'neutral') as neutral,
      COUNTIF(source = 'call') as from_calls,
      COUNTIF(source != 'call') as from_text,
      ROUND(AVG(confidence), 3) as avg_confidence,
      COUNTIF(confidence < 0.7) as low_confidence
    FROM `{DATASET}.enriched_feedback`
    """
    row = next(bq.query(query).result())
    return dict(row)


# ─── 2. Chirp Pipeline Stats ──────────────────────────────────────

@app.get("/api/chirp-stats")
async def get_chirp_stats():
    """Chirp STT pipeline health — success rate, confidence, timing."""
    query = f"""
    SELECT
      COUNT(*) as total_calls,
      COUNTIF(error_message IS NULL) as successful,
      COUNTIF(error_message IS NOT NULL) as failed,
      ROUND(AVG(confidence_avg), 3) as avg_confidence,
      ROUND(AVG(duration_seconds), 1) as avg_duration_sec,
      ROUND(AVG(processing_time_ms), 0) as avg_processing_ms
    FROM `{DATASET}.call_transcripts`
    """
    row = next(bq.query(query).result())
    return dict(row)


# ─── 3. List Transcripts ──────────────────────────────────────────

@app.get("/api/transcripts")
async def list_transcripts(limit: int = Query(default=20, le=100)):
    """Recent call transcripts with classification metadata."""
    query = f"""
    SELECT
      t.id, t.audio_file_uri,
      SUBSTR(t.transcript_full, 1, 200) as transcript_preview,
      t.speaker_count, t.duration_seconds,
      t.confidence_avg, t.transcribed_at,
      e.department, e.sentiment, e.tone
    FROM `{DATASET}.call_transcripts` t
    LEFT JOIN `{DATASET}.enriched_feedback` e ON t.id = e.id
    WHERE t.error_message IS NULL
    ORDER BY t.transcribed_at DESC
    LIMIT {limit}
    """
    return [dict(row) for row in bq.query(query).result()]


# ─── 4. Transcript Detail ─────────────────────────────────────────

@app.get("/api/transcript/{transcript_id}")
async def get_transcript_detail(transcript_id: str):
    """Full transcript with word-level data + classification."""
    query = f"""
    SELECT
      t.*,
      e.department, e.sentiment, e.tone, e.key_issues, e.confidence
    FROM `{DATASET}.call_transcripts` t
    LEFT JOIN `{DATASET}.enriched_feedback` e ON t.id = e.id
    WHERE t.id = @id
    """
    cfg = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("id", "STRING", transcript_id)
        ]
    )
    row = next(bq.query(query, job_config=cfg).result(), None)
    if not row:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return dict(row)


# ─── 5. List Feedback ─────────────────────────────────────────────

@app.get("/api/feedback")
async def list_feedback(
    department: str = None,
    sentiment: str = None,
    source: str = None,
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    limit: int = Query(default=50, le=200),
):
    """Filtered feedback list — powers the Classification Explorer."""
    conditions = ["1=1"]
    params = []

    if department:
        conditions.append("department = @department")
        params.append(bigquery.ScalarQueryParameter("department", "STRING", department))
    if sentiment:
        conditions.append("sentiment = @sentiment")
        params.append(bigquery.ScalarQueryParameter("sentiment", "STRING", sentiment))
    if source:
        conditions.append("source = @source")
        params.append(bigquery.ScalarQueryParameter("source", "STRING", source))
    if min_confidence > 0:
        conditions.append("confidence >= @min_conf")
        params.append(bigquery.ScalarQueryParameter("min_conf", "FLOAT64", min_confidence))

    where = " AND ".join(conditions)
    query = f"""
    SELECT id, source, SUBSTR(text, 1, 300) as text, department,
           sentiment, tone, confidence, created_at
    FROM `{DATASET}.enriched_feedback`
    WHERE {where}
    ORDER BY created_at DESC
    LIMIT {limit}
    """
    cfg = bigquery.QueryJobConfig(query_parameters=params)
    return [dict(row) for row in bq.query(query, job_config=cfg).result()]


# ─── 6. Departments List ──────────────────────────────────────────

@app.get("/api/departments")
async def list_departments():
    """Distinct departments + counts — for frontend filter dropdowns."""
    query = f"""
    SELECT department, COUNT(*) as count
    FROM `{DATASET}.enriched_feedback`
    WHERE department IS NOT NULL
    GROUP BY department
    ORDER BY count DESC
    """
    return [dict(row) for row in bq.query(query).result()]


# ─── 7. Semantic Search (Vertex AI Search) ─────────────────────────

@app.get("/api/search")
async def semantic_search(
    q: str = Query(..., min_length=2, description="Search query"),
    department: str = None,
    source: str = None,
):
    """Semantic search via Vertex AI Search — returns AI summary + results."""
    from search.search_feedback import search_feedback
    return search_feedback(q, department=department, source=source)


# ─── Health check ──────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "project": PROJECT}
