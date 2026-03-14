# Stakeholder Demo Guide — Feedback Intel

How to walk someone through the platform in 5 minutes, plus Q&A on architecture and design decisions.

---

## The 5-Minute Walkthrough

### Opening (30 seconds)

"This is an end-to-end customer feedback intelligence platform on GCP. It ingests feedback from four channels — support tickets, app reviews, surveys, and phone calls — transcribes audio with Chirp, classifies everything with Gemini, and makes it searchable through dashboards and semantic search."

### Architecture Walk (1 minute)

Open the README architecture diagram.

"Two ingestion paths feed the same BigQuery table:

1. **Batch** — CSVs land in Cloud Storage, trigger a Gen2 Cloud Function, which validates and streams to BigQuery.
2. **Streaming** — events hit Pub/Sub, an Apache Beam pipeline parses, validates, and writes to BigQuery. Runs locally on DirectRunner, deploys to Dataflow in production.

Phone calls go through Chirp 3 with speaker diarization — it separates agent from customer speech. Then everything runs through Gemini 2.5 Flash Lite for structured classification: department, sentiment, tone, key issues."

### Live Demo (2 minutes)

1. **Dashboard** — pipeline stats: 1,402 records, sentiment breakdown, department distribution, Chirp health (36 calls, 97% success rate)
2. **Transcript Viewer** — click a call, show the full transcript with classification metadata alongside it
3. **Explorer** — filter by department=Engineering, sentiment=negative. "These are the Engineering team's pain points."
4. **Semantic Search** — type "what are customers saying about login problems". Show the AI summary. "This matched 'authentication errors' and 'session timeouts' — zero keyword overlap. That's semantic search."

### Technical Depth (1 minute)

"A few things worth highlighting:

- **Prompt iteration**: V1 prompt had 72% accuracy. V2 with few-shot examples hit 84%. V3 with transcript-specific handling brought call classification up from 68% to 82%.
- **Evaluation transparency**: The data is synthetic (Gemini-generated), so classifier metrics have a ceiling. The evaluation framework — WER for Chirp, accuracy/confidence for classification — is designed to work with real data when it arrives.
- **Parameterized queries**: The API uses BigQuery `@param` bindings instead of string interpolation — standard practice for preventing SQL injection."

### Close (30 seconds)

"The full pipeline is reproducible — `gcloud_full_steps.sh` sets up every GCP resource from scratch. Every architectural decision is documented with the reasoning in Documenting_Progress.md."

---

## Q&A Reference

### Architecture & Design

**Q: Why BigQuery instead of Postgres/MySQL?**
Serverless, columnar, handles structured + semi-structured data, direct integration with every GCP service (Looker, Vertex AI Search, Dataflow). For analytics workloads — aggregations, filters, scans — it's the right tool. Partitioning and clustering give automatic cost control at scale.

**Q: Why Beam instead of another Cloud Function for streaming?**
Cloud Functions are per-invocation — one function per message. Beam distributes work across workers and can batch internally. It also supports windowing and stateful processing. The portability is key: same `pipeline.py` runs on DirectRunner locally or DataflowRunner in production. The runner is a CLI flag, not a code change.

**Q: Why two ingestion paths?**
Different patterns for different data shapes. Batch (Cloud Function) handles file-level uploads — a CSV with 2,000 records. Streaming (Beam) handles individual events — a webhook fires when a customer submits feedback. Both write to the same table. Most production systems have both.

**Q: How would this handle 10x/100x the volume?**
BigQuery scales horizontally — no changes needed. The Beam pipeline on Dataflow auto-scales workers. The bottleneck would be Gemini classification throughput — that's where request batching, async processing, and a dead-letter queue come in. The architecture doesn't change, just the operational parameters.

### AI & ML

**Q: Why Gemini Flash Lite instead of a fine-tuned model?**
Cost and iteration speed. Flash Lite is the cheapest Gemini model, and structured JSON output means no parsing failures. For classification with 8 departments and 3 sentiments, prompt engineering with few-shot examples gets 80-85% accuracy. Fine-tuning requires labeled training data — the ROI comes when prompt engineering plateaus.

