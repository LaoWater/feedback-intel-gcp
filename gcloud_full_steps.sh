#!/bin/bash
# ============================================================
# feedback-intel-gcp — Full GCP Setup Script
# ============================================================
# Run this to replicate the entire project from scratch.
# Captures every gcloud command across all sprints.
#
# In production, this would be Terraform. For a portfolio
# project, a single bash script is the right level of
# infrastructure-as-code — replicable, version-controlled,
# reviewable.
# ============================================================

set -e  # Exit on first error

PROJECT_ID="feedback-intel-demo"
REGION="europe-west1"
SA_NAME="feedback-pipeline"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# ============================================================
# 1. PROJECT & CONFIG
# ============================================================
gcloud projects create $PROJECT_ID --name="Feedback Intel"
gcloud config set project $PROJECT_ID
gcloud config set compute/region $REGION

# Link billing account (required for any paid APIs)
# gcloud billing accounts list
# gcloud billing projects link $PROJECT_ID --billing-account=XXXXXX-XXXXXX-XXXXXX

# ============================================================
# 2. ENABLE APIs
# ============================================================
gcloud services enable \
  bigquery.googleapis.com \
  storage.googleapis.com \
  cloudfunctions.googleapis.com \
  aiplatform.googleapis.com \
  discoveryengine.googleapis.com \
  run.googleapis.com \
  speech.googleapis.com \
  texttospeech.googleapis.com \
  pubsub.googleapis.com \
  dataflow.googleapis.com \
  eventarc.googleapis.com

# ============================================================
# 3. SERVICE ACCOUNT + IAM ROLES
# ============================================================
# Create the pipeline service account
gcloud iam service-accounts create $SA_NAME \
  --display-name="Feedback Pipeline SA"

# --- Sprint 01 roles (foundation) ---
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/bigquery.dataEditor"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/aiplatform.user"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/storage.objectAdmin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/speech.client"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/pubsub.subscriber"

# --- Sprint 03 roles (Cloud Function deployment) ---
# Eventarc SA needs storage admin on the bucket
# Pipeline SA needs eventarc.eventReceiver
# GCS service agent needs pubsub.publisher
# Pipeline SA needs run.invoker (Gen2 functions ARE Cloud Run)
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/eventarc.eventReceiver"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/run.invoker"

# --- Sprint 08 roles (Dataflow) ---
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/dataflow.worker"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/dataflow.admin"

# ============================================================
# 4. BIGQUERY
# ============================================================
bq mk --location=EU ${PROJECT_ID}:feedback

# Tables created via SQL (see Development_Progress.md Sprint 01)
# raw_feedback, call_transcripts, enriched_feedback, daily_summary

# ============================================================
# 5. CLOUD STORAGE BUCKETS
# ============================================================
gcloud storage buckets create gs://feedback-intel-raw-data --location=$REGION
gcloud storage buckets create gs://feedback-intel-audio-calls --location=$REGION
gcloud storage buckets create gs://feedback-intel-audio-processed --location=$REGION
gcloud storage buckets create gs://feedback-intel-dataflow --location=$REGION   # Sprint 08

# ============================================================
# 6. PUB/SUB
# ============================================================
# Sprint 01: Audio upload notifications (GCS → Pub/Sub)
gcloud pubsub topics create audio-upload-events
gcloud pubsub subscriptions create audio-upload-sub --topic=audio-upload-events

# Wire GCS notifications → Pub/Sub
gcloud storage buckets notifications create gs://feedback-intel-audio-calls \
  --topic=audio-upload-events \
  --event-types=OBJECT_FINALIZE

# Sprint 08: Feedback event stream (application → Beam pipeline)
gcloud pubsub topics create feedback-raw
gcloud pubsub subscriptions create feedback-raw-sub --topic=feedback-raw

# ============================================================
# 7. VERIFY
# ============================================================
echo "=== Services ==="
gcloud services list --enabled --filter="name:(bigquery OR storage OR pubsub OR dataflow OR speech OR run)"

echo "=== SA Roles ==="
gcloud projects get-iam-policy $PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:$SA_EMAIL" \
  --format="table(bindings.role)"

echo "=== Buckets ==="
gcloud storage ls

echo "=== Pub/Sub Topics ==="
gcloud pubsub topics list

echo "=== Done ==="