**Q: How is the classifier evaluated?**
WER for Chirp accuracy (4% on synthetic audio — floor, not ceiling). For classification: accuracy by department, sentiment, and source type. Key finding: call transcripts classified worse than clean text (68% vs 84% on V2). Adding transcript-specific few-shot examples in V3 closed the gap. Synthetic data means the evaluation framework matters more than absolute numbers.

**Q: What's the confidence score?**
Gemini self-reports confidence 0-1 in its structured output. Records below 0.7 get flagged for human review (~8% of records). It's not calibrated — 0.8 doesn't mean 80% probability — but it correlates with actual errors. It's a triage signal, not a probability.

### GCP Specifics

**Q: How is IAM managed?**
Service account with least privilege. The pipeline SA has 7 roles, each added when the sprint needed it — documented in `gcloud_full_steps.sh`. In production, this would be Terraform with a module per service.

**Q: What happens when Chirp fails on an audio file?**
The error is captured in `call_transcripts.error_message` — the record exists with a null transcript. The pipeline logs and continues. Of 36 files, 35 succeeded, 1 failed (codec issue). Success rate is a first-class metric in the dashboard.

**Q: How does Vertex AI Search work here?**
RAG-as-a-service. Point it at a BigQuery table — it creates embeddings, indexes them, handles retrieval + AI-generated summaries. Key gotcha: for structured data, use `NO_CONTENT` mode. Fields need explicit annotations for indexable/searchable/retrievable — auto-detect only gets the types right.

### Production Considerations

**Q: What would change for production?**
Three things: (1) Terraform for infrastructure — the bash script doesn't handle state. (2) CI/CD for Beam and Cloud Functions — currently manual deploy. (3) Cloud Monitoring alerts on Chirp failure rate, classification latency, and BigQuery slot usage.

**Q: How is pipeline health monitored?**
Three layers: (1) `daily_summary` materialized view for volume trends. (2) `call_analytics` view for Chirp success rate and confidence. (3) The React dashboard surfaces all of this. For production, add Cloud Monitoring alerts — page if success rate drops below 90% or no records arrive for 2 hours.

**Q: Cost at scale?**
BigQuery: $6.25/TB scanned (our 1,402 rows = $0.00/query). Gemini Flash Lite: $0.075/million input tokens. Chirp: $0.016/minute of audio. Dataflow: ~$0.056/hr per vCPU. At scale, Gemini classification is the expensive part — batch and async processing keep it in budget.

---

## Key Talking Points

**Data Engineering:**
- Beam is the code, Dataflow is the runtime — like Docker and Kubernetes
- Cloud Function for batch files, Beam for real-time streams — same destination, different patterns
- Pub/Sub decouples producers from consumers — if transcription is slow, messages queue
- BigQuery streaming inserts are append-only for 30 minutes — design around it

**ML Engineering:**
- Structured JSON output from Gemini — no regex, no markdown stripping
- Evaluation on LLM-generated data measures the framework, not the classifier
- Prompt V1: 72% → V2 few-shot: 84% → V3 transcript-aware: 82% on calls
- Chirp WER 4% on synthetic audio — that's the floor, not the ceiling

**Search & Retrieval:**
- Vertex AI Search is RAG-as-a-service — no vector database to manage
- Semantic search matched 'billing complaints' to 'charge on my invoice' — zero keyword overlap

---

## Project Narrative

1. **Problem:** Customer feedback comes from 4 channels. Nobody reads it all. Teams need automated classification and searchable insights.
2. **Pipeline:** Audio → Chirp → text. All text → Gemini → structured classification. Everything lands in BigQuery.
3. **Access layers:** Looker for business stakeholders, semantic search for product managers, React dashboard for engineering visibility.
4. **Lessons:** Pick 2-3 from [Documenting_Progress.md](Documenting_Progress.md). The evaluation transparency point shows engineering maturity.
